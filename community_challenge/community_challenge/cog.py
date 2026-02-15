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
            else:
                # Manual progress
                current = challenge.manual_progress

            target = challenge.target_amount
            percentage = min(current / target, 1.0) if target > 0 else 0
            
            # Generate progress bar
            filled_length = int(10 * percentage)
            bar = "█" * filled_length + "░" * (10 - filled_length)
            
            progress_text = f"`[{bar}]` {int(percentage * 100)}% ({current}/{target})"
