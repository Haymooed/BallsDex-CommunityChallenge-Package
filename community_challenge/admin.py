from django.contrib import admin
from django.db.models import Sum

from .models import (
    ChallengeProgress,
    ChallengeReward,
    ChallengeSettings,
    CommunityChallenge,
)


# ---------------------------------------------------------------------------
# Settings (singleton)
# ---------------------------------------------------------------------------

@admin.register(ChallengeSettings)
class ChallengeSettingsAdmin(admin.ModelAdmin):
    list_display = ("enabled", "announcement_channel_id")

    def has_add_permission(self, request):
        # Singleton — block creating a second row.
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# ---------------------------------------------------------------------------
# Challenges
# ---------------------------------------------------------------------------

class ChallengeProgressInline(admin.TabularInline):
    model = ChallengeProgress
    extra = 0
    readonly_fields = ("player", "amount", "last_updated")
    can_delete = False
    ordering = ("-amount",)
    show_change_link = False

    def get_queryset(self, request):
        # Show only top 25 contributors inline to keep the page fast.
        return super().get_queryset(request).order_by("-amount")[:25]


@admin.register(CommunityChallenge)
class CommunityChallengeAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "challenge_type",
        "target_amount",
        "current_progress",
        "enabled",
        "completed",
        "created_at",
        "completed_at",
    )
    list_filter = ("challenge_type", "enabled", "completed")
    search_fields = ("name", "description", "reward_item")
    readonly_fields = ("created_at", "completed_at", "current_progress")
    fieldsets = (
        (
            "Identity",
            {
                "fields": ("name", "description", "challenge_type"),
            },
        ),
        (
            "Goal",
            {
                "fields": ("target_amount", "current_progress"),
            },
        ),
        (
            "Reward",
            {
                "fields": ("reward_item", "reward_quantity"),
            },
        ),
        (
            "Status",
            {
                "fields": ("enabled", "completed", "created_at", "completed_at"),
            },
        ),
    )
    inlines = (ChallengeProgressInline,)

    @admin.display(description="Current Progress")
    def current_progress(self, obj: CommunityChallenge) -> str:
        total = (
            ChallengeProgress.objects.filter(challenge=obj).aggregate(
                total=Sum("amount")
            )["total"]
            or 0
        )
        pct = min(100, round(total / max(1, obj.target_amount) * 100, 1))
        return f"{total:,} / {obj.target_amount:,} ({pct}%)"


# ---------------------------------------------------------------------------
# Progress entries
# ---------------------------------------------------------------------------

@admin.register(ChallengeProgress)
class ChallengeProgressAdmin(admin.ModelAdmin):
    list_display = ("challenge", "player", "amount", "last_updated")
    list_filter = ("challenge",)
    search_fields = ("player__discord_id",)
    readonly_fields = ("challenge", "player", "amount", "last_updated")
    ordering = ("-amount",)

    def has_add_permission(self, request):
        return False


# ---------------------------------------------------------------------------
# Reward log
# ---------------------------------------------------------------------------

@admin.register(ChallengeReward)
class ChallengeRewardAdmin(admin.ModelAdmin):
    list_display = ("challenge", "player", "reward_item", "reward_quantity", "issued_at")
    list_filter = ("challenge", "reward_item")
    search_fields = ("player__discord_id",)
    readonly_fields = ("challenge", "player", "reward_item", "reward_quantity", "issued_at")

    def has_add_permission(self, request):
        return False
