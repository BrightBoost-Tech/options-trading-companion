-- #115 PR-A Layer 3 fix — UNIQUE (underlying, as_of_date) constraint on
-- underlying_iv_points so IVRepository.upsert_iv_point's
-- on_conflict="underlying, as_of_date" actually resolves.
--
-- Diagnostic 2026-05-08: post-#901 manual fire ran the producer
-- chain end-to-end. Handler reported {ok: 68, failed: 2} but
-- underlying_iv_points stayed at 0 rows. Root cause: every upsert
-- errored with PostgreSQL 42P10 ("no unique or exclusion constraint
-- matching the ON CONFLICT specification") and the silent except in
-- IVRepository.upsert_iv_point swallowed it. Layer 3 of the PR-A
-- wrapper-drift cascade.
--
-- Pre-flight verified 2026-05-09: zero duplicate (underlying,
-- as_of_date) pairs in current data (table is empty), so this
-- constraint adds cleanly. No data-cleanup section needed.

BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'underlying_iv_points_underlying_as_of_date_key'
          AND conrelid = 'public.underlying_iv_points'::regclass
    ) THEN
        ALTER TABLE underlying_iv_points
            ADD CONSTRAINT underlying_iv_points_underlying_as_of_date_key
            UNIQUE (underlying, as_of_date);
    END IF;
END $$;

-- Verification: constraint must exist post-apply.
DO $$
DECLARE _exists boolean;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'underlying_iv_points_underlying_as_of_date_key'
          AND conrelid = 'public.underlying_iv_points'::regclass
    ) INTO _exists;
    IF NOT _exists THEN
        RAISE EXCEPTION 'underlying_iv_points UNIQUE constraint not present post-apply';
    END IF;
END $$;

COMMIT;

NOTIFY pgrst, 'reload schema';
