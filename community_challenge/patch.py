import logging

log = logging.getLogger("ballsdex.packages.community_challenges")

def apply_patches():
    """
    Called from the cog's __init__, NOT from AppConfig.ready().
    By the time the cog loads, BallsDex settings are fully initialised.
    """
    log.info("Applying Community Challenges monkey patches...")

    try:
        from ballsdex.packages.countryballs.cog import CountryBallsSpawner
        original_catch = CountryBallsSpawner.catch_ball

        async def patched_catch_ball(self, interaction, *args, **kwargs):
            result = await original_catch(self, interaction, *args, **kwargs)
            if interaction.client and interaction.user:
                interaction.client.dispatch("challenge_score_add", interaction.user.id, "balls", 1)
            return result

        CountryBallsSpawner.catch_ball = patched_catch_ball
        log.info("Monkey-patch applied to CountryBallsSpawner.catch_ball")
    except ImportError as e:
        log.warning(f"Could not monkey-patch catch module: {e}")
    except AttributeError as e:
        log.warning(f"catch_ball method not found on expected class: {e}")
