from django.apps import AppConfig


class CommunityChallengeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "community_challenge"
    verbose_name = "Community Challenges"
    dpy_package = "community_challenge.community_challenge"
