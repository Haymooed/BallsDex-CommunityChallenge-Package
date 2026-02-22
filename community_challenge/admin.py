from django.contrib import admin
from django.db.models import Sum

from .models import ChallengeProgress, ChallengeReward, ChallengeSettings, CommunityChallenge


@admin.register(ChallengeSettings)
class ChallengeSettingsAdmin(admin.ModelAdmin):
    list_display = ("enabled", "announcement_channel_id")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ChallengeProgressInline(admin.TabularInline):
    model = ChallengeProgress
    extra = 0
    readonly_fields = ("player", "amount", "last_updated")
    can_delete = False
    ordering = ("-amount",)

    def get_queryset(self, request):
        return super().get_queryset(request).order_by("-amount")[:25]


@admin.register(CommunityChallenge)
class CommunityChallengeAdmin(admin.ModelAdmin):
    list_display = (
        "name", "challenge_type", "target_amount",
        "current_progress", "reward_balls", "enabled", "completed", "created_at",
    )
    list_filter = ("challenge_type", "enabled", "completed")
    search_fields = ("name", "description")
    readonly_fields = ("created_at", "completed_at", "current_progress")
    fieldsets = (
        ("Identity", {"fields": ("name", "description", "challenge_type")}),
        ("Goal", {"fields": ("target_amount", "current_progress")}),
        ("Reward", {"fields": ("reward_balls",)}),
        ("Status", {"fields": ("enabled", "completed", "created_at", "completed_at")}),
    )
    inlines = (ChallengeProgressInline,)

    @admin.display(description="Current Progress")
    def current_progress(self, obj: CommunityChallenge) -> str:
        total = (
            ChallengeProgress.objects.filter(challenge=obj)
            .aggregate(total=Sum("amount"))["total"]
            or 0
        )
        pct = min(100, round(total / max(1, obj.target_amount) * 100, 1))
        return f"{total:,} / {obj.target_amount:,} ({pct}%)"


@admin.register(ChallengeProgress)
class ChallengeProgressAdmin(admin.ModelAdmin):
    list_display = ("challenge", "player", "amount", "last_updated")
    list_filter = ("challenge",)
    search_fields = ("player__discord_id",)
    readonly_fields = ("challenge", "player", "amount", "last_updated")
    ordering = ("-amount",)

    def has_add_permission(self, request):
        return False


@admin.register(ChallengeReward)
class ChallengeRewardAdmin(admin.ModelAdmin):
    list_display = ("challenge", "player", "balls_given", "issued_at")
    list_filter = ("challenge",)
    search_fields = ("player__discord_id",)
    readonly_fields = ("challenge", "player", "balls_given", "issued_at")

    def has_add_permission(self, request):
        return False