from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import discord
from asgiref.sync import sync_to_async
from discord import app_commands
from discord.ext import commands
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.db.models.signals import post_save
from django.utils import timezone

from bd_models.models import BallInstance, Player

from community_challenge.models import (
    ChallengeProgress,
    ChallengeReward,
    ChallengeSettings,
    CommunityChallenge,
    ChallengeType,
    SNAPSHOT_TYPES,
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


TYPE_EMOJI: dict[str, str] = {
    ChallengeType.CATCH_ANY:              "🎣",
    ChallengeType.CATCH_SPECIFIC:         "🎯",
    ChallengeType.CATCH_SPECIAL:          "✨",
    ChallengeType.CATCH_SPECIFIC_SPECIAL: "🌟",
    ChallengeType.GUESS_WRONG:            "❌",
    ChallengeType.TRADE:                  "🔄",
    ChallengeType.BALLS_OWNED:            "📦",
    ChallengeType.UNIQUE_BALLS:           "🗂️",
    ChallengeType.SPECIALS_OWNED:         "💫",
}

TYPE_LABEL: dict[str, str] = {
    ChallengeType.CATCH_ANY:              "balls caught",
    ChallengeType.CATCH_SPECIFIC:         "specific balls caught",
    ChallengeType.CATCH_SPECIAL:          "specials caught",
    ChallengeType.CATCH_SPECIFIC_SPECIAL: "specific specials caught",
    ChallengeType.GUESS_WRONG:            "wrong guesses",
    ChallengeType.TRADE:                  "trades completed",
    ChallengeType.BALLS_OWNED:            "balls owned",
    ChallengeType.UNIQUE_BALLS:           "unique ball types owned",
    ChallengeType.SPECIALS_OWNED:         "specials owned",
}


# ---------------------------------------------------------------------------
# Module-level signal receiver
#
# CRITICAL: This must be a plain module-level function, NOT a bound method.
#
# Django signals store receivers as weak references by default.
# If you pass `self._some_method`, that bound method object has no other
# references, so Python's garbage collector destroys it almost immediately.
# The signal fires but the receiver is already gone — nothing happens.
#
# Using a module-level function AND passing weak=False to post_save.connect()
# ensures the receiver is never collected.
# ---------------------------------------------------------------------------

_cog_ref: "CommunityChallenges | None" = None


def _ball_instance_post_save(
    sender,
    instance: BallInstance,
    created: bool,
    **kwargs,
) -> None:
    """
    Fires on every BallInstance save. We only care about newly-created rows.
    Bridges the synchronous Django signal into the async bot event loop.
    """
    if not created:
        return
    cog = _cog_ref
    if cog is None:
        return
    asyncio.run_coroutine_threadsafe(
        cog._handle_new_ball(instance),
        cog.bot.loop,
    )


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
        global _cog_ref
        _cog_ref = self
        # weak=False is mandatory — without it Django drops the receiver immediately
        post_save.connect(_ball_instance_post_save, sender=BallInstance, weak=False)
        log.info(
            "CommunityChallenges: post_save connected on BallInstance (weak=False)."
        )
        await self._refresh_cache()

    async def cog_unload(self) -> None:
        global _cog_ref
        _cog_ref = None
        post_save.disconnect(_ball_instance_post_save, sender=BallInstance)
        log.info("CommunityChallenges: post_save disconnected from BallInstance.")

    # ------------------------------------------------------------------
    # Core handler
    # ------------------------------------------------------------------

    async def _handle_new_ball(self, instance: BallInstance) -> None:
        """
        Called for every new BallInstance row.
        instance.ball_id    → Ball PK (int)
        instance.player_id  → Player PK (int)
        instance.special_id → Special PK (int) or None
        """
        active = await self._ensure_cache()
        if not active:
            return

        is_special = instance.special_id is not None
        log.debug(
            "CommunityChallenges: new BallInstance pk=%s ball_id=%s special_id=%s player_id=%s",
            instance.pk, instance.ball_id, instance.special_id, instance.player_id,
        )

        matching: list[CommunityChallenge] = []
        for challenge in active:
            ct = challenge.challenge_type

            if ct == ChallengeType.CATCH_ANY:
                matching.append(challenge)

            elif ct == ChallengeType.CATCH_SPECIFIC:
                if (
                    challenge.ball_filter_id is not None
                    and challenge.ball_filter_id == instance.ball_id
                ):
                    matching.append(challenge)

            elif ct == ChallengeType.CATCH_SPECIAL:
                if is_special:
                    matching.append(challenge)

            elif ct == ChallengeType.CATCH_SPECIFIC_SPECIAL:
                if is_special:
                    if challenge.special_filter_id is None:
                        matching.append(challenge)
                    elif challenge.special_filter_id == instance.special_id:
                        matching.append(challenge)

        if not matching:
            return

        try:
            player = await Player.objects.aget(pk=instance.player_id)
        except Player.DoesNotExist:
            log.warning(
                "CommunityChallenges: Player pk=%s not found for BallInstance pk=%s",
                instance.player_id, instance.pk,
            )
            return

        for challenge in matching:
            total = await self._add_progress(challenge, player)
            log.info(
                "CommunityChallenges: '%s' → %d / %d",
                challenge.name, total, challenge.target_amount,
            )
            await self.check_and_complete(challenge, total)

    # ------------------------------------------------------------------
    # Progress
    # ------------------------------------------------------------------

    async def _add_progress(
        self,
        challenge: CommunityChallenge,
        player: Player,
        amount: int = 1,
    ) -> int:
        def _sync() -> int:
            with transaction.atomic():
                entry, _ = ChallengeProgress.objects.select_for_update().get_or_create(
                    challenge=challenge,
                    player=player,
                    defaults={"amount": 0},
                )
                entry.amount += amount
                entry.save(update_fields=["amount", "last_updated"])
            return (
                ChallengeProgress.objects.filter(challenge=challenge)
                .aggregate(total=Sum("amount"))["total"]
                or 0
            )
        return await sync_to_async(_sync)()

    # ------------------------------------------------------------------
    # Snapshot challenges
    # ------------------------------------------------------------------

    @staticmethod
    async def _challenge_total(challenge: CommunityChallenge) -> int:
        ct = challenge.challenge_type
        if ct == ChallengeType.BALLS_OWNED:
            return await sync_to_async(BallInstance.objects.count)()
        if ct == ChallengeType.UNIQUE_BALLS:
            qs = BallInstance.objects.values("ball_id").distinct()
            return await sync_to_async(qs.count)()
        if ct == ChallengeType.SPECIALS_OWNED:
            qs = BallInstance.objects.filter(special__isnull=False)
            return await sync_to_async(qs.count)()
        def _sync() -> int:
            r = ChallengeProgress.objects.filter(challenge=challenge).aggregate(
                total=Sum("amount")
            )
            return r["total"] or 0
        return await sync_to_async(_sync)()

    async def check_snapshot_challenges(self) -> None:
        for challenge in await self._ensure_cache():
            if challenge.challenge_type in SNAPSHOT_TYPES:
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
            refreshed = await sync_to_async(
                lambda: CommunityChallenge.objects.get(pk=challenge.pk)
            )()
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

        def _mark():
            challenge.completed = True
            challenge.completed_at = timezone.now()
            challenge.save(update_fields=["completed", "completed_at"])
        await sync_to_async(_mark)()

        rewarded = 0
        if challenge.reward_balls > 0:
            entries = await sync_to_async(
                lambda: list(
                    ChallengeProgress.objects.filter(
                        challenge=challenge, amount__gt=0
                    ).select_related("player")
                )
            )()
            for entry in entries:
                if await self._issue_reward(challenge, entry.player):
                    rewarded += 1

        log.info(
            "Challenge '%s' complete — rewarded %d player(s) with %d ball(s) each.",
            challenge.name, rewarded, challenge.reward_balls,
        )
        await self._announce(challenge, rewarded)

    async def _issue_reward(self, challenge: CommunityChallenge, player: Player) -> bool:
        def _sync():
            try:
                ChallengeReward.objects.create(
                    challenge=challenge,
                    player=player,
                    balls_given=challenge.reward_balls,
                )
                return True
            except IntegrityError:
                return False
        return await sync_to_async(_sync)()

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
        embed.add_field(name="🏆 Goal", value=f"{challenge.target_amount:,} {label}", inline=True)
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
    # Cache
    # ------------------------------------------------------------------

    async def _refresh_cache(self) -> None:
        self._cache = await sync_to_async(
            lambda: list(
                CommunityChallenge.objects.filter(enabled=True, completed=False)
                .select_related("ball_filter", "special_filter")
            )
        )()
        self._cache_dirty = False
        log.debug(
            "CommunityChallenges: cache refreshed — %d active challenge(s).",
            len(self._cache),
        )

    def _invalidate_cache(self) -> None:
        self._cache_dirty = True

    async def _ensure_cache(self) -> list[CommunityChallenge]:
        if self._cache_dirty:
            await self._refresh_cache()
        return self._cache

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

        challenges = await sync_to_async(
            lambda: list(
                CommunityChallenge.objects.filter(enabled=True)
                .select_related("ball_filter", "special_filter")
            )
        )()

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
            status = (
                "✅ **Completed!**"
                if challenge.completed
                else _progress_bar(total, challenge.target_amount)
            )
            filters: list[str] = []
            if challenge.ball_filter:
                filters.append(f"Ball: **{challenge.ball_filter.country}**")
            if challenge.special_filter:
                filters.append(f"Special: **{challenge.special_filter.name}**")
            filter_line = ("\n" + " • ".join(filters)) if filters else ""
            value = (
                f"{challenge.description}{filter_line}\n"
                f"**Type:** {emoji} {challenge.get_challenge_type_display()}\n"
                f"**Progress:** {total:,} / {challenge.target_amount:,} {label}\n"
                f"{status}"
            )
            if challenge.reward_balls:
                value += f"\n**Reward:** {challenge.reward_balls} ball(s) per contributor"
            embed.add_field(name=f"{emoji} {challenge.name}", value=value, inline=False)

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

        def _get():
            try:
                return CommunityChallenge.objects.select_related(
                    "ball_filter", "special_filter"
                ).get(pk=challenge_id, enabled=True)
            except CommunityChallenge.DoesNotExist:
                return None

        challenge = await sync_to_async(_get)()
        if challenge is None:
            await interaction.response.send_message("Challenge not found.", ephemeral=True)
            return

        await interaction.response.defer()
        total = await self._challenge_total(challenge)
        top = await sync_to_async(
            lambda: list(
                ChallengeProgress.objects.filter(challenge=challenge)
                .select_related("player")
                .order_by("-amount")[:10]
            )
        )()

        emoji = TYPE_EMOJI.get(challenge.challenge_type, "🏆")
        label = TYPE_LABEL.get(challenge.challenge_type, "actions")
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

        if challenge.challenge_type in SNAPSHOT_TYPES:
            embed.add_field(
                name="ℹ️ Snapshot Challenge",
                value="This challenge measures a live database total, not individual events.",
                inline=False,
            )

        if not top:
            embed.add_field(
                name="No contributions yet",
                value="Start catching to appear here!",
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
        challenges = await sync_to_async(
            lambda: list(CommunityChallenge.objects.filter(enabled=True))
        )()
        return [
            app_commands.Choice(
                name=f"{'✅ ' if c.completed else ''}{c.name} ({c.get_challenge_type_display()})",
                value=c.pk,
            )
            for c in challenges
            if current.lower() in c.name.lower()
        ][:25]