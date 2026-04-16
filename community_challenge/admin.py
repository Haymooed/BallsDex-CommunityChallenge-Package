from django.contrib import admin
from .models import Challenge, ChallengeParticipant, ChallengeReward

class ChallengeRewardInline(admin.TabularInline):
    model = ChallengeReward
    extra = 1
    autocomplete_fields = ["ball"] # Gives you a nice search bar to find the ball

@admin.register(Challenge)
class ChallengeAdmin(admin.ModelAdmin):
    list_display = ('name', 'start_time', 'end_time', 'goal_type', 'active')
    list_filter = ('active', 'goal_type')
    inlines = [ChallengeRewardInline] # Puts the rewards UI inside the challenge page

@admin.register(ChallengeParticipant)
class ChallengeParticipantAdmin(admin.ModelAdmin):
    list_display = ('challenge', 'player', 'score')
    autocomplete_fields = ("player",)
