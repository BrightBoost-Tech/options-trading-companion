-- PR-② (E16-3 + F-REPLAY-FK, 2026-07-13): tape-integrity annotation on
-- decision_runs.
--
-- Root cause (ledger 07-13 ~13:0x CT): BlobStore staged raw gzip bytes as
-- `payload`, which supabase-py's JSON layer cannot serialize — EVERY blob
-- batch failed since capture went live, data_blobs has ZERO rows all-time,
-- and every decision_inputs insert FK-orphaned. Every pre-fix capture row is
-- therefore an unrecoverable tape.
--
-- Column semantics (written by DecisionContext.commit from this PR's SHA):
--   'complete'             — all input blobs confirmed persisted
--   'capture_partial'      — typed degrade: >=1 input blob unpersisted
--                            (failed batch / oversize drop); decision_inputs
--                            carries the persisted subset only
--   'commit_failed'        — the commit itself raised (_try_mark_failed)
--   'blob_never_persisted' — BACKFILL below: every pre-fix row (the
--                            all-time-zero-blobs era; move-don't-lose)
--
-- The TRUE tape-complete boundary stamps at this PR's squashed SHA.

ALTER TABLE decision_runs
    ADD COLUMN IF NOT EXISTS tape_integrity text;

-- Backfill: every existing row predates the fix — no blob it references was
-- ever persisted (data_blobs was empty at backfill time; verified 07-13).
UPDATE decision_runs
SET tape_integrity = 'blob_never_persisted'
WHERE tape_integrity IS NULL;
