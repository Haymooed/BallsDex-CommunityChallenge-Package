from django.contrib import admin
from .models import Challenge, ChallengeParticipant

@admin.register(Challenge)
class ChallengeAdmin(admin.ModelAdmin):
    list_display = ('name', 'start_time', 'end_time', 'goal_type', 'active')
    list_filter = ('active', 'goal_type')

@admin.register(ChallengeParticipant)
class ChallengeParticipantAdmin(admin.ModelAdmin):
    list_display = ('challenge', 'player', 'score')
    autocomplete_fields = ("player",)