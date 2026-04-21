from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

     dependencies = [
        ("bd_models", "0014_alter_ball_options_alter_ballinstance_options_and_more"),  # not 0015
        ("community_challenge", "0005_challenge_challengeparticipant_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ChallengeReward",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("challenge", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="rewards",
                    to="community_challenge.challenge",
                )),
                ("rank", models.PositiveIntegerField(
                    help_text="The rank this reward is given to (e.g., 1 for 1st place)."
                )),
                ("ball", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    to="bd_models.ball",
                    help_text="The specific ball to reward.",
                )),
                ("amount", models.PositiveIntegerField(
                    default=1,
                    help_text="How many of this ball to give.",
                )),
            ],
            options={
                "verbose_name": "Reward",
                "verbose_name_plural": "Rewards",
                "ordering": ["rank"],
            },
        ),
    ]
