from django.db import migrations


ADD_MISSING_FILTER_COLUMNS = """
ALTER TABLE community_challenge_communitychallenge
    ADD COLUMN IF NOT EXISTS ball_filter_id bigint NULL,
    ADD COLUMN IF NOT EXISTS special_filter_id bigint NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'community_challenge_communitychallenge_ball_filter_id_fkey'
    ) THEN
        ALTER TABLE community_challenge_communitychallenge
            ADD CONSTRAINT community_challenge_communitychallenge_ball_filter_id_fkey
            FOREIGN KEY (ball_filter_id)
            REFERENCES bd_models_ball(id)
            ON DELETE SET NULL
            DEFERRABLE INITIALLY DEFERRED;
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'community_challenge_communitychallenge_special_filter_id_fkey'
    ) THEN
        ALTER TABLE community_challenge_communitychallenge
            ADD CONSTRAINT community_challenge_communitychallenge_special_filter_id_fkey
            FOREIGN KEY (special_filter_id)
            REFERENCES bd_models_special(id)
            ON DELETE SET NULL
            DEFERRABLE INITIALLY DEFERRED;
    END IF;
END
$$;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("community_challenge", "0002_fix_schema"),
    ]

    operations = [
        migrations.RunSQL(
            sql=ADD_MISSING_FILTER_COLUMNS,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
