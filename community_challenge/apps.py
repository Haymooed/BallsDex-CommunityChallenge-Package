from django.apps import AppConfig

class CommunityChallengesConfig(AppConfig):
    name = "community_challenges"
    dpy_package = "community_challenges.ext"

    def ready(self):
        from . import patch
        patch.apply_patches()