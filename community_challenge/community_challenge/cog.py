from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING, List, Optional

import discord
from asgiref.sync import sync_to_async
from discord import app_commands
from discord.ext import commands
from django.db import IntegrityError, transaction
from django.db.models import Count, Sum
from django.utils import timezone

from bd_models.models import BallInstance, Player

from community_challenge.models import (
    ChallengeProgress,
    ChallengeReward,
    ChallengeSettings,
    CommunityChallenge,
    ChallengeType,
)

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger(__name__)
Interaction = discord.Interaction["BallsDexBot"]

# ---------------------------------------------------------------------------
# Message pattern matching for on_message event tracking
#
# These patterns match the BallsDex bot's own response messages.
# Each pattern is matched against embed descriptions/titles or message content.
#
# HOW THIS WORKS:
#   BallsDex sends a message/embed when a player catches, fails, or trades.
#   We listen to those bot messages and extract the player's Discord ID
#   from the text (BallsDex always mentions the player in its response).
# ---------------------------------------------------------------------------

# Matches bot catch confirmation — BallsDex says something like:
#   "<@123456789> caught **France**!"
# or for specials:
#   "<@123456789> caught **France** ✨ (Summer Special)!"
_RE_CATCH = re.compile(
    r"<@!?(?P<user_id>\d+)>\s+caught\s+\*\*(?P<ball>[^*]+)\*\*",
    re.IGNORECASE,
)

# Special catch — same pattern but also has a special name in parentheses or via embed field
_RE_CATCH_SPECIAL = re.compile(
    r"<@!?(?P<user_id>\d+)>\s+caught\s+\*\*(?P<ball>[^*]+)\*\*[^(]*\(",
    re.IGNORECASE,
)

# Wrong guess — BallsDex says something like:
#   "Wrong answer <@123456789>! The ball was France."
# or: "That's not it, <@123456789>."
_RE_WRONG = re.compile(
    r"(?:wrong answer|that'?s not it)[^<]*<@!?(?P<user_id>\d+)>",
    re.IGNORECASE,
)

# Trade completion — BallsDex trade embed has "Trade completed" in the title/description
# and the two players are mentioned in the embed footer or description.
# We'll match the embed title and extract both participant mentions.
_RE_TRADE_DONE = re.compile(r"trade\s+(?:completed|done|successful)", re.IGNORECASE)
_RE_MENTION = re.compile(r"<@!?(?P<user_id>\d+)>")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _progress_bar(current: int, target: int, width: int = 20) -> str:
    ratio = min(1.0, current / max(1, target))
    filled = round(ratio * width)
    return "[" + "█" * filled + "░" * (width - filled) + f"] {round(ratio * 100, 1)}%"


TYPE_EMOJI: dict[str, str] = {
    ChallengeType.CATCH_ANY:      "🎣",
    ChallengeType.CATCH_SPECIAL:  "✨",
    ChallengeType.GUESS_WRONG:    "❌",
    ChallengeType.GUESS_CORRECT:  "✅",
    ChallengeType.TRADE:          "🔄",
    ChallengeType.BALLS_OWNED:    "📦",
    ChallengeType.UNIQUE_BALLS:   "🗂️",
    ChallengeType.SPECIALS_OWNED: "🌟",
}

TYPE_LABEL: dict[str, str] = {
    ChallengeType.CATCH_ANY:      "Balls caught",
    ChallengeType.CATCH_SPECIAL:  "Specials caught",
    ChallengeType.GUESS_WRONG:    "Wrong guesses",
    ChallengeType.GUESS_CORRECT:  "Correct catches",
    ChallengeType.TRADE:          "Trades completed",
    ChallengeType.BALLS_OWNED:    "Total balls owned",
    ChallengeType.UNIQUE_BALLS:   "Unique ball types owned",
    ChallengeType.SPECIALS_OWNED: "Specials owned",
}


def _embed_text(message: discord.Message) -> str:
    """Combine all text fields from a message's embeds into one searchable string."""
    parts: list[str] = []
    if message.content:
        parts.append(message.content)
    for embed in message.embeds:
        if embed.title:
            parts.append(embed.title)
        if embed.description:
            parts.append(embed.description)
        for field in embed.fields:
            parts.append(field.name or "")
            parts.append(field.value or "")
        if embed.footer and embed.footer.text:
            parts.append(embed.footer.text)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class CommunityChallenges(commands.GroupCog, name="challenge"):
    """Community-wide cooperative challenge system (BallsDex v3)."""

    def __init__(self, bot: "BallsDexBot") -> None:
        self.bot = bot
        self._completion_lock = asyncio.Lock()
        self._completing: set[int] = set()
        # Cache of active challenges — refreshed every time ensure_cache() is called.
        # Avoids a DB query on every single message.
        self._cache: list[CommunityChallenge] = []
        self._cache_dirty: bool = True

    async def cog_load(self) -> None:
        await self._refresh_cache()

    async def _refresh_cache(self) -> None:
        self._cache = [
            c async for c in CommunityChallenge.objects.filter(enabled=True, completed=False)
        ]
        self._cache_dirty = False
        log.debug("Challenge cache refreshed: %d active challenges.", len(self._cache))

    def _invalidate_cache(self) -> None:
        self._cache_dirty = True

    async def _ensure_cache(self) -> list[CommunityChallenge]:
        if self._cache_dirty:
            await self._refresh_cache()
        return self._cache

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _all_enabled() -> list[CommunityChallenge]:
        return [c async for c in CommunityChallenge.objects.filter(enabled=True)]

    @staticmethod
    async def _challenge_total(challenge: CommunityChallenge) -> int:
        """
        For event-based challenges: sum of ChallengeProgress.amount.
        For snapshot challenges: live DB count across all players.
        """
        if challenge.challenge_type == ChallengeType.BALLS_OWNED:
            return await BallInstance.objects.acount()

        if challenge.challenge_type == ChallengeType.UNIQUE_BALLS:
            result = await (
                BallInstance.objects
                .values("ball_id")
                .distinct()
                .aaggregate(count=Count("ball_id"))
            )
            return result["count"] or 0

        if challenge.challenge_type == ChallengeType.SPECIALS_OWNED:
            return await BallInstance.objects.filter(special__isnull=False).acount()

        # Event-based: sum progress table
        result = await ChallengeProgress.objects.filter(challenge=challenge).aaggregate(
            total=Sum("amount")
        )
        return result["total"] or 0

    @staticmethod
    async def _top_contributors(
        challenge: CommunityChallenge, limit: int = 10
    ) -> list[ChallengeProgress]:
        qs = (
            ChallengeProgress.objects.filter(challenge=challenge)
            .select_related("player")
            .order_by("-amount")[:limit]
        )
        return [entry async for entry in qs]

    @staticmethod
    async def _get_player(discord_id: int) -> Optional[Player]:
        try:
            return await Player.objects.aget(discord_id=discord_id)
        except Player.DoesNotExist:
            return None

    # ------------------------------------------------------------------
    # Progress tracking
    # ------------------------------------------------------------------

    async def add_progress(
        self,
        challenge: CommunityChallenge,
        player: Player,
        amount: int = 1,
    ) -> int:
        """
        Atomically increment player contribution for event-based challenges.
        Returns new community total.
        """

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

    async def record_contribution(
        self,
        discord_id: int,
        contribution_type: str,
        amount: int = 1,
    ) -> None:
        """
        Credit a player for a specific contribution type across all matching active challenges.
        Creates the Player row via get_or_create if it doesn't exist yet.
        """
        active = await self._ensure_cache()
        matching = [c for c in active if c.challenge_type == contribution_type]
        if not matching:
            return

        player, _ = await Player.objects.aget_or_create(discord_id=discord_id)

        for challenge in matching:
            new_total = await self.add_progress(challenge, player, amount)
            await self.check_and_complete(challenge, new_total)

    # ------------------------------------------------------------------
    # Snapshot challenge check (called on /challenge view)
    # ------------------------------------------------------------------

    async def check_snapshot_challenges(self) -> None:
        """Pull live DB totals for snapshot challenges and check for completion."""
        active = await self._ensure_cache()
        for challenge in active:
            if not challenge.is_snapshot:
                continue
            total = await self._challenge_total(challenge)
            await self.check_and_complete(challenge, total)

    # ------------------------------------------------------------------
    # Completion
    # ------------------------------------------------------------------

    async def check_and_complete(
        self, challenge: CommunityChallenge, total: int
    ) -> None:
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
            self._invalidate_cache()

    async def _complete_challenge(self, challenge: CommunityChallenge) -> None:
        log.info("Community challenge '%s' reached its goal!", challenge.name)
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
            "Challenge '%s' complete — rewarded %d players with %d ball(s) each.",
            challenge.name, rewarded, challenge.reward_balls,
        )
        await self._announce(challenge, rewarded)

    async def _issue_reward(self, challenge: CommunityChallenge, player: Player) -> bool:
        """
        Record a reward. Returns True if newly issued.
        Extend this to grant actual BallInstances via your economy logic.
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

        emoji = TYPE_EMOJI.get(challenge.challenge_type, "🏆")
        embed = discord.Embed(
            title="🎉 Community Challenge Complete!",
            description=(
                f"{emoji} **{challenge.name}** has been beaten by the community!\n\n"
                f"{challenge.description}"
            ),
            colour=discord.Colour.gold(),
        )
        embed.add_field(
            name="🏆 Goal",
            value=f"{challenge.target_amount:,} {TYPE_LABEL.get(challenge.challenge_type, 'actions')}",
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
    # on_message — the only reliable event hook in BallsDex v3
    # (confirmed by grep: only 2 bot.dispatch calls exist, both in guildconfig)
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        # Only process messages from the bot itself
        if not self.bot.user or message.author.id != self.bot.user.id:
            return
        # Skip DMs
        if not message.guild:
            return
        # Fast-exit if no active event-based challenges
        active = await self._ensure_cache()
        event_types = {
            ChallengeType.CATCH_ANY,
            ChallengeType.CATCH_SPECIAL,
            ChallengeType.GUESS_WRONG,
            ChallengeType.GUESS_CORRECT,
            ChallengeType.TRADE,
        }
        if not any(c.challenge_type in event_types for c in active):
            return

        text = _embed_text(message)
        if not text:
            return

        await self._process_message(text, active)

    async def _process_message(
        self, text: str, active: list[CommunityChallenge]
    ) -> None:
        """Parse a bot message and credit the appropriate challenge types."""

        # ── Catch (any) ───────────────────────────────────────────────
        catch_match = _RE_CATCH.search(text)
        if catch_match:
            uid = int(catch_match.group("user_id"))

            # Check if it's a special catch (parenthesis after ball name = special)
            is_special = _RE_CATCH_SPECIAL.search(text) is not None

            if any(c.challenge_type == ChallengeType.CATCH_ANY for c in active):
                await self.record_contribution(uid, ChallengeType.CATCH_ANY)

            if is_special and any(c.challenge_type == ChallengeType.CATCH_SPECIAL for c in active):
                await self.record_contribution(uid, ChallengeType.CATCH_SPECIAL)

            # A successful catch also counts as a correct guess
            if any(c.challenge_type == ChallengeType.GUESS_CORRECT for c in active):
                await self.record_contribution(uid, ChallengeType.GUESS_CORRECT)
            return

        # ── Wrong guess ───────────────────────────────────────────────
        wrong_match = _RE_WRONG.search(text)
        if wrong_match:
            uid = int(wrong_match.group("user_id"))
            if any(c.challenge_type == ChallengeType.GUESS_WRONG for c in active):
                await self.record_contribution(uid, ChallengeType.GUESS_WRONG)
            return

        # ── Trade completed ───────────────────────────────────────────
        if _RE_TRADE_DONE.search(text):
            mentions = list({int(m.group("user_id")) for m in _RE_MENTION.finditer(text)})
            if any(c.challenge_type == ChallengeType.TRADE for c in active):
                for uid in mentions:
                    await self.record_contribution(uid, ChallengeType.TRADE)

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

        await interaction.response.defer()

        # Snapshot challenges are recalculated fresh on every view
        await self.check_snapshot_challenges()
        challenges = await self._all_enabled()

        if not challenges:
            await interaction.followup.send(
                "No challenges are active right now. Check back soon!"
            )
            return

        embed = discord.Embed(
            title="🏆 Community Challenges",
            description="Work together to reach these community goals!",
            colour=discord.Colour.blurple(),
        )

        for challenge in challenges:
            total = await self._challenge_total(challenge)
            emoji = TYPE_EMOJI.get(challenge.challenge_type, "🏆")
            label = TYPE_LABEL.get(challenge.challenge_type, "actions")

            if challenge.completed:
                status = "✅ **Completed!**"
            else:
                status = _progress_bar(total, challenge.target_amount)

            value = (
                f"{challenge.description}\n"
                f"**Type:** {emoji} {challenge.get_challenge_type_display()}\n"
                f"**Progress:** {total:,} / {challenge.target_amount:,} {label}\n"
                f"{status}"
            )
            if challenge.reward_balls:
                value += f"\n**Reward:** {challenge.reward_balls} ball(s) per contributor"

            embed.add_field(
                name=f"{emoji} {challenge.name}",
                value=value,
                inline=False,
            )

        embed.set_footer(text="Use /challenge leaderboard to see top contributors per challenge")
        await interaction.followup.send(embed=embed)

    @app_commands.command(
        name="leaderboard",
        description="Top contributors for a community challenge.",
    )
    @app_commands.describe(challenge_id="Which challenge to inspect.")
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
        emoji = TYPE_EMOJI.get(challenge.challenge_type, "🏆")
        label = TYPE_LABEL.get(challenge.challenge_type, "actions")

        embed = discord.Embed(
            title=f"{emoji} {challenge.name} — Leaderboard",
            description=(
                f"{challenge.description}\n\n"
                f"**Community Progress:** {total:,} / {challenge.target_amount:,} {label}\n"
                f"{_progress_bar(total, challenge.target_amount)}"
            ),
            colour=discord.Colour.gold() if challenge.completed else discord.Colour.blurple(),
        )

        if challenge.is_snapshot:
            embed.add_field(
                name="ℹ️ Snapshot Challenge",
                value=(
                    "This challenge tracks a live database total rather than individual events. "
                    "The leaderboard shows players who have manually contributed via commands."
                ),
                inline=False,
            )

        if not top:
            embed.add_field(
                name="No tracked contributions yet",
                value="Start catching, trading, or guessing to appear here!",
                inline=False,
            )
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
            embed.set_footer(text="Keep going — every action counts!")

        await interaction.followup.send(embed=embed)

    @leaderboard.autocomplete("challenge_id")
    async def _autocomplete_challenge(
        self, interaction: Interaction, current: str
    ) -> list[app_commands.Choice[int]]:
        challenges = await self._all_enabled()
        return [
            app_commands.Choice(
                name=f"{'✅ ' if c.completed else ''}{c.name} ({c.get_challenge_type_display()})",
                value=c.pk,
            )
            for c in challenges
            if current.lower() in c.name.lower()
        ][:25]