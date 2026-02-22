from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

import discord
from asgiref.sync import sync_to_async
from discord import app_commands
from discord.ext import commands
from django.db import IntegrityError, transaction
from django.db.models import Count, Sum
from django.utils import timezone

from bd_models.models import Ball, BallInstance, Player, Special

from community_challenge.models import (
    ChallengeProgress,
    ChallengeReward,
    ChallengeSettings,
    CommunityChallenge,
    ChallengeType,
    EVENT_TYPES,
    SNAPSHOT_TYPES,
)

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger(__name__)
Interaction = discord.Interaction["BallsDexBot"]


# ---------------------------------------------------------------------------
# Message parsing
#
# From the screenshot, the bot EDITS the spawn message to show the catch:
#   "@haymooed You caught **Pink Popsicle**! (#660, -6%/-1%)"
#
# Key facts:
#   • "@username" is a plain mention (not <@id>) — we resolve via BallInstance
#   • Ball name is between ** **
#   • Instance ID is #NUMBER — we query BallInstance(pk=NUMBER) for player/ball/special
#   • The edit happens to the spawn message content (not an embed)
#
# Wrong guess message (separate bot message, not an edit):
#   "That is not the correct name haymooed, try again!" (or similar)
#
# Trade completed (bot sends embed with title containing "trade" + "complete"):
#   Mentions both players as <@id> in the embed footer or description.
# ---------------------------------------------------------------------------

# Matches: "@username You caught **Ball Name**! (#123, ...)"
# Groups: ball_name, instance_id
_RE_CATCH = re.compile(
    r"You caught \*\*(?P<ball_name>[^*]+)\*\*[^(]*\(#(?P<instance_id>\d+)",
    re.IGNORECASE,
)

# Wrong guess — "That is not the correct name haymooed" or "Wrong answer"
_RE_WRONG = re.compile(
    r"(?:that is not the correct name|wrong answer|incorrect)[^\n]*?(?P<username>\w+)",
    re.IGNORECASE,
)

# Trade done embed title
_RE_TRADE_DONE = re.compile(r"trade\s+(?:completed?|done|successful)", re.IGNORECASE)
_RE_MENTION = re.compile(r"<@!?(?P<user_id>\d+)>")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _progress_bar(current: int, target: int, width: int = 20) -> str:
    ratio = min(1.0, current / max(1, target))
    filled = round(ratio * width)
    return "[" + "█" * filled + "░" * (width - filled) + f"] {round(ratio * 100, 1)}%"


TYPE_EMOJI: dict[str, str] = {
    ChallengeType.CATCH_ANY:             "🎣",
    ChallengeType.CATCH_SPECIFIC:        "🎯",
    ChallengeType.CATCH_SPECIAL:         "✨",
    ChallengeType.CATCH_SPECIFIC_SPECIAL:"🌟",
    ChallengeType.GUESS_WRONG:           "❌",
    ChallengeType.TRADE:                 "🔄",
    ChallengeType.BALLS_OWNED:           "📦",
    ChallengeType.UNIQUE_BALLS:          "🗂️",
    ChallengeType.SPECIALS_OWNED:        "💫",
}

TYPE_LABEL: dict[str, str] = {
    ChallengeType.CATCH_ANY:             "balls caught",
    ChallengeType.CATCH_SPECIFIC:        "specific balls caught",
    ChallengeType.CATCH_SPECIAL:         "specials caught",
    ChallengeType.CATCH_SPECIFIC_SPECIAL:"specific specials caught",
    ChallengeType.GUESS_WRONG:           "wrong guesses",
    ChallengeType.TRADE:                 "trades completed",
    ChallengeType.BALLS_OWNED:           "balls owned",
    ChallengeType.UNIQUE_BALLS:          "unique ball types owned",
    ChallengeType.SPECIALS_OWNED:        "specials owned",
}


def _embed_text(message: discord.Message) -> str:
    parts: list[str] = [message.content or ""]
    for embed in message.embeds:
        for piece in (embed.title, embed.description):
            if piece:
                parts.append(piece)
        for field in embed.fields:
            parts.append(f"{field.name or ''} {field.value or ''}")
        if embed.footer and embed.footer.text:
            parts.append(embed.footer.text)
    return "\n".join(parts)


@dataclass
class CatchEvent:
    instance_id: int
    ball_id: int
    player_id: int       # bd_models Player pk
    discord_id: int      # Discord user ID
    special_id: Optional[int]
    is_special: bool


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class CommunityChallenges(commands.GroupCog, name="challenge"):
    """Community-wide cooperative challenge system (BallsDex v3)."""

    def __init__(self, bot: "BallsDexBot") -> None:
        self.bot = bot
        self._completion_lock = asyncio.Lock()
        self._completing: set[int] = set()
        self._cache: list[CommunityChallenge] = []
        self._cache_dirty: bool = True

    async def cog_load(self) -> None:
        await self._refresh_cache()

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    async def _refresh_cache(self) -> None:
        self._cache = [
            c async for c in CommunityChallenge.objects.filter(
                enabled=True, completed=False
            ).select_related("ball_filter", "special_filter")
        ]
        self._cache_dirty = False
        log.debug("Challenge cache: %d active challenges.", len(self._cache))

    def _invalidate_cache(self) -> None:
        self._cache_dirty = True

    async def _ensure_cache(self) -> list[CommunityChallenge]:
        if self._cache_dirty:
            await self._refresh_cache()
        return self._cache

    # ------------------------------------------------------------------
    # DB totals
    # ------------------------------------------------------------------

    @staticmethod
    async def _challenge_total(challenge: CommunityChallenge) -> int:
        ct = challenge.challenge_type
        if ct == ChallengeType.BALLS_OWNED:
            return await BallInstance.objects.acount()
        if ct == ChallengeType.UNIQUE_BALLS:
            r = await BallInstance.objects.values("ball_id").distinct().aaggregate(
                count=Count("ball_id")
            )
            return r["count"] or 0
        if ct == ChallengeType.SPECIALS_OWNED:
            return await BallInstance.objects.filter(special__isnull=False).acount()
        # Event-based
        r = await ChallengeProgress.objects.filter(challenge=challenge).aaggregate(
            total=Sum("amount")
        )
        return r["total"] or 0

    @staticmethod
    async def _top_contributors(
        challenge: CommunityChallenge, limit: int = 10
    ) -> list[ChallengeProgress]:
        return [
            e async for e in ChallengeProgress.objects.filter(challenge=challenge)
            .select_related("player")
            .order_by("-amount")[:limit]
        ]

    # ------------------------------------------------------------------
    # Progress tracking
    # ------------------------------------------------------------------

    async def add_progress(
        self,
        challenge: CommunityChallenge,
        player: Player,
        amount: int = 1,
    ) -> int:
        @sync_to_async
        def _update() -> int:
            with transaction.atomic():
                entry, _ = ChallengeProgress.objects.select_for_update().get_or_create(
                    challenge=challenge, player=player, defaults={"amount": 0}
                )
                entry.amount += amount
                entry.save(update_fields=["amount", "last_updated"])
            return (
                ChallengeProgress.objects.filter(challenge=challenge)
                .aggregate(total=Sum("amount"))["total"]
                or 0
            )
        return await _update()

    def _catch_matches_challenge(
        self, challenge: CommunityChallenge, event: CatchEvent
    ) -> bool:
        """Return True if this catch event satisfies the challenge's type and filters."""
        ct = challenge.challenge_type

        if ct == ChallengeType.CATCH_ANY:
            return True

        if ct == ChallengeType.CATCH_SPECIFIC:
            # Must have a ball_filter set and it must match
            return (
                challenge.ball_filter_id is not None
                and challenge.ball_filter_id == event.ball_id
            )

        if ct == ChallengeType.CATCH_SPECIAL:
            return event.is_special

        if ct == ChallengeType.CATCH_SPECIFIC_SPECIAL:
            if not event.is_special:
                return False
            if challenge.special_filter_id is None:
                # No specific special required — any special counts
                return True
            return challenge.special_filter_id == event.special_id

        return False

    async def handle_catch(self, event: CatchEvent) -> None:
        """Credit all matching active challenges for a catch event."""
        active = await self._ensure_cache()
        catch_challenges = [
            c for c in active
            if c.challenge_type in (
                ChallengeType.CATCH_ANY,
                ChallengeType.CATCH_SPECIFIC,
                ChallengeType.CATCH_SPECIAL,
                ChallengeType.CATCH_SPECIFIC_SPECIAL,
            )
        ]
        if not catch_challenges:
            return

        player = await Player.objects.aget(pk=event.player_id)
        for challenge in catch_challenges:
            if self._catch_matches_challenge(challenge, event):
                total = await self.add_progress(challenge, player)
                await self.check_and_complete(challenge, total)

    async def handle_wrong_guess(self, discord_id: int) -> None:
        active = await self._ensure_cache()
        matching = [c for c in active if c.challenge_type == ChallengeType.GUESS_WRONG]
        if not matching:
            return
        player, _ = await Player.objects.aget_or_create(discord_id=discord_id)
        for challenge in matching:
            total = await self.add_progress(challenge, player)
            await self.check_and_complete(challenge, total)

    async def handle_trade(self, discord_ids: list[int]) -> None:
        active = await self._ensure_cache()
        matching = [c for c in active if c.challenge_type == ChallengeType.TRADE]
        if not matching:
            return
        for discord_id in discord_ids:
            player, _ = await Player.objects.aget_or_create(discord_id=discord_id)
            for challenge in matching:
                total = await self.add_progress(challenge, player)
                await self.check_and_complete(challenge, total)

    async def check_snapshot_challenges(self) -> None:
        active = await self._ensure_cache()
        for challenge in active:
            if challenge.is_snapshot:
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
            "Challenge '%s' done — rewarded %d players with %d ball(s) each.",
            challenge.name, rewarded, challenge.reward_balls,
        )
        await self._announce(challenge, rewarded)

    async def _issue_reward(self, challenge: CommunityChallenge, player: Player) -> bool:
        try:
            await ChallengeReward.objects.acreate(
                challenge=challenge,
                player=player,
                balls_given=challenge.reward_balls,
            )
            return True
        except IntegrityError:
            return False

    async def _announce(self, challenge: CommunityChallenge, rewarded: int) -> None:
        config = await ChallengeSettings.load()
        if not config.announcement_channel_id:
            return
        channel = self.bot.get_channel(config.announcement_channel_id)
        if not isinstance(channel, discord.TextChannel):
            log.warning("Announcement channel %s not found.", config.announcement_channel_id)
            return

        emoji = TYPE_EMOJI.get(challenge.challenge_type, "🏆")
        label = TYPE_LABEL.get(challenge.challenge_type, "actions")
        embed = discord.Embed(
            title="🎉 Community Challenge Complete!",
            description=f"{emoji} **{challenge.name}** has been beaten!\n\n{challenge.description}",
            colour=discord.Colour.gold(),
        )
        embed.add_field(
            name="🏆 Goal",
            value=f"{challenge.target_amount:,} {label}",
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
    # Discord event listeners
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_message_edit(
        self, before: discord.Message, after: discord.Message
    ) -> None:
        """
        BallsDex edits the spawn message when a ball is caught:
          Before: "Pink Popsicle just spawned. Quickly type its name..."
          After:  "@haymooed You caught **Pink Popsicle**! (#660, -6%/-1%)"

        We detect the edit, extract the BallInstance ID, then look up
        player + ball + special from the database.
        """
        if not self.bot.user or after.author.id != self.bot.user.id:
            return
        if not after.guild:
            return

        # Only process edits that added a catch confirmation
        text = after.content or ""
        if "You caught" not in text:
            return
        # Make sure it wasn't already processed (before also had "You caught")
        if before.content and "You caught" in before.content:
            return

        match = _RE_CATCH.search(text)
        if not match:
            return

        instance_id = int(match.group("instance_id"))

        # Look up the BallInstance to get player + ball + special
        try:
            instance = await BallInstance.objects.select_related(
                "player", "ball", "special"
            ).aget(pk=instance_id)
        except BallInstance.DoesNotExist:
            log.warning("BallInstance #%d not found after catch edit.", instance_id)
            return

        event = CatchEvent(
            instance_id=instance_id,
            ball_id=instance.ball_id,
            player_id=instance.player_id,
            discord_id=instance.player.discord_id,
            special_id=instance.special_id,
            is_special=instance.special_id is not None,
        )

        await self.handle_catch(event)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Handles wrong guesses and trade completions (separate bot messages, not edits)."""
        if not self.bot.user or message.author.id != self.bot.user.id:
            return
        if not message.guild:
            return

        active = await self._ensure_cache()
        text = _embed_text(message)
        if not text:
            return

        # ── Wrong guess ───────────────────────────────────────────────
        if any(c.challenge_type == ChallengeType.GUESS_WRONG for c in active):
            wrong_match = _RE_WRONG.search(text)
            if wrong_match:
                # Wrong guess messages don't include a user ID, only username.
                # We can't reliably map username → discord_id without fetching guild members.
                # Best effort: look for any <@id> mention in the message.
                mention = _RE_MENTION.search(text)
                if mention:
                    await self.handle_wrong_guess(int(mention.group("user_id")))
                # If no mention found, we skip — can't safely credit an unknown user.
                return

        # ── Trade completed ───────────────────────────────────────────
        if any(c.challenge_type == ChallengeType.TRADE for c in active):
            if _RE_TRADE_DONE.search(text):
                ids = list({int(m.group("user_id")) for m in _RE_MENTION.finditer(text)})
                if ids:
                    await self.handle_trade(ids)

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
        await self.check_snapshot_challenges()

        challenges = [
            c async for c in CommunityChallenge.objects.filter(enabled=True)
            .select_related("ball_filter", "special_filter")
        ]
        if not challenges:
            await interaction.followup.send("No challenges active right now. Check back soon!")
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
            status = "✅ **Completed!**" if challenge.completed else _progress_bar(total, challenge.target_amount)

            # Build filter description
            filters: list[str] = []
            if challenge.ball_filter:
                filters.append(f"Ball: **{challenge.ball_filter.country}**")
            if challenge.special_filter:
                filters.append(f"Special: **{challenge.special_filter.name}**")
            filter_line = f"\n{' • '.join(filters)}" if filters else ""

            value = (
                f"{challenge.description}{filter_line}\n"
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

        embed.set_footer(text="Use /challenge leaderboard to see top contributors")
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
            challenge = await CommunityChallenge.objects.select_related(
                "ball_filter", "special_filter"
            ).aget(pk=challenge_id, enabled=True)
        except CommunityChallenge.DoesNotExist:
            await interaction.response.send_message("Challenge not found.", ephemeral=True)
            return

        await interaction.response.defer()
        total = await self._challenge_total(challenge)
        top = await self._top_contributors(challenge, limit=10)
        emoji = TYPE_EMOJI.get(challenge.challenge_type, "🏆")
        label = TYPE_LABEL.get(challenge.challenge_type, "actions")

        # Filter description
        filters: list[str] = []
        if challenge.ball_filter:
            filters.append(f"Ball: **{challenge.ball_filter.country}**")
        if challenge.special_filter:
            filters.append(f"Special: **{challenge.special_filter.name}**")
        filter_line = ("\n" + " • ".join(filters)) if filters else ""

        embed = discord.Embed(
            title=f"{emoji} {challenge.name} — Leaderboard",
            description=(
                f"{challenge.description}{filter_line}\n\n"
                f"**Type:** {emoji} {challenge.get_challenge_type_display()}\n"
                f"**Progress:** {total:,} / {challenge.target_amount:,} {label}\n"
                f"{_progress_bar(total, challenge.target_amount)}"
            ),
            colour=discord.Colour.gold() if challenge.completed else discord.Colour.blurple(),
        )

        if challenge.is_snapshot:
            embed.add_field(
                name="ℹ️ Snapshot Challenge",
                value="This challenge measures a live database total, not individual events.",
                inline=False,
            )

        if not top:
            embed.add_field(
                name="No contributions yet",
                value="Start catching or trading to appear here!",
                inline=False,
            )
        else:
            medals = ["🥇", "🥈", "🥉"]
            lines = [
                f"{medals[r-1] if r <= 3 else f'`#{r}`'} <@{e.player.discord_id}> — **{e.amount:,}**"
                for r, e in enumerate(top, 1)
            ]
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
        challenges = [
            c async for c in CommunityChallenge.objects.filter(enabled=True)
        ]
        return [
            app_commands.Choice(
                name=f"{'✅ ' if c.completed else ''}{c.name} ({c.get_challenge_type_display()})",
                value=c.pk,
            )
            for c in challenges
            if current.lower() in c.name.lower()
        ][:25]