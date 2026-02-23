from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("community_challenge", "0002_fix_schema"),
        ("bd_models", "0014_alter_ball_options_alter_ballinstance_options_and_more"),
    ]

    operations = [
        # Add ball_filter_id column (nullable FK → bd_models.ball)
        migrations.AddField(
            model_name="communitychallenge",
            name="ball_filter",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="bd_models.ball",
                help_text=(
                    "Required for 'Catch a specific ball'. "
                    "Leave blank to accept any ball for other catch types."
                ),
            ),
        ),
        # Add special_filter_id column (nullable FK → bd_models.special)
        migrations.AddField(
            model_name="communitychallenge",
            name="special_filter",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="bd_models.special",
                help_text=(
                    "Required for 'Catch a specific special'. "
                    "Leave blank to accept any special."
                ),
            ),
        ),
        # Also update challenge_type choices + max_length to match current models
        migrations.AlterField(
            model_name="communitychallenge",
            name="challenge_type",
            field=models.CharField(
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
            ),
        ),
        migrations.RunSQL(
            sql="""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'community_challenge_communitychallenge'
                        AND column_name = 'reward_balls'
                    ) THEN
                        ALTER TABLE community_challenge_communitychallenge
                        ADD COLUMN reward_balls smallint NOT NULL DEFAULT 0;
                    END IF;
                END
                $$;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
