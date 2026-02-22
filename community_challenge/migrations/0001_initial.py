from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("bd_models", "0014_alter_ball_options_alter_ballinstance_options_and_more"),
    ]

    operations = [
        # ------------------------------------------------------------------
        # ChallengeSettings (singleton)
        # ------------------------------------------------------------------
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
                        help_text=(
                            "Discord channel ID where challenge completion announcements are sent. "
                            "Leave blank to disable announcements."
                        ),
                    ),
                ),
            ],
            options={
                "verbose_name": "Challenge settings",
            },
        ),
        # ------------------------------------------------------------------
        # CommunityChallenge
        # ------------------------------------------------------------------
        migrations.CreateModel(
            name="CommunityChallenge",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "name",
                    models.CharField(
                        max_length=64, help_text="Display name shown to players."
                    ),
                ),
                (
                    "description",
                    models.CharField(
                        blank=True,
                        max_length=256,
                        help_text="Short description shown in the /challenge embed.",
                    ),
                ),
                (
                    "challenge_type",
                    models.CharField(
                        choices=[
                            ("collect", "Collect"),
                            ("trade", "Trade"),
                            ("craft", "Craft"),
                            ("catch", "Catch"),
                            ("donate", "Donate"),
                        ],
                        default="catch",
                        max_length=16,
                        help_text="The action type players must perform to contribute.",
                    ),
                ),
                (
                    "target_amount",
                    models.PositiveIntegerField(
                        default=1000,
                        help_text="Total community-wide contributions needed to complete this challenge.",
                    ),
                ),
                (
                    "reward_item",
                    models.CharField(
                        blank=True,
                        max_length=64,
                        help_text="String key identifying the reward (e.g. 'winter_crate').",
                    ),
                ),
                (
                    "reward_quantity",
                    models.PositiveSmallIntegerField(
                        default=1,
                        help_text="How many reward items each contributor receives upon completion.",
                    ),
                ),
                (
                    "enabled",
                    models.BooleanField(
                        default=True,
                        help_text="Toggle visibility without deleting the challenge.",
                    ),
                ),
                (
                    "completed",
                    models.BooleanField(
                        default=False,
                        help_text=(
                            "Set automatically when progress reaches target_amount. "
                            "Reset to False to re-open the challenge."
                        ),
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "verbose_name": "Community Challenge",
                "verbose_name_plural": "Community Challenges",
                "ordering": ("-created_at",),
            },
        ),
        # ------------------------------------------------------------------
        # ChallengeProgress
        # ------------------------------------------------------------------
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
                (
                    "amount",
                    models.PositiveIntegerField(
                        default=0,
                        help_text="Cumulative contribution by this player to this challenge.",
                    ),
                ),
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
            index=models.Index(
                fields=("challenge", "amount"), name="cc_challenge_amount_idx"
            ),
        ),
        # ------------------------------------------------------------------
        # ChallengeReward
        # ------------------------------------------------------------------
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
                ("reward_item", models.CharField(max_length=64)),
                ("reward_quantity", models.PositiveSmallIntegerField()),
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
