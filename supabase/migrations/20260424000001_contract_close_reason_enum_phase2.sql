-- =============================================================================
-- Phase 2 of the close-path enum expand-and-contract migration (PR #6).
--
-- SCOPE: ONLY the check_close_reason_enum 14→9 contraction. Drops the
-- 5 legacy close_reason values from the CHECK, leaving the strict
-- canonical 9-value set.
--
-- close_path_required was added in Phase 1 Step 7 with a more
-- defensive definition (uses 'status IS DISTINCT FROM closed' for
-- the open-row gate, strict '<' for the cutoff comparison). Phase 2
-- deliberately leaves it untouched.
--
-- HISTORY: An earlier draft of this file (merged as PR #802) included
-- a DROP IF EXISTS + ADD of close_path_required with a slightly
-- weaker definition ('closed_at IS NULL' open-row gate, '<=' cutoff
-- comparison). That draft was caught at pre-apply re-verification
-- per CLAUDE.md §Migration Apply Procedure step 2 (re-derive from
-- upstream sources, not from artifact under review) and never
-- applied to production. The correction shipped via the fix PR that
-- contains this revised file.
--
-- Phase 1 file (reference):
--   supabase/migrations/20260423000001_expand_close_reason_enum_phase1.sql
--
-- Grandfather cutoff (referenced for context only — no longer
-- modified by Phase 2):
--   GRANDFATHER_CUTOFF = '2026-04-26 00:00:00+00'
--   Historical paper_positions rows closed before this timestamp are
--   exempt from close_path_required (the Phase 1 constraint). Phase 2
--   does not re-issue the constraint, so this cutoff is informational.
--
-- Operator reference:
--   docs/pr6_close_path_consolidation.md
--   — §3 timeline, §5 verification queries, §6 rollback procedures
-- =============================================================================


-- =============================================================================
-- REQUIRED MANUAL STEP — NOT executed by this migration
--
-- Before applying this migration, the operator (human OR scheduled
-- verification job) MUST run the verification queries from the ops
-- doc §5 and confirm all four return the expected "all clean" result.
--
-- The CORE pre-check — zero post-deploy legacy writes:
--
--     SELECT close_reason, COUNT(*), MAX(closed_at)
--       FROM paper_positions
--      WHERE close_reason IN (
--              'target_profit',
--              'stop_loss',
--              'alpaca_fill_reconciled_2026_04_16',
--              'manual_internal_fill',
--              'alpaca_fill_manual'
--            )
--        AND closed_at > '<PR #6 DEPLOY TIMESTAMP>'
--      GROUP BY close_reason;
--
-- EXPECTED RESULT: zero rows.
--
-- IF ANY ROWS RETURN:
--   A handler migration in PR #6 missed a call site, OR a new code
--   path has been added that writes a legacy close_reason. DO NOT
--   APPLY THIS MIGRATION. Diagnose and fix in a follow-up PR,
--   re-verify, then apply Phase 2.
--
-- Additional verification queries (all must pass — see docs §5):
--   §5.2 every new close has fill_source populated
--   §5.3 every new close has a canonical 9-value close_reason
--   §5.4 no recurring close_path_anomaly critical alerts
--
-- The Phase 2 PR description MUST reference the specific
-- verification result capture (risk_alerts row with
-- metadata.verification_type='phase2_precheck', or observation_log
-- entry) — not a screenshot, not "I ran it" — as evidence that
-- the pre-check passed cleanly.
-- =============================================================================

BEGIN;

-- Step 1 (sole step). Drop-and-replace the close_reason CHECK.
-- Contracts the Phase-1 14-value permissive set to the strict
-- 9-value canonical set. Legacy rows (closed_at < GRANDFATHER_CUTOFF)
-- are unaffected by the CHECK change because DROP + ADD with IS NULL
-- handling leaves them in place — CHECK constraints only validate on
-- INSERT/UPDATE, not on existing rows. Phase 1 Step 4 already renamed
-- all legacy values to canonical, so historical rows pass the new
-- CHECK by virtue of the rename, not grandfathering.
--
-- DROP IF EXISTS + ADD is idempotent: safe on retry.
ALTER TABLE paper_positions
    DROP CONSTRAINT IF EXISTS check_close_reason_enum;
ALTER TABLE paper_positions
    ADD CONSTRAINT check_close_reason_enum
    CHECK (
        close_reason IS NULL
        OR close_reason IN (
            'target_profit_hit',
            'stop_loss_hit',
            'dte_threshold',
            'expiration_day',
            'manual_close_user_initiated',
            'alpaca_fill_reconciler_sign_corrected',
            'alpaca_fill_reconciler_standard',
            'envelope_force_close',
            'orphan_fill_repair'
        )
    );

-- (close_path_required intentionally NOT touched here — Phase 1
-- Step 7 owns it. See header HISTORY note.)

COMMIT;


-- =============================================================================
-- Rollback (if Phase 2 deploy fails or CHECK rejects legitimate writes)
--
-- See docs/pr6_close_path_consolidation.md §6.1 for the full playbook.
-- Abbreviated:
--
--   BEGIN;
--     ALTER TABLE paper_positions DROP CONSTRAINT check_close_reason_enum;
--     ALTER TABLE paper_positions
--       ADD CONSTRAINT check_close_reason_enum
--       CHECK (
--         close_reason IS NULL
--         OR close_reason IN (
--           -- Restore Phase 1's 14-value permissive set
--           'target_profit_hit', 'stop_loss_hit', 'dte_threshold',
--           'expiration_day', 'manual_close_user_initiated',
--           'alpaca_fill_reconciler_sign_corrected',
--           'alpaca_fill_reconciler_standard',
--           'envelope_force_close', 'orphan_fill_repair',
--           'target_profit', 'stop_loss',
--           'alpaca_fill_reconciled_2026_04_16',
--           'manual_internal_fill', 'alpaca_fill_manual'
--         )
--       );
--   COMMIT;
--
-- Rollback scope note:
--   close_path_required is NOT touched by rollback. Phase 1 owns
--   that constraint and Phase 2 never modified it; the rollback
--   only needs to undo Phase 2's check_close_reason_enum
--   contraction.
--
-- Rollback semantics:
--   Accepting legacy close_reason values TEMPORARILY is strictly
--   better than a stuck strict constraint that rejects every
--   legitimate write. Rollback buys time to diagnose; does not
--   absolve the investigation.
-- =============================================================================
