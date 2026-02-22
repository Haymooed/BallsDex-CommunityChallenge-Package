from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, List, Optional

import discord
from asgiref.sync import sync_to_async
from discord import app_commands
from discord.ext import commands
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from bd_models.models import BallInstance, Player

from community_challenge.models import (
    ChallengeProgress,
    ChallengeReward,
    ChallengeSettings,
    CommunityChallenge,
)

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger(__name__)
Interaction = discord.Interaction["BallsDexBot"]

# ---------------------------------------------------------------------------
# Progress bar helper
# ---------------------------------------------------------------------------

def _progress_bar(current: int, target: int, width: int = 20) -> str:
    """Return a Unicode block-style progress bar."""
    ratio = min(1.0, current / max(1, target))
    filled = round(ratio * width)
    bar = "█" * filled + "░" * (width - filled)
    pct = round(ratio * 100, 1)
    return f"[{bar}] {pct}%"


def _type_emoji(challenge_type: str) -> str:
    return {
        "collect": "📦",
        "trade":   "🔄",
        "craft":   "⚒️",
        "catch":   "🎣",
        "donate":  "🎁",
    }.get(challenge_type, "🏆")


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class CommunityChallenges(commands.GroupCog, name="challenge"):
    """Community-wide cooperative challenge system (BallsDex v3)."""

    def __init__(self, bot: "BallsDexBot") -> None:
        self.bot = bot
        # Lock prevents race conditions when multiple events fire simultaneously
        # and both try to mark a challenge complete.
        self._completion_lock = asyncio.Lock()
        # Cache of challenge IDs currently being completed, to skip redundant work.
        self._completing: set[int] = set()

    # ------------------------------------------------------------------
    # Internal helpers — database queries
    # ------------------------------------------------------------------

    @staticmethod
    async def _active_challenges() -> List[CommunityChallenge]:
        qs = CommunityChallenge.objects.filter(enabled=True, completed=False)
        return [c async for c in qs]

    @staticmethod
    async def _all_enabled_challenges() -> List[CommunityChallenge]:
        qs = CommunityChallenge.objects.filter(enabled=True)
        return [c async for c in qs]

    @staticmethod
    async def _challenge_total(challenge: CommunityChallenge) -> int:
        result = await ChallengeProgress.objects.filter(challenge=challenge).aaggregate(
            total=Sum("amount")
        )
        return result["total"] or 0

    @staticmethod
    async def _top_contributors(
        challenge: CommunityChallenge, limit: int = 10
    ) -> List[ChallengeProgress]:
        qs = (
            ChallengeProgress.objects.filter(challenge=challenge)
            .select_related("player")
            .order_by("-amount")[:limit]
        )
        return [entry async for entry in qs]

    # ------------------------------------------------------------------
    # Progress contribution
    # ------------------------------------------------------------------

    async def add_progress(
        self,
        challenge: CommunityChallenge,
        player: Player,
        amount: int = 1,
    ) -> int:
        """
        Increment a player's contribution to *challenge* by *amount*.
        Returns the new community total for the challenge.
        Thread-safe via select_for_update inside a transaction.
        """

        @sync_to_async
        def _update() -> int:
            with transaction.atomic():
                entry, _ = ChallengeProgress.objects.select_for_update().get_or_create(
                    challenge=challenge, player=player, defaults={"amount": 0}
                )
                entry.amount += amount
                entry.save(update_fields=["amount", "last_updated"])

            total = (
                ChallengeProgress.objects.filter(challenge=challenge).aggregate(
                    total=Sum("amount")
                )["total"]
                or 0
            )
            return total

        return await _update()

    # ------------------------------------------------------------------
    # Completion logic
    # ------------------------------------------------------------------

    async def check_and_complete(
        self, challenge: CommunityChallenge, total: int
    ) -> None:
        """
        If *total* has reached the challenge target, fire completion once.
        All work is guarded by _completion_lock to stay async-safe.
        """
        if total < challenge.target_amount:
            return
        if challenge.completed:
            return

        async with self._completion_lock:
            # Re-check inside the lock to avoid double-completion.
            refreshed = await CommunityChallenge.objects.aget(pk=challenge.pk)
            if refreshed.completed:
                return
            if challenge.pk in self._completing:
                return

            self._completing.add(challenge.pk)

        try:
            await self._complete_challenge(refreshed)
        finally:
            self._completing.discard(challenge.pk)

    async def _complete_challenge(self, challenge: CommunityChallenge) -> None:
        """Mark completed, distribute rewards, and send announcement."""
        log.info("Challenge '%s' completed! Processing rewards...", challenge.name)

        # Mark as completed in DB
        challenge.completed = True
        challenge.completed_at = timezone.now()
        await challenge.asave(update_fields=["completed", "completed_at"])

        # Distribute rewards to all contributors
        rewarded: List[int] = []
        if challenge.reward_item:
            contributors_qs = ChallengeProgress.objects.filter(
                challenge=challenge, amount__gt=0
            ).select_related("player")

            async for entry in contributors_qs:
                issued = await self._issue_reward(challenge, entry.player)
                if issued:
                    rewarded.append(entry.player.discord_id)

        log.info(
            "Challenge '%s': rewarded %d contributors with %d× %s.",
            challenge.name,
            len(rewarded),
            challenge.reward_quantity,
            challenge.reward_item or "(no reward item)",
        )

        # Announce
        await self._announce_completion(challenge, len(rewarded))

    async def _issue_reward(
        self, challenge: CommunityChallenge, player: Player
    ) -> bool:
        """
        Record a reward for *player*. Returns True if reward was newly issued.

        NOTE: Extend this method to actually grant in-game items / currency
        once your economy integration is ready. The ChallengeReward table
        provides an idempotency guard so double-runs are safe.
        """
        try:
            await ChallengeReward.objects.acreate(
                challenge=challenge,
                player=player,
                reward_item=challenge.reward_item,
                reward_quantity=challenge.reward_quantity,
            )
            log.debug(
                "Reward issued: %s × %d → player %s",
                challenge.reward_item,
                challenge.reward_quantity,
                player.discord_id,
            )
            return True
        except IntegrityError:
            # Already rewarded (unique_together guard).
            return False

    async def _announce_completion(
        self, challenge: CommunityChallenge, rewarded_count: int
    ) -> None:
        config = await ChallengeSettings.load()
        if not config.announcement_channel_id:
            return

        channel = self.bot.get_channel(config.announcement_channel_id)
        if not isinstance(channel, discord.TextChannel):
            log.warning(
                "Announcement channel %s not found or not a TextChannel.",
                config.announcement_channel_id,
            )
            return

        emoji = _type_emoji(challenge.challenge_type)
        embed = discord.Embed(
            title=f"🎉 Community Challenge Completed!",
            description=(
                f"{emoji} **{challenge.name}** has been conquered by the community!\n\n"
                f"{challenge.description}"
            ),
            colour=discord.Colour.gold(),
        )
        embed.add_field(
            name="🏆 Goal Reached",
            value=f"{challenge.target_amount:,} {challenge.get_challenge_type_display()}s",
            inline=True,
        )
        if challenge.reward_item:
            embed.add_field(
                name="🎁 Reward",
                value=f"{challenge.reward_quantity}× **{challenge.reward_item}**",
                inline=True,
            )
        embed.add_field(
            name="👥 Contributors Rewarded",
            value=f"{rewarded_count:,} players",
            inline=True,
        )
        embed.set_footer(text="Thanks to everyone who participated!")

        try:
            await channel.send(embed=embed)
        except discord.HTTPException as exc:
            log.error("Failed to send completion announcement: %s", exc)

    # ------------------------------------------------------------------
    # Public event hook — call this from your ball-catching / trade listeners
    # ------------------------------------------------------------------

    async def record_contribution(
        self,
        player: Player,
        contribution_type: str,
        amount: int = 1,
    ) -> None:
        """
        Public API for other cogs/listeners to call when a player performs an
        action. Pass ``contribution_type`` as one of the ChallengeType values
        (e.g. "catch", "trade"). Matching active challenges are credited.

        Example (from a catching listener)::

            cog = bot.cogs.get("challenge")
            if cog:
                await cog.record_contribution(player, "catch")
        """
        challenges = await self._active_challenges()
        for challenge in challenges:
            if challenge.challenge_type != contribution_type:
                continue

            new_total = await self.add_progress(challenge, player, amount)
            await self.check_and_complete(challenge, new_total)

    # ------------------------------------------------------------------
    # Slash commands
    # ------------------------------------------------------------------

    @app_commands.command(name="view", description="View all active community challenges.")
    async def view(self, interaction: Interaction) -> None:
        config = await ChallengeSettings.load()
        if not config.enabled:
            await interaction.response.send_message(
                "Community Challenges are currently disabled.", ephemeral=True
            )
            return

        challenges = await self._all_enabled_challenges()
        if not challenges:
            await interaction.response.send_message(
                "There are no active challenges right now. Check back soon!",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="🏆 Community Challenges",
            description="Work together to reach these goals and earn rewards!",
            colour=discord.Colour.blurple(),
        )

        for challenge in challenges:
            total = await self._challenge_total(challenge)
            bar = _progress_bar(total, challenge.target_amount)
            emoji = _type_emoji(challenge.challenge_type)
            status = "✅ Completed" if challenge.completed else f"{bar}"

            field_value = (
                f"{challenge.description}\n"
                f"**Type:** {emoji} {challenge.get_challenge_type_display()}\n"
                f"**Progress:** {total:,} / {challenge.target_amount:,}\n"
                f"{status}"
            )
            if challenge.reward_item:
                field_value += (
                    f"\n**Reward:** {challenge.reward_quantity}× {challenge.reward_item}"
                )

            embed.add_field(
                name=challenge.name,
                value=field_value,
                inline=False,
            )

        embed.set_footer(text="Use /challenge leaderboard to see top contributors")
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(
        name="leaderboard",
        description="See the top contributors for a community challenge.",
    )
    @app_commands.describe(challenge_id="The challenge to view (use autocomplete).")
    async def leaderboard(
        self, interaction: Interaction, challenge_id: int
    ) -> None:
        config = await ChallengeSettings.load()
        if not config.enabled:
            await interaction.response.send_message(
                "Community Challenges are currently disabled.", ephemeral=True
            )
            return

        try:
            challenge = await CommunityChallenge.objects.aget(pk=challenge_id, enabled=True)
        except CommunityChallenge.DoesNotExist:
            await interaction.response.send_message(
                "Challenge not found. Use autocomplete to pick a valid one.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        total = await self._challenge_total(challenge)
        top = await self._top_contributors(challenge, limit=10)

        emoji = _type_emoji(challenge.challenge_type)
        embed = discord.Embed(
            title=f"{emoji} {challenge.name} — Leaderboard",
            description=(
                f"{challenge.description}\n\n"
                f"**Community Progress:** {total:,} / {challenge.target_amount:,}\n"
                f"{_progress_bar(total, challenge.target_amount)}"
            ),
            colour=discord.Colour.gold() if challenge.completed else discord.Colour.blurple(),
        )

        if not top:
            embed.add_field(
                name="No contributions yet",
                value="Be the first to contribute!",
                inline=False,
            )
        else:
            medals = ["🥇", "🥈", "🥉"]
            lines: List[str] = []
            for rank, entry in enumerate(top, start=1):
                medal = medals[rank - 1] if rank <= 3 else f"`#{rank}`"
                user_tag = f"<@{entry.player.discord_id}>"
                lines.append(f"{medal} {user_tag} — **{entry.amount:,}**")

            embed.add_field(
                name="🏅 Top Contributors",
                value="\n".join(lines),
                inline=False,
            )

        if challenge.completed and challenge.completed_at:
            embed.set_footer(
                text=f"Completed on {challenge.completed_at.strftime('%B %d, %Y')}"
            )
        else:
            embed.set_footer(text="Keep contributing to reach the goal!")

        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------------
    # Autocomplete
    # ------------------------------------------------------------------

    @leaderboard.autocomplete("challenge_id")
    async def autocomplete_challenge(
        self, interaction: Interaction, current: str
    ) -> List[app_commands.Choice[int]]:
        challenges = await self._all_enabled_challenges()
        return [
            app_commands.Choice(
                name=f"{'✅ ' if c.completed else ''}{c.name}",
                value=c.pk,
            )
            for c in challenges
            if current.lower() in c.name.lower()
        ][:25]

    # ------------------------------------------------------------------
    # Listener examples — wire up to real BallsDex events as needed
    # ------------------------------------------------------------------

    @commands.Cog.listener("on_ballsdex_ball_caught")
    async def _on_ball_caught(
        self, player: Player, ball_instance: BallInstance
    ) -> None:
        """
        Example listener that credits 'catch' challenges whenever a ball is caught.
        Hook name may differ in your BallsDex build — adjust as needed.
        """
        await self.record_contribution(player, "catch")

    @commands.Cog.listener("on_ballsdex_trade_completed")
    async def _on_trade_completed(
        self, player_a: Player, player_b: Player
    ) -> None:
        """
        Example listener for 'trade' challenges.
        Both players involved in a trade get credit.
        """
        await self.record_contribution(player_a, "trade")
        await self.record_contribution(player_b, "trade")
