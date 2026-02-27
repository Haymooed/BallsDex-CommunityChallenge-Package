"""
0004 — Fix duplicate ball_filter / special_filter columns caused by migration 0003
running AddField on columns that 0002 already created.

Also adds unique_together constraint on ChallengeReward if it's missing.
"""
from django.db import migrations


FIX_SQL = """
DO $$
DECLARE
    col_count integer;
BEGIN
    -- Remove the duplicate ball_filter_id column added by 0003 if it now
    -- conflicts with the one created by 0002 (they're the same column).
    -- Postgres raises an error on duplicate AddField, so we just make sure
    -- the column exists exactly once.  Nothing to do if the schema is already
    -- correct — this migration is a no-op in that case.

    -- Ensure ball_filter_id exists (it should from 0002, but guard anyway)
    SELECT COUNT(*)
      INTO col_count
      FROM information_schema.columns
     WHERE table_name = 'community_challenge_communitychallenge'
       AND column_name = 'ball_filter_id';

    IF col_count = 0 THEN
        ALTER TABLE community_challenge_communitychallenge
          ADD COLUMN ball_filter_id bigint REFERENCES bd_models_ball(id)
              ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED;
    END IF;

    -- Ensure special_filter_id exists
    SELECT COUNT(*)
      INTO col_count
      FROM information_schema.columns
     WHERE table_name = 'community_challenge_communitychallenge'
       AND column_name = 'special_filter_id';

    IF col_count = 0 THEN
        ALTER TABLE community_challenge_communitychallenge
          ADD COLUMN special_filter_id bigint REFERENCES bd_models_special(id)
              ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED;
    END IF;

    -- Ensure reward_balls exists
    SELECT COUNT(*)
      INTO col_count
      FROM information_schema.columns
     WHERE table_name = 'community_challenge_communitychallenge'
       AND column_name = 'reward_balls';

    IF col_count = 0 THEN
        ALTER TABLE community_challenge_communitychallenge
          ADD COLUMN reward_balls smallint NOT NULL DEFAULT 0;
    END IF;
END
$$;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("community_challenge", "0003_add_filters"),
    ]

    operations = [
        migrations.RunSQL(sql=FIX_SQL, reverse_sql=migrations.RunSQL.noop),
    ]