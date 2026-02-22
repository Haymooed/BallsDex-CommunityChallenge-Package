from __future__ import annotations

from django.db import models
from django.utils import timezone

from bd_models.models import Player


class ChallengeType(models.TextChoices):
    # Ball catching
    CATCH_ANY      = "catch_any",      "Catch any ball"
    CATCH_SPECIAL  = "catch_special",  "Catch a special ball"
    # Guessing
    GUESS_WRONG    = "guess_wrong",    "Guess wrong (wrong answer attempts)"
    GUESS_CORRECT  = "guess_correct",  "Guess correct (first-try catches)"
    # Trading
    TRADE          = "trade",          "Complete a trade"
    # Collection milestones (snapshot-based, checked on /challenge view)
    BALLS_OWNED    = "balls_owned",    "Community total balls owned"
    UNIQUE_BALLS   = "unique_balls",   "Community unique ball types owned"
    SPECIALS_OWNED = "specials_owned", "Community total specials owned"


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
    """A single cooperative challenge, managed entirely from the admin panel."""

    name = models.CharField(max_length=64, help_text="Display name shown to players.")
    description = models.CharField(max_length=256, blank=True)
    challenge_type = models.CharField(
        max_length=20,
        choices=ChallengeType.choices,
        default=ChallengeType.CATCH_ANY,
        help_text=(
            "What players must do to contribute. "
            "Event-based types (catch, guess, trade) are tracked in real-time via message events. "
            "Snapshot types (balls_owned, unique_balls, specials_owned) are recalculated "
            "from the database whenever a player runs /challenge view."
        ),
    )
    target_amount = models.PositiveIntegerField(
        default=1000,
        help_text="Community-wide goal. For snapshot types this is the total DB count to reach.",
    )
    reward_balls = models.PositiveSmallIntegerField(
        default=0,
        help_text="Number of balls to gift each contributor on completion (0 = no reward).",
    )
    enabled = models.BooleanField(default=True, help_text="Toggle without deleting.")
    completed = models.BooleanField(
        default=False,
        help_text="Set automatically when progress hits target. Reset to re-open.",
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
        """Snapshot challenges pull their total from the live DB, not from ChallengeProgress."""
        return self.challenge_type in (
            ChallengeType.BALLS_OWNED,
            ChallengeType.UNIQUE_BALLS,
            ChallengeType.SPECIALS_OWNED,
        )


class ChallengeProgress(models.Model):
    """
    One row per (player, challenge) for event-based challenges.
    Snapshot challenges do not use this table for their total
    (but a row is still created to track individual contribution for leaderboards).
    """

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