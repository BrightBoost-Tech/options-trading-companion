-- job_runs.status CHECK — add 'partial' (ledgered latent HIGH).
--
-- FINDING (adjudicated 2026-07-18, primary evidence):
--   The F-A4-1 typed-outcome contract (2026-07-11) taught the job runner to
--   record status='partial' for a run that COMPLETED but had failed units
--   (succeeded-with-errors). The write path is:
--     packages/quantum/jobs/runner.py:_classify_handler_return  → returns "partial"
--       when users_failed>0 OR counts.errors>0 OR a truthy top-level 'error';
--     packages/quantum/jobs/runner.py:174-177  → store.mark_partial_failure(...);
--     packages/quantum/jobs/job_runs.py:168-176 → UPDATE job_runs SET status='partial'.
--
--   BUT the job_runs_status_check CHECK constraint (created in
--   20251220000001_job_runs_db_queue.sql) was never widened to include
--   'partial'. Live constraint at adjudication time:
--     CHECK (status = ANY (ARRAY['queued','running','succeeded',
--                                'failed_retryable','dead_lettered','cancelled']))
--   A 'partial' UPDATE therefore raises 23514 (check_violation). That raise
--   occurs INSIDE run_job_run's outer try (runner.py:148), so it is caught by
--   the generic `except Exception` (runner.py:200) and the run is wrongly
--   RE-QUEUED as failed_retryable / dead-lettered — re-running the whole job
--   and redoing the units that already succeeded. That is the exact harm the
--   'partial' terminal status was introduced to prevent. LATENT: the classifier
--   only returns 'partial' when a handler reports failed units, which has not
--   fired live yet (0 'partial' and 0 'failed_retryable' rows observed
--   2026-07-18), so the constraint has not yet been exercised into a crash.
--
-- FIX: drop and re-add the SAME-NAMED constraint, preserving EVERY currently
-- allowed status value EXACTLY and adding only 'partial'. No row rewrites; no
-- change to any other object. Idempotent-safe (IF EXISTS on the drop).
--
-- NOTE: This migration is UNAPPLIED by the PR that introduces it. An operator
-- applies it (project doctrine: migration-before-merge for any read of the new
-- value; here the writer already ships, so apply this BEFORE the next run that
-- can classify 'partial').

ALTER TABLE job_runs DROP CONSTRAINT IF EXISTS job_runs_status_check;

ALTER TABLE job_runs
    ADD CONSTRAINT job_runs_status_check
    CHECK (status IN (
        'queued',
        'running',
        'succeeded',
        'failed_retryable',
        'dead_lettered',
        'cancelled',
        'partial'
    ));
