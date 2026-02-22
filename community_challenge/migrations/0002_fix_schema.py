"""
0002_fix_schema
---------------
Corrective migration for users who ran an earlier broken version.
Drops all community_challenge_* tables (CASCADE) and recreates them
with the correct schema. Safe because the previous version 500'd on
every admin panel page — no real data exists.
"""
from django.db import migrations, models
import django.db.models.deletion

DROP = """
DROP TABLE IF EXISTS community_challenge_challengereward    CASCADE;
DROP TABLE IF EXISTS community_challenge_challengeprogress  CASCADE;
DROP TABLE IF EXISTS community_challenge_communitychallenge CASCADE;
DROP TABLE IF EXISTS community_challenge_challengesettings  CASCADE;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("community_challenge", "0001_initial"),
        ("bd_models", "0014_alter_ball_options_alter_ballinstance_options_and_more"),
    ]

    operations = [
        migrations.RunSQL(sql=DROP, reverse_sql=migrations.RunSQL.noop),

        migrations.CreateModel(
            name="ChallengeSettings",
            fields=[
                ("singleton_id", models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
                ("enabled", models.BooleanField(default=True, help_text="Master switch — disable to hide all challenges.")),
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
                        ("catch_special", "Catch a special ball"),
                        ("guess_wrong", "Guess wrong (wrong answer attempts)"),
                        ("guess_correct", "Guess correct (first-try catches)"),
                        ("trade", "Complete a trade"),
                        ("balls_owned", "Community total balls owned"),
                        ("unique_balls", "Community unique ball types owned"),
                        ("specials_owned", "Community total specials owned"),
                    ],
                    default="catch_any",
                    max_length=20,
                )),
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