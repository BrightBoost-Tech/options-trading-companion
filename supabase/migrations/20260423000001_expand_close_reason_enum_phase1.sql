-- PR #6 Commit 1 — close-path consolidation foundation (PHASE 1 of 2)
--
-- Expand-and-contract migration strategy chosen to eliminate the
-- deploy-ordering collision window that would exist with a strict
-- CHECK constraint. See Commit 10 (Phase 2,
-- 20260424000001_contract_close_reason_enum_phase2.sql) for the
-- follow-up tightening.
--
-- PHASE 1 (THIS FILE): permissive CHECK accepting BOTH legacy and
-- new enum values (14 total). Pre-merge code writing legacy values
-- does not collide; post-merge code writes new values. Migration
-- can run at any time, any order relative to the Railway deploy.
--
-- PHASE 2 (follow-up, ~24h after PR #6 deploys): verifies zero
-- post-deploy writes of legacy values, then drops-and-recreates the
-- CHECK to the strict 9-value enum. Verification query embedded in
-- the Phase 2 migration file.
--
-- ==========================================================
-- SHARED CONSTANT (referenced by both Phase 1 and Phase 2):
--
--   GRANDFATHER_CUTOFF = '2026-04-26 00:00:00+00'
--
-- Any paper_positions row with closed_at < this timestamp is
-- exempt from the combined post-migration CHECK (fill_source
-- + close_reason + realized_pl all required). Buffer of ~3d
-- past the Phase 1 migration date (2026-04-23) absorbs deploy
-- window + operator lag + weekend. Phase 2 must reference the
-- EXACT same timestamp to preserve grandfather semantics.
-- ==========================================================
--
-- -------------------------------------------------------------------
-- Pre-migration inventory (verified 2026-04-22 against production):
--   target_profit                         44 rows
--   stop_loss                              7 rows
--   alpaca_fill_reconciled_2026_04_16      3 rows
--   manual_internal_fill                   2 rows
--   alpaca_fill_manual                     2 rows
--   alpaca_fill_reconciler_sign_corrected  1 row
--   ---                                   --
--   Total closed rows                     59
--
-- Post-Phase-1 inventory target:
--   target_profit_hit                     44 rows (renamed)
--   stop_loss_hit                          7 rows (renamed)
--   alpaca_fill_reconciler_standard        3 rows (renamed)
--   manual_endpoint                        4 rows (2+2, renamed)
--   alpaca_fill_reconciler_sign_corrected  1 row  (unchanged)
--   ---                                   --
--   Total closed rows                     59
--
-- All 59 rows also have close_reason_legacy_original populated
-- with the original pre-migration value for audit traceability.
-- -------------------------------------------------------------------
--
-- Rollback plan (reverse order of the 7 steps below):
--   1. ALTER TABLE paper_positions DROP CONSTRAINT close_path_required;
--   2. ALTER TABLE paper_positions DROP CONSTRAINT check_fill_source_enum;
--   3. ALTER TABLE paper_positions DROP CONSTRAINT check_close_reason_enum;
--   4. UPDATE paper_positions
--        SET close_reason = close_reason_legacy_original
--        WHERE close_reason_legacy_original IS NOT NULL;
--   5. ALTER TABLE paper_positions DROP COLUMN close_reason_legacy_original;
--   6. ALTER TABLE paper_positions DROP COLUMN fill_source;
--
-- close_reason_legacy_original stays as historical metadata after
-- Phase 2 completes — it's cheap and aids future diagnostics.
--
-- ROLLBACK CAUTION: if Phase 2 has already applied (strict 9-value
-- CHECK active), Phase 1 rollback is unsafe. Roll back Phase 2
-- FIRST (restoring the 14-value permissive CHECK), then Phase 1.
-- In practice: if Phase 2 is in production, do not attempt to roll
-- back Phase 1 without planning a multi-step recovery.

BEGIN;

-- Step 1. Add fill_source column (nullable; NULL on all legacy rows
--         so pre-migration closes are grandfathered by the combined
--         constraint in Step 7).
ALTER TABLE paper_positions
    ADD COLUMN IF NOT EXISTS fill_source TEXT;

-- Step 2. Add close_reason_legacy_original column (audit breadcrumb).
ALTER TABLE paper_positions
    ADD COLUMN IF NOT EXISTS close_reason_legacy_original TEXT;

-- Step 3. Populate close_reason_legacy_original from the current
--         close_reason for every row that has one. Run BEFORE the
--         rename so we capture the original value regardless of
--         whether it's in the renamed set.
UPDATE paper_positions
SET close_reason_legacy_original = close_reason
WHERE close_reason IS NOT NULL
  AND close_reason_legacy_original IS NULL;

-- Step 4. Rename 58 legacy close_reason values to new-enum values.
--         The 1 row already at 'alpaca_fill_reconciler_sign_corrected'
--         (PYPL cfe69b28 from the 2026-04-20 corrective UPDATE) is
--         not touched — it's already in the new enum.
UPDATE paper_positions SET close_reason = 'target_profit_hit'
    WHERE close_reason = 'target_profit';

UPDATE paper_positions SET close_reason = 'stop_loss_hit'
    WHERE close_reason = 'stop_loss';

UPDATE paper_positions SET close_reason = 'alpaca_fill_reconciler_standard'
    WHERE close_reason = 'alpaca_fill_reconciled_2026_04_16';

UPDATE paper_positions SET close_reason = 'manual_close_user_initiated'
    WHERE close_reason IN ('manual_internal_fill', 'alpaca_fill_manual');

-- Step 5. CHECK constraint on close_reason — PERMISSIVE (14 values).
--         Accepts both legacy values (writable by pre-merge code,
--         about to be gone once deploy completes) and new values
--         (writable by post-merge code). Phase 2 drops-and-replaces
--         this with a 9-value strict CHECK after verifying zero
--         post-deploy legacy writes.
--
--         DROP IF EXISTS + ADD is idempotent: re-running the
--         migration is safe. If an operator retries after a transient
--         failure, the second run behaves identically to the first.
ALTER TABLE paper_positions
    DROP CONSTRAINT IF EXISTS check_close_reason_enum;
ALTER TABLE paper_positions
    ADD CONSTRAINT check_close_reason_enum
    CHECK (
        close_reason IS NULL
        OR close_reason IN (
            -- New enum (9 values — target state after Phase 2)
            'target_profit_hit',
            'stop_loss_hit',
            'dte_threshold',
            'expiration_day',
            'manual_close_user_initiated',
            'alpaca_fill_reconciler_sign_corrected',
            'alpaca_fill_reconciler_standard',
            'envelope_force_close',
            'orphan_fill_repair',
            -- Legacy values (5 — temporarily accepted during the
            -- ~24h expand-and-contract window. Phase 2 drops these.)
            'target_profit',
            'stop_loss',
            'alpaca_fill_reconciled_2026_04_16',
            'manual_internal_fill',
            'alpaca_fill_manual'
        )
    );

-- Step 6. CHECK constraint on fill_source — strict (4 values).
--         No legacy values to accommodate since this is a new column.
--         NULL permitted for pre-migration rows (grandfathered by
--         Step 7's combined constraint).
ALTER TABLE paper_positions
    DROP CONSTRAINT IF EXISTS check_fill_source_enum;
ALTER TABLE paper_positions
    ADD CONSTRAINT check_fill_source_enum
    CHECK (
        fill_source IS NULL
        OR fill_source IN (
            'alpaca_fill_reconciler',
            'orphan_fill_repair',
            'exit_evaluator',
            'manual_endpoint'
        )
    );

-- Step 7. Combined CHECK: post-migration closes must have all three
--         fields populated (fill_source, close_reason, realized_pl).
--         Pre-migration closed rows grandfathered by GRANDFATHER_CUTOFF
--         (defined in the header comment). Phase 2 uses the exact
--         same timestamp literal when recreating this constraint.
--
--         `IS DISTINCT FROM 'closed'` used instead of `!= 'closed'`
--         because paper_positions.status is declared nullable; with
--         `!=`, a NULL status row would return NULL (unknown) and
--         the whole CHECK could behave unexpectedly. With IS DISTINCT
--         FROM, NULL status rows are treated as "not closed" and
--         pass the constraint. Backlog task #58 tracks whether
--         status should be NOT NULL; this constraint is NULL-safe
--         either way.
ALTER TABLE paper_positions
    DROP CONSTRAINT IF EXISTS close_path_required;
ALTER TABLE paper_positions
    ADD CONSTRAINT close_path_required
    CHECK (
        status IS DISTINCT FROM 'closed'
        OR closed_at < '2026-04-26 00:00:00+00'::timestamptz
        OR (
            fill_source IS NOT NULL
            AND close_reason IS NOT NULL
            AND realized_pl IS NOT NULL
        )
    );

COMMIT;

-- -------------------------------------------------------------------
-- Post-migration verification query (run MANUALLY post-deploy;
-- this file does not execute it as part of the migration):
--
--   SELECT close_reason, COUNT(*) AS n
--   FROM paper_positions
--   WHERE close_reason IS NOT NULL
--   GROUP BY close_reason
--   ORDER BY n DESC;
--
-- Expected after Phase 1:
--   target_profit_hit                       44
--   stop_loss_hit                            7
--   manual_endpoint                          4
--   alpaca_fill_reconciler_standard          3
--   alpaca_fill_reconciler_sign_corrected    1
--                                         ---
--   Total                                   59
--
-- Any row with close_reason in the 5 legacy values after Phase 1
-- applies means a handler missed the migration — investigate before
-- running Phase 2 (which will reject legacy values and FAIL if any
-- post-deploy legacy writes exist).
-- -------------------------------------------------------------------
