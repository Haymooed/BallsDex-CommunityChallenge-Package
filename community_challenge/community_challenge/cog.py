from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, List

import discord
from asgiref.sync import sync_to_async
from discord import app_commands
from discord.ext import commands
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from bd_models.models import Player

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
# Helpers
# ---------------------------------------------------------------------------

def _progress_bar(current: int, target: int, width: int = 20) -> str:
    ratio = min(1.0, current / max(1, target))
    filled = round(ratio * width)
    return "[" + "█" * filled + "░" * (width - filled) + f"] {round(ratio * 100, 1)}%"


def _type_emoji(challenge_type: str) -> str:
    return {"catch": "🎣", "trade": "🔄"}.get(challenge_type, "🏆")


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class CommunityChallenges(commands.GroupCog, name="challenge"):
    """Community-wide cooperative challenge system (BallsDex v3)."""

    def __init__(self, bot: "BallsDexBot") -> None:
        self.bot = bot
        self._completion_lock = asyncio.Lock()
        self._completing: set[int] = set()

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _active_challenges() -> List[CommunityChallenge]:
        return [c async for c in CommunityChallenge.objects.filter(enabled=True, completed=False)]

    @staticmethod
    async def _all_enabled_challenges() -> List[CommunityChallenge]:
        return [c async for c in CommunityChallenge.objects.filter(enabled=True)]

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
    # Progress tracking
    # ------------------------------------------------------------------

    async def add_progress(
        self, challenge: CommunityChallenge, player: Player, amount: int = 1
    ) -> int:
        """Atomically increment player contribution. Returns new community total."""

        @sync_to_async
        def _update() -> int:
            with transaction.atomic():
                entry, _ = ChallengeProgress.objects.select_for_update().get_or_create(
                    challenge=challenge, player=player, defaults={"amount": 0}
                )
                entry.amount += amount
                entry.save(update_fields=["amount", "last_updated"])

            return (
                ChallengeProgress.objects.filter(challenge=challenge).aggregate(
                    total=Sum("amount")
                )["total"]
                or 0
            )

        return await _update()

    # ------------------------------------------------------------------
    # Completion
    # ------------------------------------------------------------------

    async def check_and_complete(self, challenge: CommunityChallenge, total: int) -> None:
        if total < challenge.target_amount or challenge.completed:
            return

        async with self._completion_lock:
            refreshed = await CommunityChallenge.objects.aget(pk=challenge.pk)
            if refreshed.completed or challenge.pk in self._completing:
                return
            self._completing.add(challenge.pk)

        try:
            await self._complete_challenge(refreshed)
        finally:
            self._completing.discard(challenge.pk)

    async def _complete_challenge(self, challenge: CommunityChallenge) -> None:
        log.info("Challenge '%s' reached its goal — completing.", challenge.name)

        challenge.completed = True
        challenge.completed_at = timezone.now()
        await challenge.asave(update_fields=["completed", "completed_at"])

        rewarded = 0
        if challenge.reward_balls > 0:
            async for entry in ChallengeProgress.objects.filter(
                challenge=challenge, amount__gt=0
            ).select_related("player"):
                if await self._issue_reward(challenge, entry.player):
                    rewarded += 1

        log.info(
            "Challenge '%s' complete. Rewarded %d players with %d balls each.",
            challenge.name, rewarded, challenge.reward_balls,
        )
        await self._announce(challenge, rewarded)

    async def _issue_reward(self, challenge: CommunityChallenge, player: Player) -> bool:
        """
        Record reward issuance. Returns True if newly issued.
        Extend this to actually grant balls via BallsDex economy hooks.
        """
        try:
            await ChallengeReward.objects.acreate(
                challenge=challenge,
                player=player,
                balls_given=challenge.reward_balls,
            )
            return True
        except IntegrityError:
            return False  # already rewarded

    async def _announce(self, challenge: CommunityChallenge, rewarded: int) -> None:
        config = await ChallengeSettings.load()
        if not config.announcement_channel_id:
            return

        channel = self.bot.get_channel(config.announcement_channel_id)
        if not isinstance(channel, discord.TextChannel):
            log.warning("Announcement channel %s not found.", config.announcement_channel_id)
            return

        emoji = _type_emoji(challenge.challenge_type)
        embed = discord.Embed(
            title="🎉 Community Challenge Complete!",
            description=(
                f"{emoji} **{challenge.name}** has been beaten by the community!\n\n"
                f"{challenge.description}"
            ),
            colour=discord.Colour.gold(),
        )
        embed.add_field(
            name="🏆 Goal Reached",
            value=f"{challenge.target_amount:,} {challenge.get_challenge_type_display()}s",
            inline=True,
        )
        if challenge.reward_balls:
            embed.add_field(
                name="🎁 Reward",
                value=f"{challenge.reward_balls} ball(s) per contributor",
                inline=True,
            )
        embed.add_field(name="👥 Rewarded", value=f"{rewarded:,} players", inline=True)
        embed.set_footer(text="Thanks to everyone who participated!")

        try:
            await channel.send(embed=embed)
        except discord.HTTPException as exc:
            log.error("Failed to send completion announcement: %s", exc)

    # ------------------------------------------------------------------
    # Public API — call from other cogs/listeners
    # ------------------------------------------------------------------

    async def record_contribution(
        self, player: Player, contribution_type: str, amount: int = 1
    ) -> None:
        """
        Credit *amount* to all active challenges matching *contribution_type*.

        Call from your catching/trading listeners::

            cog = bot.cogs.get("challenge")
            if cog:
                await cog.record_contribution(player, "catch")
        """
        for challenge in await self._active_challenges():
            if challenge.challenge_type != contribution_type:
                continue
            new_total = await self.add_progress(challenge, player, amount)
            await self.check_and_complete(challenge, new_total)

    # ------------------------------------------------------------------
    # Commands
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
                "No challenges are active right now. Check back soon!", ephemeral=True
            )
            return

        embed = discord.Embed(
            title="🏆 Community Challenges",
            description="Work together to reach these goals!",
            colour=discord.Colour.blurple(),
        )

        for challenge in challenges:
            total = await self._challenge_total(challenge)
            emoji = _type_emoji(challenge.challenge_type)
            status = "✅ Completed!" if challenge.completed else _progress_bar(total, challenge.target_amount)
            value = (
                f"{challenge.description}\n"
                f"**Type:** {emoji} {challenge.get_challenge_type_display()}\n"
                f"**Progress:** {total:,} / {challenge.target_amount:,}\n"
                f"{status}"
            )
            if challenge.reward_balls:
                value += f"\n**Reward:** {challenge.reward_balls} ball(s) per contributor"
            embed.add_field(name=challenge.name, value=value, inline=False)

        embed.set_footer(text="Use /challenge leaderboard to see top contributors")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="leaderboard",
        description="See the top contributors for a community challenge.",
    )
    @app_commands.describe(challenge_id="The challenge to view.")
    async def leaderboard(self, interaction: Interaction, challenge_id: int) -> None:
        config = await ChallengeSettings.load()
        if not config.enabled:
            await interaction.response.send_message(
                "Community Challenges are currently disabled.", ephemeral=True
            )
            return

        try:
            challenge = await CommunityChallenge.objects.aget(pk=challenge_id, enabled=True)
        except CommunityChallenge.DoesNotExist:
            await interaction.response.send_message("Challenge not found.", ephemeral=True)
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
            embed.add_field(name="No contributions yet", value="Be the first!", inline=False)
        else:
            medals = ["🥇", "🥈", "🥉"]
            lines = []
            for rank, entry in enumerate(top, start=1):
                medal = medals[rank - 1] if rank <= 3 else f"`#{rank}`"
                lines.append(f"{medal} <@{entry.player.discord_id}> — **{entry.amount:,}**")
            embed.add_field(name="🏅 Top Contributors", value="\n".join(lines), inline=False)

        if challenge.completed and challenge.completed_at:
            embed.set_footer(text=f"Completed {challenge.completed_at.strftime('%B %d, %Y')}")
        else:
            embed.set_footer(text="Keep contributing!")

        await interaction.followup.send(embed=embed)

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
    # Event listener stubs — rename to match your BallsDex build's events
    # ------------------------------------------------------------------

    @commands.Cog.listener("on_ballsdex_ball_caught")
    async def _on_ball_caught(self, player: Player, **kwargs) -> None:
        await self.record_contribution(player, "catch")

    @commands.Cog.listener("on_ballsdex_trade_completed")
    async def _on_trade_completed(self, player_a: Player, player_b: Player, **kwargs) -> None:
        await self.record_contribution(player_a, "trade")
        await self.record_contribution(player_b, "trade")