import logging
import datetime

from typing import TYPE_CHECKING
from discord.ext import commands
from discord import app_commands
import discord
from django.utils import timezone

from community_challenge.models import CommunityChallenge
from bd_models.models import BallInstance

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

        if not await active_challenges.aexists():
            await interaction.response.send_message("There are no active community challenges at the moment.", ephemeral=True)
            return

        embed = discord.Embed(title="Community Challenges", color=discord.Color.blue())
        async for challenge in active_challenges:
            # Calculate progress
            if challenge.type == "balls_caught":
                # Count balls caught since start of challenge
                current = await BallInstance.objects.filter(
                    catch_date__gte=challenge.start_time,
                    catch_date__lte=now 
                ).acount()
            elif challenge.type == "specials_caught":
                # Count special balls caught
                current = await BallInstance.objects.filter(
                    catch_date__gte=challenge.start_time,
                    catch_date__lte=now,
                    special__isnull=False
                ).acount()
            elif challenge.type == "specific_ball":
                current = 0
                if challenge.ball_id:
                    current = await BallInstance.objects.filter(
                        catch_date__gte=challenge.start_time,
                        catch_date__lte=now,
                        ball_id=challenge.ball_id
                    ).acount()
            elif challenge.type == "specific_special":
                current = 0
                if challenge.special_id:
                    current = await BallInstance.objects.filter(
                        catch_date__gte=challenge.start_time,
                        catch_date__lte=now,
                        special_id=challenge.special_id
                    ).acount()
            else:
                # Manual progress
                current = challenge.manual_progress

            target = challenge.target_amount
            percentage = min(current / target, 1.0) if target > 0 else 0
            
            # Generate progress bar
            filled_length = int(10 * percentage)
            bar = "█" * filled_length + "░" * (10 - filled_length)
            
            progress_text = f"`[{bar}]` {int(percentage * 100)}% ({current}/{target})"

            embed.add_field(
                name=challenge.title,
                value=f"{challenge.description}\n\n**Progress**:\n{progress_text}\n\nEnds: <t:{int(challenge.end_time.timestamp())}:R>",
                inline=False,
            )

        await interaction.response.send_message(embed=embed)
