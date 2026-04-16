from django.apps import AppConfig

class CommunityChallengesConfig(AppConfig):
    name = "community_challenge"
    dpy_package = "community_challenge.community_challenge"

    def ready(self):
        from . import patch
        patch.apply_patches()
