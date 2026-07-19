-- =============================================================================
-- V17-1  F-A2-INTERNAL-CLOSE-PRECOMMIT-SIDE-EFFECTS  (Lane 1A foundation)
-- rpc_commit_internal_close_v1 — atomic economic commit for an INTERNAL close
-- =============================================================================
-- NOT APPLIED BY THIS PR (draft). This file ships the server-side atomic DDL
-- foundation ONLY. Lane 1B (a separate, later lane) switches the internal
-- close route (paper_exit_evaluator._close_position, the internal-fill block)
-- to call this function instead of the current NON-atomic sequence of writes.
-- Applied only via the operator-owned migration procedure
-- (docs/migration_procedure.md).
--
-- WHY THIS EXISTS
-- The internal / shadow close route today writes, in order:
--     1. paper_orders  status='filled'          (paper_exit_evaluator.py:2463)
--     2. paper_portfolios cash_balance += delta (:2487)
--     3. paper_ledger  fill event               (:2493, via PaperLedgerService)
--   ...and ONLY THEN runs
--     4. compute_realized_pl validation         (:2537)
--     5. _map_close_reason mapping              (:2558)
--     6. close_position_shared CAS close        (:2573)
-- supabase-py has no client-side transaction, so a raise / CAS race between
-- steps 1-3 and step 6 orphans a filled order, a cash delta, and a ledger
-- event against a position that never closed — or double-books a racing close.
-- This function performs the ENTIRE economic commit inside ONE plpgsql body =
-- ONE implicit transaction: all-or-none. Any RAISE rolls back every write.
--
-- CONTRACT (each numbered point maps to a labelled section below)
--   1. required idempotency key + identifying inputs.
--   2. lock position -> order -> portfolio (fixed order) to avoid deadlock.
--   3. verify user/portfolio/position/order ownership + linkage.
--   4. position must be OPEN with nonzero quantity.
--   5. verify the order has NOT been economically committed (write-once marker).
--   6. verify side, filled qty, close reason, fill source, POSITIVE magnitude.
--   7. derive cash DIRECTION + DELTA server-side from LOCKED truth (never a
--      client balance_after — there is no such parameter).
--   8. atomically: order filled + commit marker; portfolio cash; ONE fill
--      ledger event (dup-guarded); position closed (qty=0, realized_pl,...).
--   9. return ONE typed jsonb receipt.
--  10. exact replay of the same committed (order,key) -> idempotent no-op.
--  11. conflicting replay (same order, different key; or a second close against
--      an already-closed position) -> typed reject.
--  12. any error rolls back every write (no dblink / autonomous sub-txn).
--
-- SECURITY: operator-only. EXECUTE revoked from PUBLIC/anon/authenticated,
-- granted to service_role. Fixed safe search_path. No dynamic SQL.
--
-- IDEMPOTENCY / UNIQUENESS CHOICE (documented for the reviewers)
-- The write-once commit marker lives on paper_orders as two ADDITIVE, NULLABLE
-- columns: internal_close_committed_at + internal_close_commit_key. Primary
-- enforcement of "an order commits at most once" is the per-order FOR UPDATE
-- lock + the marker check inside the transaction (point 5). In ADDITION we add
-- a PARTIAL UNIQUE index on internal_close_commit_key WHERE it IS NOT NULL, as
-- defense-in-depth against a globally-reused key committing two DIFFERENT
-- orders. That schema constraint is safe to add because the columns are brand
-- new: a read-only preflight (2026-07-19) confirmed the columns are absent and
-- all 528 existing paper_orders rows therefore carry NULL, so the partial
-- index indexes ZERO legacy rows and cannot fail to build. (Had legacy rows
-- carried values that might violate, we would instead have enforced uniqueness
-- only under the transaction lock, with no schema constraint.)
-- =============================================================================

-- ── Marker columns: additive, nullable, safe default NULL (uncommitted) ──────
ALTER TABLE paper_orders
    ADD COLUMN IF NOT EXISTS internal_close_committed_at timestamptz,
    ADD COLUMN IF NOT EXISTS internal_close_commit_key   text;

COMMENT ON COLUMN paper_orders.internal_close_committed_at IS
    'Write-once marker: the timestamp at which rpc_commit_internal_close_v1 '
    'economically committed this close order. NULL = not yet committed. Set '
    'exactly once inside the atomic commit; never mutated afterwards.';
COMMENT ON COLUMN paper_orders.internal_close_commit_key IS
    'Write-once idempotency key that committed this close order (paired with '
    'internal_close_committed_at). A replay with the same key is an idempotent '
    'no-op; a replay with a different key is a typed conflict.';

-- Defense-in-depth uniqueness (safe: brand-new column, all legacy rows NULL).
CREATE UNIQUE INDEX IF NOT EXISTS ux_paper_orders_internal_close_commit_key
    ON paper_orders (internal_close_commit_key)
    WHERE internal_close_commit_key IS NOT NULL;

-- =============================================================================
-- rpc_commit_internal_close_v1
-- =============================================================================
CREATE OR REPLACE FUNCTION rpc_commit_internal_close_v1(
    p_user_id              uuid,      -- (1) identifying inputs
    p_portfolio_id         uuid,
    p_position_id          uuid,
    p_close_order_id       uuid,
    p_idempotency_key      text,      -- (1) REQUIRED idempotency key
    p_close_reason         text,      -- mapped close_reason (9-value enum)
    p_fill_source          text,      -- fill_source (4-value enum)
    p_close_side           text,      -- 'buy' | 'sell' (verified vs position)
    p_fill_qty             numeric,   -- absolute contracts (== |position.qty|)
    p_fill_price_magnitude numeric,   -- POSITIVE per-contract executable price
    p_realized_pl          numeric,   -- computed upstream (close_math); required
    p_multiplier           numeric DEFAULT 100
)
RETURNS jsonb
LANGUAGE plpgsql
SET search_path = public, pg_temp         -- (SECURITY) fixed, safe; no dynamic SQL
AS $$
DECLARE
    v_position      paper_positions%ROWTYPE;
    v_order         paper_orders%ROWTYPE;
    v_portfolio     paper_portfolios%ROWTYPE;
    v_expected_side text;
    v_sign          integer;              -- +1 sell/credit (long close), -1 buy/debit (short close)
    v_abs_qty       numeric;
    v_cash_delta    numeric;
    v_new_cash      numeric;
    v_ledger_id     uuid;
    v_existing_fill integer;
    v_now           timestamptz;
    v_closed        integer;
BEGIN
    -- ── (1) required scalar inputs — typed reject, NOTHING written ───────────
    IF p_user_id IS NULL OR p_portfolio_id IS NULL OR p_position_id IS NULL
       OR p_close_order_id IS NULL THEN
        RAISE EXCEPTION 'commit_internal_close: identifying_ids_required';
    END IF;
    IF p_idempotency_key IS NULL OR btrim(p_idempotency_key) = '' THEN
        RAISE EXCEPTION 'commit_internal_close: idempotency_key_required';
    END IF;
    IF p_close_reason IS NULL OR p_fill_source IS NULL OR p_close_side IS NULL THEN
        RAISE EXCEPTION 'commit_internal_close: reason_source_side_required';
    END IF;
    IF p_fill_qty IS NULL OR p_fill_price_magnitude IS NULL
       OR p_multiplier IS NULL THEN
        RAISE EXCEPTION 'commit_internal_close: fill_inputs_required';
    END IF;
    -- realized_pl is REQUIRED (close_path_required CHECK + the whole point of
    -- moving validation BEFORE the writes). A NULL here is the RPC-boundary
    -- equivalent of the upstream realized-P&L computation failing.
    IF p_realized_pl IS NULL THEN
        RAISE EXCEPTION 'commit_internal_close: realized_pl_required';
    END IF;

    -- ── (6a) enum / domain validation (before any lock or write) ─────────────
    IF p_close_reason NOT IN (
        'target_profit_hit','stop_loss_hit','dte_threshold','expiration_day',
        'manual_close_user_initiated','alpaca_fill_reconciler_sign_corrected',
        'alpaca_fill_reconciler_standard','envelope_force_close','orphan_fill_repair'
    ) THEN
        RAISE EXCEPTION 'commit_internal_close: invalid_close_reason (%)', p_close_reason;
    END IF;
    IF p_fill_source NOT IN (
        'alpaca_fill_reconciler','orphan_fill_repair','exit_evaluator','manual_endpoint'
    ) THEN
        RAISE EXCEPTION 'commit_internal_close: invalid_fill_source (%)', p_fill_source;
    END IF;
    IF p_close_side NOT IN ('buy','sell') THEN
        RAISE EXCEPTION 'commit_internal_close: invalid_close_side (%)', p_close_side;
    END IF;
    -- POSITIVE fill magnitude: a broker fill price is always positive; the
    -- signed mark is normalized to magnitude + structural direction upstream
    -- (F-CREDIT-SIGN). A non-positive magnitude means an unpriceable/garbage
    -- fill — reject rather than fabricate (H9 both ends).
    IF p_fill_price_magnitude <= 0 THEN
        RAISE EXCEPTION 'commit_internal_close: nonpositive_fill_magnitude (%)', p_fill_price_magnitude;
    END IF;
    IF p_fill_qty <= 0 THEN
        RAISE EXCEPTION 'commit_internal_close: nonpositive_fill_qty (%)', p_fill_qty;
    END IF;
    IF p_multiplier <= 0 THEN
        RAISE EXCEPTION 'commit_internal_close: nonpositive_multiplier (%)', p_multiplier;
    END IF;

    -- ── (2) LOCK in a fixed order: position -> order -> portfolio ────────────
    -- Every caller of this function acquires these row locks in this order, so
    -- two concurrent commits can never deadlock (they queue on the first lock).
    SELECT * INTO v_position FROM paper_positions
        WHERE id = p_position_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'commit_internal_close: position_not_found (%)', p_position_id;
    END IF;

    SELECT * INTO v_order FROM paper_orders
        WHERE id = p_close_order_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'commit_internal_close: close_order_not_found (%)', p_close_order_id;
    END IF;

    SELECT * INTO v_portfolio FROM paper_portfolios
        WHERE id = p_portfolio_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'commit_internal_close: portfolio_not_found (%)', p_portfolio_id;
    END IF;

    -- ── (3) ownership + linkage: every id must belong to the same user and be
    --        wired to each other. A NULL order.position_id fails here (closes
    --        carry a position_id by construction). ────────────────────────────
    IF v_position.user_id <> p_user_id OR v_position.portfolio_id <> p_portfolio_id THEN
        RAISE EXCEPTION 'commit_internal_close: position_ownership_mismatch';
    END IF;
    IF v_order.user_id <> p_user_id OR v_order.portfolio_id <> p_portfolio_id THEN
        RAISE EXCEPTION 'commit_internal_close: order_ownership_mismatch';
    END IF;
    IF v_order.position_id IS DISTINCT FROM p_position_id THEN
        RAISE EXCEPTION 'commit_internal_close: order_position_linkage_mismatch';
    END IF;
    IF v_portfolio.user_id <> p_user_id THEN
        RAISE EXCEPTION 'commit_internal_close: portfolio_ownership_mismatch';
    END IF;

    -- ── (5)/(10)/(11) commit-marker idempotency — BEFORE any mutation ────────
    -- The order is "economically committed" iff internal_close_committed_at is
    -- set. This is the immutable, write-once marker point 5 checks.
    IF v_order.internal_close_committed_at IS NOT NULL THEN
        IF v_order.internal_close_commit_key IS NOT DISTINCT FROM p_idempotency_key THEN
            -- (10) EXACT replay of the same committed (order,key): idempotent
            -- no-op. Reconstruct the receipt from durable truth; ZERO writes.
            SELECT id INTO v_ledger_id FROM paper_ledger
                WHERE order_id = p_close_order_id AND event_type = 'fill'
                ORDER BY created_at ASC LIMIT 1;
            RETURN jsonb_build_object(
                'committed', true,
                'idempotent_replay', true,
                'order_id', p_close_order_id,
                'position_id', p_position_id,
                'cash_after', v_portfolio.cash_balance,
                'ledger_event_id', v_ledger_id,
                'realized_pl', v_position.realized_pl
            );
        END IF;
        -- (11) same order, DIFFERENT key -> conflicting replay.
        RAISE EXCEPTION
            'commit_internal_close: idempotency_conflict — order % already committed with a different key',
            p_close_order_id;
    END IF;

    -- ── (4)/(11) position must be OPEN with nonzero quantity ─────────────────
    -- A 'closed' status here is the CAS-race loser: another close already won
    -- (this is the exact orphan/double-book race the function eliminates).
    IF v_position.status = 'closed' THEN
        RAISE EXCEPTION
            'commit_internal_close: position_already_closed % (existing reason=%, source=%)',
            p_position_id, v_position.close_reason, v_position.fill_source;
    END IF;
    IF v_position.status IS DISTINCT FROM 'open' THEN
        RAISE EXCEPTION 'commit_internal_close: position_not_open (status=%)', v_position.status;
    END IF;
    IF v_position.quantity = 0 THEN
        RAISE EXCEPTION 'commit_internal_close: position_zero_quantity';
    END IF;

    -- ── (7) cash DIRECTION derived from the LOCKED position sign (server
    --        truth). Long (qty>0) closes by SELL -> cash IN (+). Short (qty<0)
    --        closes by BUY -> cash OUT (-). The client side is only VERIFIED
    --        against this, never trusted to set direction. ────────────────────
    v_abs_qty := abs(v_position.quantity);
    IF v_position.quantity > 0 THEN
        v_expected_side := 'sell';
        v_sign := 1;
    ELSE
        v_expected_side := 'buy';
        v_sign := -1;
    END IF;

    -- ── (6b) verify the client side + qty agree with the locked truth ────────
    IF p_close_side <> v_expected_side THEN
        RAISE EXCEPTION
            'commit_internal_close: side_mismatch (client=%, position_implied=%)',
            p_close_side, v_expected_side;
    END IF;
    IF p_fill_qty <> v_abs_qty THEN
        RAISE EXCEPTION
            'commit_internal_close: fill_qty_mismatch (client=%, position=%)',
            p_fill_qty, v_abs_qty;
    END IF;

    -- ── (7 cont.) cash DELTA + new balance, both from LOCKED truth ───────────
    -- Uses the locked position quantity (server) and locked portfolio cash
    -- (server). No client-supplied balance_after exists to trust.
    v_cash_delta := v_sign * p_fill_price_magnitude * v_abs_qty * p_multiplier;
    v_new_cash   := v_portfolio.cash_balance + v_cash_delta;

    -- ── (8a) duplicate-ledger guard under the lock ───────────────────────────
    -- The marker guarantees at-most-once, but assert the fill ledger invariant
    -- explicitly: no prior 'fill' event may exist for this order.
    SELECT count(*) INTO v_existing_fill FROM paper_ledger
        WHERE order_id = p_close_order_id AND event_type = 'fill';
    IF v_existing_fill > 0 THEN
        RAISE EXCEPTION
            'commit_internal_close: duplicate_fill_ledger (% rows) for order %',
            v_existing_fill, p_close_order_id;
    END IF;

    v_now := now();

    -- ── (8b) mark the order filled + set the WRITE-ONCE commit marker ────────
    -- Broker/live provenance columns (execution_mode, alpaca_order_id,
    -- broker_status, broker_response, routing) are deliberately UNTOUCHED — this
    -- is an internal-close economic commit only.
    UPDATE paper_orders SET
        status                       = 'filled',
        filled_qty                   = v_abs_qty,
        avg_fill_price               = round(p_fill_price_magnitude, 2),
        fees_usd                     = 0,
        side                         = p_close_side,
        submitted_at                 = COALESCE(submitted_at, v_now),
        filled_at                    = v_now,
        internal_close_committed_at  = v_now,
        internal_close_commit_key    = p_idempotency_key
    WHERE id = p_close_order_id;

    -- ── (8c) portfolio cash (server-derived new balance) ─────────────────────
    UPDATE paper_portfolios SET cash_balance = v_new_cash
        WHERE id = p_portfolio_id;

    -- ── (8d) exactly ONE linked fill ledger event ────────────────────────────
    INSERT INTO paper_ledger (
        user_id, portfolio_id, order_id, position_id, event_type,
        amount, balance_after, description, trace_id, metadata, created_at
    ) VALUES (
        p_user_id, p_portfolio_id, p_close_order_id, p_position_id, 'fill',
        v_cash_delta, v_new_cash,
        format('%s %s %s @ $%s (internal close)',
               upper(p_close_side), v_abs_qty, v_position.symbol,
               round(p_fill_price_magnitude, 4)),
        v_position.trace_id::text,
        jsonb_build_object(
            'side', p_close_side,
            'qty', v_abs_qty,
            'price', p_fill_price_magnitude,
            'symbol', v_position.symbol,
            'fees', 0,
            'source', p_fill_source,
            'reason', p_close_reason,
            'commit', 'rpc_commit_internal_close_v1',
            'idempotency_key', p_idempotency_key
        ),
        v_now
    )
    RETURNING id INTO v_ledger_id;

    -- ── (8e) close the position (qty=0, realized_pl, reason, source, closed_at)
    -- CAS belt-and-suspenders: AND status='open'. We already hold FOR UPDATE
    -- and checked status, so this always affects 1 row; if it ever affects 0,
    -- something raced under the lock — RAISE and roll the whole txn back.
    UPDATE paper_positions SET
        status      = 'closed',
        quantity    = 0,
        realized_pl = p_realized_pl,
        close_reason = p_close_reason,
        fill_source = p_fill_source,
        closed_at   = v_now,
        updated_at  = v_now
    WHERE id = p_position_id AND status = 'open';
    GET DIAGNOSTICS v_closed = ROW_COUNT;
    IF v_closed <> 1 THEN
        RAISE EXCEPTION 'commit_internal_close: position_close_cas_failed (% rows)', v_closed;
    END IF;

    -- ── (9) typed receipt ────────────────────────────────────────────────────
    RETURN jsonb_build_object(
        'committed', true,
        'idempotent_replay', false,
        'order_id', p_close_order_id,
        'position_id', p_position_id,
        'cash_after', v_new_cash,
        'ledger_event_id', v_ledger_id,
        'realized_pl', p_realized_pl
    );
    -- (12) No EXCEPTION handler is used: this single function body is one
    -- implicit transaction, so any RAISE above rolls back EVERY write. No
    -- dblink / pg_background / autonomous sub-transaction escapes the rollback.
END;
$$;

COMMENT ON FUNCTION rpc_commit_internal_close_v1(
    uuid, uuid, uuid, uuid, text, text, text, text, numeric, numeric, numeric, numeric
) IS
    'Atomically commits an INTERNAL (paper/shadow/fallback) close: marks the '
    'close order filled with a write-once commit marker, moves portfolio cash '
    '(direction+delta derived server-side from the locked position sign, never '
    'a client balance_after), inserts exactly one linked fill ledger event, and '
    'closes the position — all-or-none in one transaction. Idempotent on '
    '(order, key); a conflicting key or a second close against an already-closed '
    'position is a typed reject. Operator-only (service_role). Foundation for '
    'V17-1 F-A2; the Python route is switched to call it in Lane 1B.';

-- =============================================================================
-- Operator-only execution surface
-- =============================================================================
REVOKE ALL ON FUNCTION rpc_commit_internal_close_v1(
    uuid, uuid, uuid, uuid, text, text, text, text, numeric, numeric, numeric, numeric
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION rpc_commit_internal_close_v1(
    uuid, uuid, uuid, uuid, text, text, text, text, numeric, numeric, numeric, numeric
) TO service_role;
