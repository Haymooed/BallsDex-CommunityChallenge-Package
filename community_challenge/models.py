from django.db import models
from bd_models.models import Player, Ball

class Challenge(models.Model):
    name = models.CharField(max_length=64)
    description = models.TextField()
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    
    GOAL_CHOICES =[
        ('balls', 'Balls Caught'),
        ('currency', 'Currency Earned'),
    ]
    goal_type = models.CharField(max_length=16, choices=GOAL_CHOICES, default='balls')
    active = models.BooleanField(default=True)
    
    # JSON mapped ranks to prizes. Example: {"1": {"currency": 5000, "balls": [14, 21]}, "2": {"currency": 1000}}
    reward_config = models.JSONField(default=dict, help_text="Mapping of Rank to rewards in JSON format.")

    def __str__(self):
        return self.name

class ChallengeParticipant(models.Model):
    challenge = models.ForeignKey(Challenge, on_delete=models.CASCADE, related_name='participants')
    player = models.ForeignKey(Player, on_delete=models.CASCADE)
    score = models.IntegerField(default=0)

    class Meta:
        constraints =[
            models.UniqueConstraint(fields=['challenge', 'player'], name='unique_challenge_player')
        ]