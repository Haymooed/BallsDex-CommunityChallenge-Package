from django.contrib import admin
from .models import CommunityChallenge


@admin.register(CommunityChallenge)
class CommunityChallengeAdmin(admin.ModelAdmin):
    list_display = ("title", "type", "start_time", "end_time", "is_active", "created_at")
    list_filter = ("is_active", "type", "start_time", "end_time")
    search_fields = ("title", "description")
    
    fieldsets = (
        (None, {
            "fields": ("title", "description", "is_active")
        }),
        ("Timing", {
            "fields": ("start_time", "end_time")
        }),
        ("Progress Configuration", {
            "fields": ("type", "target_amount", "manual_progress"),
            "description": "Configure how the challenge progress is tracked. For 'Manual', update 'Manual Progress' field. For 'Balls Caught', it calculates automatically."
        }),
    )
