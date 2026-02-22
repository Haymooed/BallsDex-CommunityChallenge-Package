"""
0002_fix_schema
---------------
Corrective migration for users who ran an earlier broken version of this
package where the tables were created with a different column set.

Strategy:
  1. Drop all four community_challenge_* tables if they exist (CASCADE).
  2. Re-create them with the correct schema.

This is safe because the previous version never worked (admin panel 500'd),
so there is no real data to preserve.
"""

from django.db import migrations, models
import django.db.models.deletion


DROP_TABLES = """
DROP TABLE IF EXISTS community_challenge_challengereward       CASCADE;
DROP TABLE IF EXISTS community_challenge_challengeprogress     CASCADE;
DROP TABLE IF EXISTS community_challenge_communitychallenge    CASCADE;
DROP TABLE IF EXISTS community_challenge_challengesettings     CASCADE;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("community_challenge", "0001_initial"),
        ("bd_models", "0014_alter_ball_options_alter_ballinstance_options_and_more"),
    ]

    operations = [
        # Step 1 — Wipe whatever is left from the broken previous schema.
        migrations.RunSQL(sql=DROP_TABLES, reverse_sql=migrations.RunSQL.noop),

        # Step 2 — Recreate ChallengeSettings with correct columns.
        migrations.CreateModel(
            name="ChallengeSettings",
            fields=[
                (
                    "singleton_id",
                    models.PositiveSmallIntegerField(
                        default=1, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "enabled",
                    models.BooleanField(
                        default=True,
                        help_text="Master switch — disable to hide all challenges from players.",
                    ),
                ),
                (
                    "announcement_channel_id",
                    models.BigIntegerField(
                        blank=True,
                        null=True,
                        help_text="Discord channel ID for completion announcements.",
                    ),
                ),
            ],
            options={
                "verbose_name": "Challenge settings",
                "verbose_name_plural": "Challenge settings",
            },
        ),

        # Step 3 — Recreate CommunityChallenge with correct columns.
        migrations.CreateModel(
            name="CommunityChallenge",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("name", models.CharField(max_length=64, help_text="Display name shown to players.")),
                ("description", models.CharField(blank=True, max_length=256)),
                (
                    "challenge_type",
                    models.CharField(
                        choices=[("catch", "Catch"), ("trade", "Trade")],
                        default="catch",
                        max_length=16,
                    ),
                ),
                ("target_amount", models.PositiveIntegerField(default=1000)),
                ("reward_balls", models.PositiveSmallIntegerField(default=0)),
                ("enabled", models.BooleanField(default=True)),
                ("completed", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "verbose_name": "Community Challenge",
                "verbose_name_plural": "Community Challenges",
                "ordering": ("-created_at",),
            },
        ),

        # Step 4 — Recreate ChallengeProgress.
        migrations.CreateModel(
            name="ChallengeProgress",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "challenge",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="progress_entries",
                        to="community_challenge.communitychallenge",
                    ),
                ),
                (
                    "player",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="challenge_progress",
                        to="bd_models.player",
                    ),
                ),
                ("amount", models.PositiveIntegerField(default=0)),
                ("last_updated", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Challenge Progress",
                "verbose_name_plural": "Challenge Progress Entries",
                "ordering": ("-amount",),
            },
        ),
        migrations.AddConstraint(
            model_name="challengeprogress",
            constraint=models.UniqueConstraint(
                fields=("challenge", "player"), name="cc_unique_challenge_player"
            ),
        ),
        migrations.AddIndex(
            model_name="challengeprogress",
            index=models.Index(fields=("challenge", "amount"), name="cc_challenge_amount_idx"),
        ),

        # Step 5 — Recreate ChallengeReward.
        migrations.CreateModel(
            name="ChallengeReward",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "challenge",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="rewards_issued",
                        to="community_challenge.communitychallenge",
                    ),
                ),
                (
                    "player",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="challenge_rewards",
                        to="bd_models.player",
                    ),
                ),
                ("balls_given", models.PositiveSmallIntegerField(default=0)),
                ("issued_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Challenge Reward",
                "verbose_name_plural": "Challenge Rewards",
                "ordering": ("-issued_at",),
            },
        ),
        migrations.AddConstraint(
            model_name="challengereward",
            constraint=models.UniqueConstraint(
                fields=("challenge", "player"), name="cc_unique_reward_per_challenge"
            ),
        ),
    ]