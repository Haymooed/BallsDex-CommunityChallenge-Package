from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from django.db import models
from django.utils import timezone

from bd_models.models import Ball, BallInstance, Player, Special


# ---------------------------------------------------------------------------
# Challenge type choices
# ---------------------------------------------------------------------------

class ChallengeType(models.TextChoices):
    COLLECT = "collect", "Collect"
    TRADE   = "trade",   "Trade"
    CRAFT   = "craft",   "Craft"
    CATCH   = "catch",   "Catch"
    DONATE  = "donate",  "Donate"


# ---------------------------------------------------------------------------
# Global settings (singleton)
# ---------------------------------------------------------------------------

class ChallengeSettings(models.Model):
    """
    Singleton that holds system-wide settings for Community Challenges.
    Managed entirely from the Django admin panel.
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
            "Discord channel ID where challenge completion announcements are sent. "
            "Leave blank to disable announcements."
        ),
    )

    class Meta:
        verbose_name = "Challenge settings"

    def __str__(self) -> str:  # pragma: no cover
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

    name = models.CharField(max_length=64, help_text="Display name shown to players.")
    description = models.CharField(
        max_length=256,
        blank=True,
        help_text="Short description shown in the /challenge embed.",
    )
    challenge_type = models.CharField(
        max_length=16,
        choices=ChallengeType.choices,
        default=ChallengeType.CATCH,
        help_text="The action type players must perform to contribute.",
    )
    target_amount = models.PositiveIntegerField(
        default=1000,
        help_text="Total community-wide contributions needed to complete this challenge.",
    )
    reward_item = models.CharField(
        max_length=64,
        blank=True,
        help_text=(
            "String key identifying the reward (e.g. 'winter_crate'). "
            "Used by the reward distribution logic."
        ),
    )
    reward_quantity = models.PositiveSmallIntegerField(
        default=1,
        help_text="How many reward items each contributor receives upon completion.",
    )
    enabled = models.BooleanField(
        default=True,
        help_text="Toggle visibility without deleting the challenge.",
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

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    async def total_progress(self) -> int:
        """Sum of all contribution amounts for this challenge."""
        result = await ChallengeProgress.objects.filter(challenge=self).aaggregate(
            total=models.Sum("amount")
        )
        return result["total"] or 0

    async def is_complete(self) -> bool:
        if self.completed:
            return True
        return await self.total_progress() >= self.target_amount


# ---------------------------------------------------------------------------
# Per-player progress entries
# ---------------------------------------------------------------------------

class ChallengeProgress(models.Model):
    """
    Tracks how much a single player has contributed to a specific challenge.
    One row per (player, challenge) pair; amount is incremented over time.
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
        return f"{self.player_id} → {self.challenge.name}: {self.amount}"


# ---------------------------------------------------------------------------
# Reward distribution log
# ---------------------------------------------------------------------------

class ChallengeReward(models.Model):
    """
    Records that a reward was issued to a player for completing a challenge.
    Prevents double-rewarding and provides an audit trail.
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
    reward_item = models.CharField(max_length=64)
    reward_quantity = models.PositiveSmallIntegerField()
    issued_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = (("challenge", "player"),)
        ordering = ("-issued_at",)
        verbose_name = "Challenge Reward"
        verbose_name_plural = "Challenge Rewards"

    def __str__(self) -> str:
        return (
            f"{self.player_id} ← {self.reward_quantity}× {self.reward_item} "
            f"({self.challenge.name})"
        )
