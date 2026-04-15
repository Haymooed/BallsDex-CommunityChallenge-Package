from typing import TYPE_CHECKING
import discord
from discord import app_commands
from discord.ext import commands
from django.utils import timezone
import random

from bd_models.models import Player, Ball, BallInstance
from ..models import Challenge, ChallengeParticipant

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

class ChallengesCog(commands.GroupCog, group_name="challenges"):
    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot

    @commands.Cog.listener()
    async def on_challenge_score_add(self, discord_id: int, goal_type: str, amount: int = 1):
        """Listens for the monkey-patched event and increments scores"""
        now = timezone.now()
        
        # Async generator for active challenges of this specific type
        active_challenges = Challenge.objects.filter(
            active=True,
            start_time__lte=now,
            end_time__gte=now,
            goal_type=goal_type
        )
        
        if not await active_challenges.aexists():
            return
            
        try:
            player = await Player.objects.aget(discord_id=discord_id)
        except Player.DoesNotExist:
            return

        async for challenge in active_challenges:
            participant, _ = await ChallengeParticipant.objects.aget_or_create(
                challenge=challenge,
                player=player,
                defaults={"score": 0}
            )
            participant.score += amount
            await participant.asave()

    @app_commands.command(name="leaderboard")
    async def leaderboard(self, interaction: discord.Interaction["BallsDexBot"]):
        """Show the current community challenge leaderboard."""
        now = timezone.now()
        challenge = await Challenge.objects.filter(active=True, start_time__lte=now, end_time__gte=now).afirst()
        
        if not challenge:
            return await interaction.response.send_message("There is no active challenge right now.", ephemeral=True)
            
        participants = ChallengeParticipant.objects.filter(challenge=challenge).order_by('-score')[:10]
        embed = discord.Embed(title=f"🏆 Challenge: {challenge.name}", description=challenge.description, color=discord.Color.gold())
        
        text, rank = "", 1
        async for part in participants:
            await part.player.arefresh_from_db()
            text += f"**#{rank}** <@{part.player.discord_id}> - {part.score} pts\n"
            rank += 1
            
        embed.add_field(name="Top 10 Leaderboard", value=text or "No participants yet. Go score some points!")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="distribute")
    @app_commands.default_permissions(administrator=True)
    async def distribute_rewards(self, interaction: discord.Interaction["BallsDexBot"], challenge_name: str):
        """End a challenge and automatically distribute rewards to top finishers."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            challenge = await Challenge.objects.aget(name=challenge_name)
        except Challenge.DoesNotExist:
            return await interaction.followup.send("Challenge not found.")
            
        # Lock the challenge
        if challenge.active:
            challenge.active = False
            await challenge.asave()
            
        participants = ChallengeParticipant.objects.filter(challenge=challenge, score__gt=0).order_by('-score')
        rewards_config = challenge.reward_config
        distributed_count = 0
        
        rank = 1
        async for part in participants:
            reward = rewards_config.get(str(rank))
            if reward:
                player = part.player
                
                # 1. Distribute Currency
                if "currency" in reward:
                    # Note: Assumes Player model has a 'currency' field or equivalent logic 
                    # specific to your merchant system
                    player.currency += reward["currency"]
                    await player.asave()
                    
                # 2. Distribute Balls from Prize Pool
                if "balls" in reward:
                    for ball_id in reward["balls"]:
                        try:
                            ball_obj = await Ball.objects.aget(id=ball_id)
                            await BallInstance.objects.acreate(
                                ball=ball_obj,
                                player=player,
                                catch_date=timezone.now(),
                                attack_bonus=random.randint(-20, 20),
                                health_bonus=random.randint(-20, 20)
                            )
                        except Ball.DoesNotExist:
                            continue
                distributed_count += 1
            rank += 1
            
        await interaction.followup.send(f"✅ Challenge closed. Rewards automatically distributed to {distributed_count} top players.")