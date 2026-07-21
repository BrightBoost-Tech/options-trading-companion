-- =============================================================================
-- BACKFILL PREFLIGHT (operator artifact — NOT a migration, NOT applied here)
-- fleet_reconciliation_receipts <- the four completed 07-18 reconciliations
-- =============================================================================
-- NOT APPLIED BY THIS PR. Fable runs this ONE idempotent transaction ONLY if the
-- preflight verdict is eligible. Requires 20260720140000_fleet_reconciliation_
-- receipts.sql applied first. Applying it activates NOTHING and binds NO slot.
-- Portable: no psql-only meta-commands — runs via psql or the Supabase MCP.
--
-- ── PREFLIGHT VERDICT: BLOCKED_RECEIPT_ID_NOT_DURABLE ────────────────────────
-- Read-only DB adjudication (2026-07-20) of the four candidate reconciliations.
-- A source row is ELIGIBLE only when ALL SEVEN are independently proven from
-- DURABLE data: (1) exact source row, (2) a FULL STABLE receipt token already
-- present in durable source data (NOT derived from a displayed/truncated
-- prefix), (3) content fingerprint, (4) receipt kind (typed/durable), (5) user
-- scope, (6) effective epoch, (7) completed-reconciliation semantics.
--
-- NONE of the four qualifies. The reconciliation stamps are scattered
-- content-stamps with NO stable typed identity, NO typed receipt_kind, and NO
-- typed effective_epoch anywhere:
--
--   fp prefix  | source (durable)                | token form            | verdict
--   -----------|---------------------------------|-----------------------|------------------------------
--   04317fc1…  | paper_orders.cancelled_reason / | 12-char prose prefix; | INELIGIBLE — no typed receipt_id/
--              | broker_response (6 rows)        | 64-char run only in   | kind/epoch; stable token lives
--              |                                 | broker_response PROSE | in free-text prose
--   5d5cd9fc…  | paper_orders.broker_response    | 64-char run in PROSE  | INELIGIBLE — prose only; no typed
--              | (1 row)                         | only (no typed key)   | receipt_id/kind/epoch
--   40258ba9…  | job_runs.error.reconciliation.  | 16-char TRUNCATED     | INELIGIBLE — truncated token (<32)
--              | census_fingerprint (5 rows)     | typed field; job_runs | AND no durable user scope
--              |                                 | has NO user_id column | (job_runs lacks user_id)
--   b780271c…  | paper_ledger.metadata.          | FULL 64-char typed    | INELIGIBLE — full content_fp exists
--              | census_fingerprint (19 rows)    | field (plan-content   | but is a plan-content stamp, not a
--              |                                 | stamp, 19 rows share) | receipt IDENTITY; no typed kind/epoch
--
-- THE EXACT MISSING TOKEN (all four): a durable, typed RECEIPT IDENTITY
-- (receipt_id) — distinct from the plan content fingerprint — together with a
-- typed receipt_kind and a typed effective_epoch. Even the one full content
-- fingerprint (b780271c… on paper_ledger) is a PLAN-content stamp shared across
-- 19 rows, not an identity, and carries no kind/epoch. Manufacturing a
-- receipt_id / kind / epoch for these rows would FABRICATE a durable identity
-- that is not there — exactly what H9 and the prerequisite packet
-- (docs/review/fleet-receipt-contract-prerequisite-2026-07-19.md §1) refuse.
--
-- CONSEQUENCE: this transaction inserts ZERO receipt rows. The D1 schema still
-- applies (empty). Scenario 5 stays enforceable-but-unsatisfiable: the D3 RPC
-- gate requires an EXISTING receipt, and none exist, so activation stays
-- fail-closed and FORBIDDEN. A future durable receipt (written by a receipt-
-- writer that stamps id + kind + epoch + full fingerprint at reconciliation
-- time) is the ONLY path to eligibility — never a rewrite of these prose stamps.
--
-- Idempotency: ON CONFLICT (receipt_kind, content_fingerprint) DO NOTHING. A
-- replay is a zero-write no-op. The eligibility column is hard-coded FALSE for
-- every candidate with the missing-proof reason, so the INSERT ... SELECT WHERE
-- eligible inserts nothing regardless of the ON CONFLICT clause.
--
-- OPERATOR: before running, replace the placeholder in _backfill_params below
-- with the receipt-owner UUID (kept out of the file so no account id is
-- embedded). The DO block RAISEs if the placeholder is left in place.
-- =============================================================================

BEGIN;

-- ── Operator params (edit before running) ────────────────────────────────────
CREATE TEMPORARY TABLE _backfill_params ON COMMIT DROP AS
SELECT '<<REPLACE_WITH_OPERATOR_USER_UUID>>'::text AS operator_user_id;

-- ── Candidate set (the four 07-18 reconciliations) with hard eligibility ─────
-- eligible is FALSE for every row (see verdict). ineligible_reason is the exact
-- missing durable proof. best_durable_token is the strongest durable token found
-- — deliberately NOT good enough to insert.
CREATE TEMPORARY TABLE _recon_receipt_candidates ON COMMIT DROP AS
SELECT * FROM (VALUES
    ('04317fc1', 'stale_order',
     '04317fc1d91b', 12, 'paper_orders',
     'cancelled_reason 12-char prose prefix; 64-char run only in broker_response PROSE',
     false,
     'no typed receipt_id/kind/epoch; stable token lives in free-text prose, not a durable typed field'),
    ('5d5cd9fc', 'manual_review',
     '5d5cd9fc', 8, 'paper_orders',
     'broker_response resolution PROSE only (no typed fingerprint key)',
     false,
     'no typed receipt_id/kind/epoch; token present only as prose in broker_response'),
    ('40258ba9', 'orphan_run',
     '40258ba97a4e35d6', 16, 'job_runs',
     'error.reconciliation.census_fingerprint typed but TRUNCATED to 16 chars; job_runs has no user_id',
     false,
     'content_fingerprint truncated (<32) AND no durable user scope (job_runs lacks user_id); no typed receipt_id/kind/epoch'),
    ('b780271c', 'manual_review',
     'b780271c5b1717fcb8514f06573be0e1f4cb4a20b6e315ba4b82e89b91c01d68', 64, 'paper_ledger',
     'metadata.census_fingerprint full 64-char typed field (plan-content stamp, shared across 19 rows)',
     false,
     'full content fingerprint exists but is a plan-content stamp, not a receipt IDENTITY; no typed receipt_id/kind/epoch')
) AS c(fp_prefix, receipt_kind, best_durable_token, token_len,
       source_table, source_note, eligible, ineligible_reason);

-- ── Before count ─────────────────────────────────────────────────────────────
CREATE TEMPORARY TABLE _recon_receipt_counts ON COMMIT DROP AS
SELECT (SELECT count(*) FROM fleet_reconciliation_receipts) AS before_count;

-- ── Insert ONLY eligible rows (zero, by construction) ───────────────────────
-- Kept as a real INSERT so a FUTURE durable candidate (eligible=true, full
-- token, typed kind+epoch, user scope) would flow through this exact path.
INSERT INTO fleet_reconciliation_receipts (
    receipt_id, user_id, receipt_kind, content_fingerprint,
    effective_epoch, source_table, source_row_id, source_fingerprint,
    created_by
)
SELECT
    c.best_durable_token,               -- receipt_id (only for eligible rows)
    (SELECT operator_user_id FROM _backfill_params)::uuid,
    c.receipt_kind,
    c.best_durable_token,               -- content_fingerprint (full only when eligible)
    'small_tier_v1',
    c.source_table,
    c.fp_prefix,
    c.best_durable_token,
    'fable_lane_d_backfill_20260720'
  FROM _recon_receipt_candidates c
 WHERE c.eligible                        -- FALSE for all four -> 0 rows
ON CONFLICT (receipt_kind, content_fingerprint) DO NOTHING;

-- ── Post-insert integrity + audit receipt (fail -> ROLLBACK) ────────────────
DO $$
DECLARE
    v_before        int;
    v_after         int;
    v_inserted      int;
    v_eligible      int;
    v_user_raw      text;
    v_user_id       uuid;
    v_preflight_fp  text;
    v_verdict       text := 'BLOCKED_RECEIPT_ID_NOT_DURABLE';
BEGIN
    SELECT before_count INTO v_before FROM _recon_receipt_counts;
    SELECT count(*) INTO v_after FROM fleet_reconciliation_receipts;
    SELECT count(*) FILTER (WHERE eligible) INTO v_eligible
      FROM _recon_receipt_candidates;
    v_inserted := v_after - v_before;

    -- Contract: zero eligible -> zero inserted -> before == after.
    IF v_eligible <> 0 THEN
        RAISE EXCEPTION
            'backfill preflight: expected 0 eligible candidates, found % — '
            'verdict is BLOCKED_RECEIPT_ID_NOT_DURABLE and must insert nothing',
            v_eligible;
    END IF;
    IF v_inserted <> 0 THEN
        RAISE EXCEPTION
            'backfill preflight: inserted % rows on a BLOCKED verdict (expected 0)',
            v_inserted;
    END IF;
    IF v_after <> v_before THEN
        RAISE EXCEPTION
            'backfill preflight: row count changed (% -> %) on a zero-write backfill',
            v_before, v_after;
    END IF;

    -- Operator user scope for the audit receipt (kept out of the file).
    SELECT operator_user_id INTO v_user_raw FROM _backfill_params;
    IF v_user_raw IS NULL OR v_user_raw = '<<REPLACE_WITH_OPERATOR_USER_UUID>>' THEN
        RAISE EXCEPTION
            'backfill preflight: operator_user_id placeholder not replaced — '
            'edit _backfill_params with the receipt-owner UUID before running '
            '(no account id is embedded in this artifact)';
    END IF;
    v_user_id := v_user_raw::uuid;

    -- Derived (never client-invented) preflight fingerprint over the canonical
    -- verdict + candidate evidence, for the audit receipt.
    SELECT encode(extensions.digest(
        v_verdict || '|' || string_agg(
            c.fp_prefix || ':' || c.receipt_kind || ':' || c.token_len::text
              || ':' || c.ineligible_reason,
            '|' ORDER BY c.fp_prefix),
        'sha256'), 'hex')
      INTO v_preflight_fp
      FROM _recon_receipt_candidates c;

    INSERT INTO risk_alerts (
        user_id, alert_type, severity, message, resolved, metadata
    ) VALUES (
        v_user_id,
        'fleet_reconciliation_backfill',
        'info',
        'fleet_reconciliation_receipts backfill preflight: '
            || v_verdict || ' — 4 candidates adjudicated, 0 eligible, 0 inserted '
            || '(no durable typed receipt identity; see supabase/backfills header).',
        false,
        jsonb_build_object(
            'verdict', v_verdict,
            'preflight_fingerprint', v_preflight_fp,
            'candidates_total', 4,
            'candidates_eligible', v_eligible,
            'rows_before', v_before,
            'rows_after', v_after,
            'rows_inserted', v_inserted,
            'candidates', (
                SELECT jsonb_agg(jsonb_build_object(
                    'fp_prefix', c.fp_prefix,
                    'receipt_kind', c.receipt_kind,
                    'best_durable_token_len', c.token_len,
                    'source_table', c.source_table,
                    'ineligible_reason', c.ineligible_reason
                ) ORDER BY c.fp_prefix)
                FROM _recon_receipt_candidates c
            )
        )
    );

    RAISE NOTICE 'backfill preflight OK: % (before=% after=% inserted=% eligible=%)',
        v_verdict, v_before, v_after, v_inserted, v_eligible;
END $$;

COMMIT;

-- =============================================================================
-- ROLLBACK (only needed if a FUTURE eligible-row version of this file is run and
-- must be reverted). The zero-write BLOCKED run above changes no receipt rows,
-- so nothing here is required for it; provided for the eligible path.
-- =============================================================================
-- BEGIN;
--   -- Receipts are append-only (D1 trigger blocks DELETE), so reverting an
--   -- ERRONEOUS insert is an operator-privileged, trigger-disabled action:
--   --   ALTER TABLE fleet_reconciliation_receipts DISABLE TRIGGER
--   --       trg_fleet_recon_receipts_immutable;
--   --   DELETE FROM fleet_reconciliation_receipts
--   --    WHERE created_by = 'fable_lane_d_backfill_20260720';
--   --   ALTER TABLE fleet_reconciliation_receipts ENABLE TRIGGER
--   --       trg_fleet_recon_receipts_immutable;
--   -- Also delete the audit receipt:
--   --   DELETE FROM risk_alerts
--   --    WHERE alert_type = 'fleet_reconciliation_backfill'
--   --      AND metadata->>'preflight_fingerprint' = '<the fp from the run>';
-- COMMIT;
