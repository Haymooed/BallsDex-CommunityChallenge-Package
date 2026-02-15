from django.db import models


class CommunityChallenge(models.Model):
    CHALLENGE_TYPES = (
        ("balls_caught", "Global Balls Caught"),
        ("specials_caught", "Global Specials Caught"),
        ("specific_ball", "Specific Ball Caught"),
        ("specific_special", "Specific Special Caught"),
        ("manual", "Manual Progress"),
    )

    title = models.CharField(max_length=255)
    description = models.TextField()
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Progress fields
    type = models.CharField(max_length=20, choices=CHALLENGE_TYPES, default="manual")
    target_amount = models.PositiveIntegerField(default=100, help_text="Goal amount for the challenge")
    manual_progress = models.PositiveIntegerField(default=0, help_text="Current progress (only for Manual type)")
    
    # Specific targets
    ball = models.ForeignKey("bd_models.Ball", on_delete=models.SET_NULL, null=True, blank=True, help_text="Required for 'Specific Ball Caught'")
    special = models.ForeignKey("bd_models.Special", on_delete=models.SET_NULL, null=True, blank=True, help_text="Required for 'Specific Special Caught'")

    def __str__(self):
        return self.title
