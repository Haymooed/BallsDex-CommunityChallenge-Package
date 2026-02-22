from __future__ import annotations

from django.db import models
from django.utils import timezone

from bd_models.models import Ball, Player, Special


class ChallengeType(models.TextChoices):
    # Event-based (tracked via on_message_edit — the bot edits the spawn message on catch)
    CATCH_ANY      = "catch_any",      "Catch any ball"
    CATCH_SPECIFIC = "catch_specific", "Catch a specific ball (set Ball filter below)"
    CATCH_SPECIAL  = "catch_special",  "Catch any special ball"
    CATCH_SPECIFIC_SPECIAL = "catch_specific_special", "Catch a specific special (set Special filter below)"
    GUESS_WRONG    = "guess_wrong",    "Wrong guesses submitted"
    TRADE          = "trade",          "Trades completed"
    # Snapshot-based (live DB count, recalculated on /challenge view)
    BALLS_OWNED    = "balls_owned",    "Community total balls owned (snapshot)"
    UNIQUE_BALLS   = "unique_balls",   "Community unique ball types owned (snapshot)"
    SPECIALS_OWNED = "specials_owned", "Community total specials owned (snapshot)"


EVENT_TYPES = {
    ChallengeType.CATCH_ANY,
    ChallengeType.CATCH_SPECIFIC,
    ChallengeType.CATCH_SPECIAL,
    ChallengeType.CATCH_SPECIFIC_SPECIAL,
    ChallengeType.GUESS_WRONG,
    ChallengeType.TRADE,
}

SNAPSHOT_TYPES = {
    ChallengeType.BALLS_OWNED,
    ChallengeType.UNIQUE_BALLS,
    ChallengeType.SPECIALS_OWNED,
}


class ChallengeSettings(models.Model):
    """Singleton — system-wide settings, managed from the admin panel."""

    singleton_id = models.PositiveSmallIntegerField(
        primary_key=True, default=1, editable=False
    )
    enabled = models.BooleanField(
        default=True,
        help_text="Master switch — disable to hide all challenges.",
    )
    announcement_channel_id = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="Discord channel ID for completion announcements. Leave blank to disable.",
    )

    class Meta:
        verbose_name = "Challenge settings"
        verbose_name_plural = "Challenge settings"

    def __str__(self) -> str:
        return "Challenge Settings"

    @classmethod
    async def load(cls) -> "ChallengeSettings":
        instance, _ = await cls.objects.aget_or_create(pk=1)
        return instance


class CommunityChallenge(models.Model):
    """A cooperative challenge configured entirely from the admin panel."""

    name = models.CharField(max_length=64, help_text="Display name shown to players.")
    description = models.CharField(max_length=256, blank=True)
    challenge_type = models.CharField(
        max_length=24,
        choices=ChallengeType.choices,
        default=ChallengeType.CATCH_ANY,
    )

    # ── Optional filters (only used for CATCH_SPECIFIC / CATCH_SPECIFIC_SPECIAL) ──
    ball_filter = models.ForeignKey(
        Ball,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text=(
            "Required for 'Catch a specific ball'. "
            "Leave blank to accept any ball for other catch types."
        ),
    )
    special_filter = models.ForeignKey(
        Special,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text=(
            "Required for 'Catch a specific special'. "
            "Leave blank to accept any special for 'Catch any special ball'."
        ),
    )

    target_amount = models.PositiveIntegerField(
        default=1000,
        help_text=(
            "Community-wide goal. "
            "For snapshot types this is the live DB total to reach."
        ),
    )
    reward_balls = models.PositiveSmallIntegerField(
        default=0,
        help_text="Balls gifted to each contributor on completion (0 = no reward).",
    )
    enabled = models.BooleanField(default=True, help_text="Toggle without deleting.")
    completed = models.BooleanField(
        default=False,
        help_text="Set automatically when target is hit. Reset manually to re-run.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Community Challenge"
        verbose_name_plural = "Community Challenges"

    def __str__(self) -> str:
        return self.name

    @property
    def is_snapshot(self) -> bool:
        return self.challenge_type in SNAPSHOT_TYPES


class ChallengeProgress(models.Model):
    """One row per (player, challenge) — incremented as events occur."""

    challenge = models.ForeignKey(
        CommunityChallenge,
        on_delete=models.CASCADE,
        related_name="progress_entries",
    )
    player = models.ForeignKey(
        Player,
        on_delete=models.CASCADE,
        related_name="challenge_progress",
    )
    amount = models.PositiveIntegerField(default=0)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (("challenge", "player"),)
        ordering = ("-amount",)
        indexes = (
            models.Index(fields=("challenge", "amount"), name="cc_challenge_amount_idx"),
        )
        verbose_name = "Challenge Progress"
        verbose_name_plural = "Challenge Progress Entries"

    def __str__(self) -> str:
        return f"Player {self.player_id} → challenge {self.challenge_id}: {self.amount}"


class ChallengeReward(models.Model):
    """Idempotency log — one row per (player, challenge). Prevents double-rewarding."""

    challenge = models.ForeignKey(
        CommunityChallenge,
        on_delete=models.CASCADE,
        related_name="rewards_issued",
    )
    player = models.ForeignKey(
        Player,
        on_delete=models.CASCADE,
        related_name="challenge_rewards",
    )
    balls_given = models.PositiveSmallIntegerField(default=0)
    issued_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = (("challenge", "player"),)
        ordering = ("-issued_at",)
        verbose_name = "Challenge Reward"
        verbose_name_plural = "Challenge Rewards"

    def __str__(self) -> str:
        return f"Player {self.player_id} ← {self.balls_given} balls ({self.challenge_id})"