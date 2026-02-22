import logging
import textwrap
from typing import TYPE_CHECKING

from .cog import CommunityChallenges

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("ballsdex.packages.community_challenge")

LOGO = textwrap.dedent(r"""
    +---------------------------------------+
    |   BallsDex Community Challenge v1    |
    |        Admin-panel configured        |
    |          Licensed under MIT          |
    +---------------------------------------+
""").strip()


async def setup(bot: "BallsDexBot") -> None:
    print(LOGO)
    log.info("Loading Community Challenge package...")
    await bot.add_cog(CommunityChallenges(bot))
    log.info("Community Challenge package loaded successfully!")
