from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("bd_models", "0014_alter_ball_options_alter_ballinstance_options_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ChallengeSettings",
            fields=[
                ("singleton_id", models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
                ("enabled", models.BooleanField(default=True)),
                ("announcement_channel_id", models.BigIntegerField(blank=True, null=True)),
            ],
            options={"verbose_name": "Challenge settings", "verbose_name_plural": "Challenge settings"},
        ),
        migrations.CreateModel(
            name="CommunityChallenge",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=64)),
                ("description", models.CharField(blank=True, max_length=256)),
                ("challenge_type", models.CharField(
                    choices=[
                        ("catch_any", "Catch any ball"),
                        ("catch_specific", "Catch a specific ball (set Ball filter below)"),
                        ("catch_special", "Catch any special ball"),
                        ("catch_specific_special", "Catch a specific special (set Special filter below)"),
                        ("guess_wrong", "Wrong guesses submitted"),
                        ("trade", "Trades completed"),
                        ("balls_owned", "Community total balls owned (snapshot)"),
                        ("unique_balls", "Community unique ball types owned (snapshot)"),
                        ("specials_owned", "Community total specials owned (snapshot)"),
                    ],
                    default="catch_any",
                    max_length=24,
                )),
                ("ball_filter", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="bd_models.ball")),
                ("special_filter", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="bd_models.special")),
                ("target_amount", models.PositiveIntegerField(default=1000)),
                ("reward_balls", models.PositiveSmallIntegerField(default=0)),
                ("enabled", models.BooleanField(default=True)),
                ("completed", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"verbose_name": "Community Challenge", "verbose_name_plural": "Community Challenges", "ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="ChallengeProgress",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("challenge", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="progress_entries", to="community_challenge.communitychallenge")),
                ("player", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="challenge_progress", to="bd_models.player")),
                ("amount", models.PositiveIntegerField(default=0)),
                ("last_updated", models.DateTimeField(auto_now=True)),
            ],
            options={"verbose_name": "Challenge Progress", "ordering": ("-amount",)},
        ),
        migrations.AddConstraint(
            model_name="challengeprogress",
            constraint=models.UniqueConstraint(fields=("challenge", "player"), name="cc_unique_challenge_player"),
        ),
        migrations.AddIndex(
            model_name="challengeprogress",
            index=models.Index(fields=("challenge", "amount"), name="cc_challenge_amount_idx"),
        ),
        migrations.CreateModel(
            name="ChallengeReward",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("challenge", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="rewards_issued", to="community_challenge.communitychallenge")),
                ("player", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="challenge_rewards", to="bd_models.player")),
                ("balls_given", models.PositiveSmallIntegerField(default=0)),
                ("issued_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"verbose_name": "Challenge Reward", "ordering": ("-issued_at",)},
        ),
        migrations.AddConstraint(
            model_name="challengereward",
            constraint=models.UniqueConstraint(fields=("challenge", "player"), name="cc_unique_reward_per_challenge"),
        ),
    ]