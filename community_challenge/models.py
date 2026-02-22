from __future__ import annotations

from datetime import timedelta

from django.db import models
from django.utils import timezone

from bd_models.models import Player


# ---------------------------------------------------------------------------
# Challenge type choices — matches real BallsDex player actions
# ---------------------------------------------------------------------------

class ChallengeType(models.TextChoices):
    CATCH  = "catch",  "Catch"
    TRADE  = "trade",  "Trade"


# ---------------------------------------------------------------------------
# Global settings (singleton)
# ---------------------------------------------------------------------------

class ChallengeSettings(models.Model):
    """
    Singleton — system-wide settings, managed entirely from the admin panel.
    """

    singleton_id = models.PositiveSmallIntegerField(
        primary_key=True, default=1, editable=False
    )
    enabled = models.BooleanField(
        default=True,
        help_text="Master switch — disable to hide all challenges from players.",
    )
    announcement_channel_id = models.BigIntegerField(
        null=True,
        blank=True,
        help_text=(
            "Discord channel ID where completion announcements are sent. "
            "Leave blank to disable announcements."
        ),
    )

    class Meta:
        verbose_name = "Challenge settings"
        verbose_name_plural = "Challenge settings"

    def __str__(self) -> str:
        return "Challenge Settings"

    @classmethod
    async def load(cls) -> "ChallengeSettings":
        """Return the singleton, creating it with defaults if missing."""
        instance, _ = await cls.objects.aget_or_create(pk=1)
        return instance


# ---------------------------------------------------------------------------
# Individual challenge definitions
# ---------------------------------------------------------------------------

class CommunityChallenge(models.Model):
    """
    A single cooperative challenge, created and managed from the admin panel.
    """

    name = models.CharField(
        max_length=64,
        help_text="Display name shown to players.",
    )
    description = models.CharField(
        max_length=256,
        blank=True,
        help_text="Short description shown in the /challenge embed.",
    )
    challenge_type = models.CharField(
        max_length=16,
        choices=ChallengeType.choices,
        default=ChallengeType.CATCH,
        help_text="The action players must perform to contribute.",
    )
    target_amount = models.PositiveIntegerField(
        default=1000,
        help_text="Total community-wide contributions needed to complete.",
    )
    reward_balls = models.PositiveSmallIntegerField(
        default=0,
        help_text="Number of balls to gift each contributor on completion (0 = none).",
    )
    enabled = models.BooleanField(
        default=True,
        help_text="Toggle visibility without deleting.",
    )
    completed = models.BooleanField(
        default=False,
        help_text=(
            "Set automatically when progress reaches target_amount. "
            "Reset to False to re-open the challenge."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Community Challenge"
        verbose_name_plural = "Community Challenges"

    def __str__(self) -> str:
        return self.name


# ---------------------------------------------------------------------------
# Per-player progress entries
# ---------------------------------------------------------------------------

class ChallengeProgress(models.Model):
    """
    One row per (player, challenge) — amount is incremented as players act.
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
    amount = models.PositiveIntegerField(
        default=0,
        help_text="Cumulative contribution by this player to this challenge.",
    )
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
        return f"Player {self.player_id} → {self.challenge_id}: {self.amount}"


# ---------------------------------------------------------------------------
# Reward log — idempotency guard + audit trail
# ---------------------------------------------------------------------------

class ChallengeReward(models.Model):
    """
    Records that a reward was issued. Prevents double-rewarding.
    """

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