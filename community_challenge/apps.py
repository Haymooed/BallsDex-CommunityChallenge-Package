from django.apps import AppConfig

class CommunityChallengesConfig(AppConfig):
    name = "community_challenge"
    dpy_package = "community_challenge.community_challenge"
    # No ready() — patching happens in the cog instead
from django.apps import AppConfig
