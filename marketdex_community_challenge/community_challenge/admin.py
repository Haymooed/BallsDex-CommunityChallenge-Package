from django.contrib import admin
from .models import CommunityChallenge


@admin.register(CommunityChallenge)
class CommunityChallengeAdmin(admin.ModelAdmin):
    list_display = ("title", "start_time", "end_time", "is_active", "created_at")
    list_filter = ("is_active", "start_time", "end_time")
    search_fields = ("title", "description")
