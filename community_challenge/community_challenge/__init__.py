from typing import TYPE_CHECKING
from .cog import ChallengesCog
from .. import patch

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

async def setup(bot: "BallsDexBot"):
    patch.apply_patches()
    await bot.add_cog(ChallengesCog(bot))
