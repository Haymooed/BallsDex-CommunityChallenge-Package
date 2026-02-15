import logging
import datetime

from typing import TYPE_CHECKING
from discord.ext import commands
from discord import app_commands
import discord
from django.utils import timezone

from community_challenge.models import CommunityChallenge

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("ballsdex.packages.community_challenge")


class CommunityChallengeCog(commands.Cog):
    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot

    @app_commands.command(description="List active community challenges")
    async def challenges(self, interaction: discord.Interaction):
        now = timezone.now()
        active_challenges = CommunityChallenge.objects.filter(
            is_active=True, start_time__lte=now, end_time__gte=now
        )

        if not await active_challenges.exists():
            await interaction.response.send_message("There are no active community challenges at the moment.", ephemeral=True)
            return

        embed = discord.Embed(title="Community Challenges", color=discord.Color.blue())
        async for challenge in active_challenges:
            embed.add_field(
                name=challenge.title,
                value=f"{challenge.description}\nEnds: <t:{int(challenge.end_time.timestamp())}:R>",
                inline=False,
            )

        await interaction.response.send_message(embed=embed)
