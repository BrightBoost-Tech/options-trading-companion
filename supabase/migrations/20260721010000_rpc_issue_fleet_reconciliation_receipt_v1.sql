-- =============================================================================
-- Lane A — durable reconciliation-receipt WRITER RPC
-- rpc_issue_fleet_reconciliation_receipt_v1
-- =============================================================================
-- NOT APPLIED BY THIS PR. Function definition only; applied later via the
-- operator-owned migration procedure. Requires
-- 20260720140000_fleet_reconciliation_receipts.sql applied first (this RPC
-- INSERTs into that table). DEFINING this function activates NOTHING, binds NO
-- fleet slot, and — critically — ISSUES NO RECEIPT: a receipt is created only
-- when an operator/producer later CALLS the function with a durable source that
-- carries a completed-reconciliation marker. The fleet stays INACTIVE and
-- activation remains operator-only + FORBIDDEN.
--
-- WHY THIS EXISTS (closes the scenario-5 loop): the D2 backfill verdict is
-- BLOCKED_RECEIPT_ID_NOT_DURABLE — the four 07-18 reconciliations exist only as
-- scattered content-stamps with no stable typed identity, so no receipt could be
-- back-filled without FABRICATING identity (H9). The activation RPC
-- (20260720150000) is therefore fail-closed: it RAISEs receipt_not_found while
-- fleet_reconciliation_receipts is empty. This writer is the ONLY sanctioned way
-- to create a durable receipt: a FUTURE reconciliation producer stamps a typed
-- completed-state marker on its source row, then calls this RPC, which PROVES the
-- marker (user scope + kind + completed state + full fingerprint) before writing
-- exactly one immutable receipt. It never rewrites the historical prose stamps.
--
-- CONTRACT (all enforced server-side; the SQL is the final authority):
--   1. receipt_id is SERVER-GENERATED (opaque, gen_random_uuid-derived) — never
--      caller-supplied. Identity cannot be forged by the caller.
--   2. Required args: p_user_id, p_receipt_kind, p_effective_epoch,
--      p_content_fingerprint (full, len >= 32) + EXACTLY ONE durable source form
--      (p_source_alert_id  OR  p_source_table + p_source_row_id) + p_actor_class.
--   3. The source event row is LOCKED FOR UPDATE and must EXIST before insert.
--   4. The source event must (a) belong to p_user_id and (b) carry a typed,
--      durable COMPLETED-reconciliation marker of the requested kind. The marker
--      is <source jsonb col>->'reconciliation_receipt' =
--         {kind, status:'completed', content_fingerprint:<full>, effective_epoch}.
--      job_runs is REJECTED as a source (it has NO user_id column — a completed
--      reconciliation recorded only there is not durably user-attributable; per
--      contract that path RAISEs, it never fabricates a user scope). A source row
--      with no typed marker (the historical prose-only stamps) RAISEs too.
--   5. p_content_fingerprint must equal the durable source marker fingerprint,
--      FULL (>= 32) and case-insensitive — never a truncated display prefix.
--   6. Exactly ONE immutable receipt is inserted.
--   7. EXACT replay (same user/kind/epoch/fingerprint/source) returns the
--      EXISTING receipt with ZERO writes (idempotent; keyed on the natural
--      UNIQUE(receipt_kind, content_fingerprint)).
--   8. CONFLICTING replay (same kind+fingerprint but different user/epoch/source)
--      RAISEs receipt_conflict (typed).
--   9. NO update/delete path anywhere. The append-only trigger on the table is
--      the backstop; this function only ever SELECTs and INSERTs.
--  10. Fixed, safe search_path. EXECUTE granted to service_role ONLY
--      (REVOKE PUBLIC/anon/authenticated).
--  11. Makes NO activation call and NO policy/fleet mutation — it touches only
--      fleet_reconciliation_receipts (INSERT) and the source table (SELECT ...
--      FOR UPDATE; a lock, not a write).
--  12. Returns a typed receipt {receipt_id, receipt_kind, content_fingerprint,
--      user_id, effective_epoch, source_*, created_at, idempotent_replay} —
--      suitable for the activation attestation's reconciliation_receipts bundle.
-- =============================================================================

CREATE OR REPLACE FUNCTION rpc_issue_fleet_reconciliation_receipt_v1(
    p_user_id             uuid,
    p_receipt_kind        text,
    p_effective_epoch     text,
    p_content_fingerprint text,
    p_source_alert_id     uuid,
    p_source_table        text,
    p_source_row_id       text,
    p_actor_class         text
)
RETURNS jsonb
LANGUAGE plpgsql
-- Fixed, safe search_path (no mutable/implicit resolution). gen_random_uuid()
-- resolves from pg_catalog (always in path); no unqualified extension calls.
SET search_path = public, extensions, pg_temp
AS $$
DECLARE
    v_kind        text;
    v_epoch       text;
    v_fp          text;
    v_created_by  text;
    v_has_alert   boolean;
    v_src_table   text;
    v_src_row     text;
    v_row_uuid    uuid;
    v_src_user    uuid;
    v_json_col    jsonb;
    v_marker      jsonb;
    v_m_kind      text;
    v_m_state     text;
    v_m_fp        text;
    v_m_epoch     text;
    v_receipt_id  text;
    v_existing    fleet_reconciliation_receipts%ROWTYPE;
    v_new         fleet_reconciliation_receipts%ROWTYPE;
    v_ins_alert   uuid;
    v_ins_table   text;
    v_ins_row     text;
BEGIN
    -- ── 1. Argument validation ──────────────────────────────────────────────
    IF p_user_id IS NULL THEN
        RAISE EXCEPTION 'issue_reconciliation_receipt: user_id_required'
            USING ERRCODE = 'check_violation';
    END IF;

    v_kind := btrim(COALESCE(p_receipt_kind, ''));
    IF v_kind NOT IN ('stale_order', 'manual_review', 'orphan_run') THEN
        RAISE EXCEPTION
            'issue_reconciliation_receipt: receipt_kind_invalid (%) — allowed '
            '{stale_order, manual_review, orphan_run}', p_receipt_kind
            USING ERRCODE = 'check_violation';
    END IF;

    v_epoch := btrim(COALESCE(p_effective_epoch, ''));
    IF v_epoch = '' THEN
        RAISE EXCEPTION 'issue_reconciliation_receipt: effective_epoch_required'
            USING ERRCODE = 'check_violation';
    END IF;

    -- Full token only: a truncated display prefix (8/12/16-char) can never pose
    -- as the full fingerprint. Case-normalized (hashes are case-insensitive hex)
    -- so the stored key matches the activation binding's lower() comparison.
    v_fp := lower(btrim(COALESCE(p_content_fingerprint, '')));
    IF char_length(v_fp) < 32 THEN
        RAISE EXCEPTION
            'issue_reconciliation_receipt: content_fingerprint_not_full '
            '(len=%; a full token is required, never a truncated display prefix)',
            char_length(v_fp)
            USING ERRCODE = 'check_violation';
    END IF;

    v_created_by := left(
        COALESCE(NULLIF(btrim(p_actor_class), ''),
                 'reconciliation_receipt_writer_v1'), 200);

    -- ── 2. Provenance form: EXACTLY ONE of {alert} or {table+row} ───────────
    v_has_alert := p_source_alert_id IS NOT NULL;
    v_src_table := btrim(COALESCE(p_source_table, ''));
    v_src_row   := btrim(COALESCE(p_source_row_id, ''));

    IF v_has_alert AND (v_src_table <> '' OR v_src_row <> '') THEN
        RAISE EXCEPTION
            'issue_reconciliation_receipt: provenance_ambiguous (supply EITHER '
            'source_alert_id OR source_table+source_row_id, never both)'
            USING ERRCODE = 'check_violation';
    END IF;
    IF NOT v_has_alert AND NOT (v_src_table <> '' AND v_src_row <> '') THEN
        RAISE EXCEPTION
            'issue_reconciliation_receipt: provenance_missing (supply '
            'source_alert_id OR source_table+source_row_id)'
            USING ERRCODE = 'check_violation';
    END IF;

    IF v_has_alert THEN
        v_src_table := 'risk_alerts';
        v_row_uuid  := p_source_alert_id;
    ELSE
        -- job_runs has NO user_id column: a completed reconciliation recorded
        -- only there cannot be user-attributed. Contract: RAISE, never fabricate.
        IF v_src_table = 'job_runs' THEN
            RAISE EXCEPTION
                'issue_reconciliation_receipt: source_user_scope_unavailable '
                '(job_runs has no user_id column; a reconciliation recorded only '
                'in job_runs is not user-attributable — route an orphan_run '
                'receipt through a user-scoped risk_alerts marker instead)'
                USING ERRCODE = 'check_violation';
        END IF;
        IF v_src_table NOT IN ('risk_alerts', 'paper_orders', 'paper_ledger') THEN
            RAISE EXCEPTION
                'issue_reconciliation_receipt: source_table_unsupported (%) — '
                'allowed {risk_alerts, paper_orders, paper_ledger}', v_src_table
                USING ERRCODE = 'check_violation';
        END IF;
        BEGIN
            v_row_uuid := v_src_row::uuid;
        EXCEPTION WHEN others THEN
            RAISE EXCEPTION
                'issue_reconciliation_receipt: source_row_id_not_uuid (%)', v_src_row
                USING ERRCODE = 'check_violation';
        END;
    END IF;

    -- ── 3. Lock + read the source event row (FOR UPDATE); require EXISTS ────
    -- Static per-table branches — the table name is NEVER injected into dynamic
    -- SQL. Each branch reads (user_id, <marker jsonb col>) from the source row.
    IF v_src_table = 'risk_alerts' THEN
        SELECT r.user_id, r.metadata INTO v_src_user, v_json_col
          FROM risk_alerts r WHERE r.id = v_row_uuid FOR UPDATE;
    ELSIF v_src_table = 'paper_orders' THEN
        SELECT o.user_id, o.broker_response INTO v_src_user, v_json_col
          FROM paper_orders o WHERE o.id = v_row_uuid FOR UPDATE;
    ELSIF v_src_table = 'paper_ledger' THEN
        SELECT l.user_id, l.metadata INTO v_src_user, v_json_col
          FROM paper_ledger l WHERE l.id = v_row_uuid FOR UPDATE;
    END IF;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'issue_reconciliation_receipt: source_not_found (table=%, row=%)',
            v_src_table, v_src_row
            USING ERRCODE = 'no_data_found';
    END IF;

    -- ── 4a. User scope: the source event must belong to p_user_id ───────────
    IF v_src_user IS NULL OR v_src_user <> p_user_id THEN
        RAISE EXCEPTION
            'issue_reconciliation_receipt: source_user_mismatch (source row does '
            'not belong to the requesting user)'
            USING ERRCODE = 'check_violation';
    END IF;

    -- ── 4b. Typed, durable COMPLETED-reconciliation marker ──────────────────
    -- The producer stamps <source jsonb col>->'reconciliation_receipt' at
    -- reconciliation completion. Historical prose-only stamps have no such typed
    -- object -> RAISE (never fabricate a completion that is not durably present).
    v_marker := COALESCE(v_json_col, '{}'::jsonb) -> 'reconciliation_receipt';
    IF v_marker IS NULL OR jsonb_typeof(v_marker) <> 'object' THEN
        RAISE EXCEPTION
            'issue_reconciliation_receipt: source_not_a_completed_reconciliation '
            '(no typed reconciliation_receipt marker on the source row; a '
            'completed reconciliation must durably stamp {kind, status, '
            'content_fingerprint, effective_epoch})'
            USING ERRCODE = 'check_violation';
    END IF;

    v_m_kind  := btrim(COALESCE(v_marker->>'kind', ''));
    v_m_state := btrim(COALESCE(v_marker->>'status', ''));
    v_m_fp    := lower(btrim(COALESCE(v_marker->>'content_fingerprint', '')));
    v_m_epoch := btrim(COALESCE(v_marker->>'effective_epoch', ''));

    IF v_m_state <> 'completed' THEN
        RAISE EXCEPTION
            'issue_reconciliation_receipt: reconciliation_not_completed '
            '(marker status=%, need ''completed'')', v_m_state
            USING ERRCODE = 'check_violation';
    END IF;
    IF v_m_kind <> v_kind THEN
        RAISE EXCEPTION
            'issue_reconciliation_receipt: source_kind_mismatch (marker kind=%, '
            'requested kind=%)', v_m_kind, v_kind
            USING ERRCODE = 'check_violation';
    END IF;
    IF v_m_epoch <> v_epoch THEN
        RAISE EXCEPTION
            'issue_reconciliation_receipt: source_epoch_mismatch (marker epoch=%, '
            'requested epoch=%)', v_m_epoch, v_epoch
            USING ERRCODE = 'check_violation';
    END IF;

    -- ── 5. content_fingerprint must equal the durable source marker fp (full)
    IF char_length(v_m_fp) < 32 THEN
        RAISE EXCEPTION
            'issue_reconciliation_receipt: source_fingerprint_not_full (the source '
            'marker fingerprint is truncated <32; a display prefix cannot prove '
            'the reconciliation)'
            USING ERRCODE = 'check_violation';
    END IF;
    IF v_m_fp <> v_fp THEN
        RAISE EXCEPTION
            'issue_reconciliation_receipt: content_fingerprint_mismatch (requested '
            '% does not match the durable source marker %)', v_fp, v_m_fp
            USING ERRCODE = 'check_violation';
    END IF;

    -- Insert-time provenance columns (exactly one form; the other is NULL).
    IF v_has_alert THEN
        v_ins_alert := p_source_alert_id;
        v_ins_table := NULL;
        v_ins_row   := NULL;
    ELSE
        v_ins_alert := NULL;
        v_ins_table := v_src_table;
        v_ins_row   := v_src_row;
    END IF;

    -- ── 6/7/8. Idempotent create keyed on UNIQUE(receipt_kind, content_fp) ──
    -- (A) Source-alert single-use pre-check (partial UNIQUE(source_alert_id)):
    IF v_has_alert THEN
        SELECT * INTO v_existing
          FROM fleet_reconciliation_receipts
         WHERE source_alert_id = p_source_alert_id;
        IF FOUND THEN
            IF v_existing.receipt_kind = v_kind
               AND lower(v_existing.content_fingerprint) = v_fp
               AND v_existing.user_id = p_user_id
               AND v_existing.effective_epoch = v_epoch THEN
                RETURN jsonb_build_object(
                    'receipt_id', v_existing.receipt_id,
                    'user_id', v_existing.user_id,
                    'receipt_kind', v_existing.receipt_kind,
                    'content_fingerprint', v_existing.content_fingerprint,
                    'effective_epoch', v_existing.effective_epoch,
                    'source_alert_id', v_existing.source_alert_id,
                    'source_table', v_existing.source_table,
                    'source_row_id', v_existing.source_row_id,
                    'source_fingerprint', v_existing.source_fingerprint,
                    'created_at', v_existing.created_at,
                    'created_by', v_existing.created_by,
                    'idempotent_replay', true);
            END IF;
            RAISE EXCEPTION
                'issue_reconciliation_receipt: source_alert_already_receipted '
                '(this alert already backs a different receipt)'
                USING ERRCODE = 'unique_violation';
        END IF;
    END IF;

    -- (B) Natural-key existence (kind, content_fingerprint):
    SELECT * INTO v_existing
      FROM fleet_reconciliation_receipts
     WHERE receipt_kind = v_kind AND lower(content_fingerprint) = v_fp;
    IF FOUND THEN
        -- EXACT replay (same user + epoch + source) -> idempotent; else conflict.
        IF v_existing.user_id = p_user_id
           AND v_existing.effective_epoch = v_epoch
           AND v_existing.source_alert_id IS NOT DISTINCT FROM v_ins_alert
           AND COALESCE(v_existing.source_table, '') = COALESCE(v_ins_table, '')
           AND COALESCE(v_existing.source_row_id, '') = COALESCE(v_ins_row, '') THEN
            RETURN jsonb_build_object(
                'receipt_id', v_existing.receipt_id,
                'user_id', v_existing.user_id,
                'receipt_kind', v_existing.receipt_kind,
                'content_fingerprint', v_existing.content_fingerprint,
                'effective_epoch', v_existing.effective_epoch,
                'source_alert_id', v_existing.source_alert_id,
                'source_table', v_existing.source_table,
                'source_row_id', v_existing.source_row_id,
                'source_fingerprint', v_existing.source_fingerprint,
                'created_at', v_existing.created_at,
                'created_by', v_existing.created_by,
                'idempotent_replay', true);
        END IF;
        RAISE EXCEPTION
            'issue_reconciliation_receipt: receipt_conflict (a receipt for '
            'kind=% + this fingerprint already exists with a different '
            'user/epoch/source; not an exact replay)', v_kind
            USING ERRCODE = 'unique_violation';
    END IF;

    -- (C) Insert. ON CONFLICT (receipt_kind, content_fingerprint) DO NOTHING is
    -- the concurrency backstop; the wrapping handler catches any OTHER unique
    -- index (source_alert / source_ref) hit under a race and re-classifies.
    v_receipt_id := 'frr_' || replace(gen_random_uuid()::text, '-', '');
    BEGIN
        INSERT INTO fleet_reconciliation_receipts (
            receipt_id, user_id, receipt_kind, content_fingerprint,
            effective_epoch, source_alert_id, source_table, source_row_id,
            source_fingerprint, created_by
        ) VALUES (
            v_receipt_id, p_user_id, v_kind, v_fp, v_epoch,
            v_ins_alert, v_ins_table, v_ins_row,
            v_fp,               -- source_fingerprint == the proven durable token
            v_created_by
        )
        ON CONFLICT (receipt_kind, content_fingerprint) DO NOTHING
        RETURNING * INTO v_new;

        IF FOUND THEN
            RETURN jsonb_build_object(
                'receipt_id', v_new.receipt_id,
                'user_id', v_new.user_id,
                'receipt_kind', v_new.receipt_kind,
                'content_fingerprint', v_new.content_fingerprint,
                'effective_epoch', v_new.effective_epoch,
                'source_alert_id', v_new.source_alert_id,
                'source_table', v_new.source_table,
                'source_row_id', v_new.source_row_id,
                'source_fingerprint', v_new.source_fingerprint,
                'created_at', v_new.created_at,
                'created_by', v_new.created_by,
                'idempotent_replay', false);
        END IF;
    EXCEPTION WHEN unique_violation THEN
        -- A concurrent insert (or a source_alert/source_ref collision) blocked
        -- us; fall through to (D) to re-fetch and classify.
        NULL;
    END;

    -- (D) A concurrent writer won the (kind, fingerprint) key. Re-fetch and
    -- classify: exact replay -> idempotent; anything else -> conflict.
    SELECT * INTO v_existing
      FROM fleet_reconciliation_receipts
     WHERE receipt_kind = v_kind AND lower(content_fingerprint) = v_fp;
    IF FOUND
       AND v_existing.user_id = p_user_id
       AND v_existing.effective_epoch = v_epoch
       AND v_existing.source_alert_id IS NOT DISTINCT FROM v_ins_alert
       AND COALESCE(v_existing.source_table, '') = COALESCE(v_ins_table, '')
       AND COALESCE(v_existing.source_row_id, '') = COALESCE(v_ins_row, '') THEN
        RETURN jsonb_build_object(
            'receipt_id', v_existing.receipt_id,
            'user_id', v_existing.user_id,
            'receipt_kind', v_existing.receipt_kind,
            'content_fingerprint', v_existing.content_fingerprint,
            'effective_epoch', v_existing.effective_epoch,
            'source_alert_id', v_existing.source_alert_id,
            'source_table', v_existing.source_table,
            'source_row_id', v_existing.source_row_id,
            'source_fingerprint', v_existing.source_fingerprint,
            'created_at', v_existing.created_at,
            'created_by', v_existing.created_by,
            'idempotent_replay', true);
    END IF;

    RAISE EXCEPTION
        'issue_reconciliation_receipt: receipt_conflict (a concurrent receipt '
        'for kind=% + this fingerprint exists with a different user/epoch/source)',
        v_kind
        USING ERRCODE = 'unique_violation';
END;
$$;

COMMENT ON FUNCTION rpc_issue_fleet_reconciliation_receipt_v1(
    uuid, text, text, text, uuid, text, text, text) IS
    'Durable, immutable reconciliation-receipt WRITER (Lane A). Server-generates '
    'an opaque receipt_id (never caller-supplied), LOCKs the durable source event '
    'row FOR UPDATE, requires it to exist + belong to p_user_id + carry a typed '
    'completed-reconciliation marker (<source jsonb>->''reconciliation_receipt'' = '
    '{kind, status:completed, content_fingerprint:full, effective_epoch}) whose '
    'kind/epoch/full-fingerprint match the request, then inserts exactly ONE '
    'immutable receipt. job_runs is rejected as a source (no user_id column). '
    'EXACT replay returns the existing receipt with zero writes; a conflicting '
    'replay (same kind+fingerprint, different user/epoch/source) RAISEs '
    'receipt_conflict. No update/delete path; touches only '
    'fleet_reconciliation_receipts (INSERT) + the source table (SELECT FOR '
    'UPDATE). Makes NO activation/policy/fleet mutation. Returns a typed receipt '
    'for the activation attestation bundle. Operator-only (service_role).';

-- =============================================================================
-- Operator-only execution surface. Default EXECUTE is granted to PUBLIC for new
-- functions, so REVOKE first, then GRANT service_role only.
-- =============================================================================
REVOKE ALL ON FUNCTION rpc_issue_fleet_reconciliation_receipt_v1(
    uuid, text, text, text, uuid, text, text, text)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION rpc_issue_fleet_reconciliation_receipt_v1(
    uuid, text, text, text, uuid, text, text, text)
    TO service_role;
