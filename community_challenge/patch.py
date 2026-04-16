import logging
log = logging.getLogger("ballsdex.packages.community_challenges")

def apply_patches():
    log.info("Applying Community Challenges monkey patches...")
    try:
        from ballsdex.packages.countryballs.countryball import BallSpawnView
        original_catch = BallSpawnView.catch_ball

        async def patched_catch_ball(self, user, *, player, guild):
            result = await original_catch(self, user, player=player, guild=guild)
            try:
                from ballsdex.core.bot import BallsDexBot
                import discord
                if hasattr(user, '_state') and user._state:
                    bot = user._state._get_client()
                    if bot:
                        bot.dispatch("challenge_score_add", user.id, "balls", 1)
            except Exception:
                pass
            return result

        BallSpawnView.catch_ball = patched_catch_ball
        log.info("Monkey-patch applied to BallSpawnView.catch_ball")
    except ImportError as e:
        log.warning(f"Could not monkey-patch catch module: {e}")
    except AttributeError as e:
        log.warning(f"catch_ball method not found on expected class: {e}")
