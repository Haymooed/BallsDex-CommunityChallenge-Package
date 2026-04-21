from django.db import models
from bd_models.models import Player, Ball


class Challenge(models.Model):
    name = models.CharField(max_length=64)
    description = models.TextField()
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()

    GOAL_CHOICES = [
        ("balls", "Balls Caught"),
    ]
    goal_type = models.CharField(max_length=16, choices=GOAL_CHOICES, default="balls")
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class ChallengeReward(models.Model):
    challenge = models.ForeignKey(Challenge, on_delete=models.CASCADE, related_name="rewards")
    rank = models.PositiveIntegerField(help_text="The rank this reward is given to (e.g., 1 for 1st place).")
    ball = models.ForeignKey(Ball, on_delete=models.CASCADE, help_text="The specific ball to reward.")
    amount = models.PositiveIntegerField(default=1, help_text="How many of this ball to give.")

    def __str__(self):
        return f"Rank {self.rank} reward for {self.challenge}"

    class Meta:
        ordering = ["rank"]
        verbose_name = "Reward"
        verbose_name_plural = "Rewards"


class ChallengeParticipant(models.Model):
    challenge = models.ForeignKey(Challenge, on_delete=models.CASCADE, related_name="participants")
    player = models.ForeignKey(Player, on_delete=models.CASCADE)
    score = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.player} in {self.challenge}"

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["challenge", "player"], name="unique_challenge_player")
        ]