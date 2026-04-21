from django.contrib import admin
from .models import Challenge, ChallengeParticipant, ChallengeReward


class ChallengeRewardInline(admin.TabularInline):
    model = ChallengeReward
    extra = 1
    raw_id_fields = ["ball"]  # autocomplete_fields needs Ball admin search_fields


@admin.register(Challenge)
class ChallengeAdmin(admin.ModelAdmin):
    list_display = ("name", "start_time", "end_time", "goal_type", "active")
    list_filter = ("active", "goal_type")
    inlines = [ChallengeRewardInline]


@admin.register(ChallengeParticipant)
class ChallengeParticipantAdmin(admin.ModelAdmin):
    list_display = ("challenge", "player", "score")
    raw_id_fields = ("player",)  # same reason — Player admin search_fields not guaranteed