-- Recurring shadow-fleet evaluator (C2): isolated internal-paper lifecycle.
--
-- Adds dedicated order/position/outcome/cash evidence and two atomic RPCs for
-- the multi-leg fleet. Structurally isolated from trade_suggestions, broker
-- orders, paper_* (the champion book), Policy-Lab learning, promotion, and every
-- live routing surface. Applying this migration creates NO fleet, portfolio,
-- binding, order, position, outcome, cash movement, or activation. Every write
-- path is gated (in-transaction) on the fleet being `active`, the micro-account
-- `active`, and the portfolio `shadow_only` — all false today, so the RPCs
-- reject every call.
--
-- Isolation choice (builder decision #1): the fleet gets its OWN fleet_shadow_*
-- tables (symmetry with single_leg_shadow_*), NOT tagged rows in the shared
-- paper_* champion book — so a fleet position can never contaminate the live
-- executor / funnel / monitor / learning that scan paper_positions (the
-- recurring shadow-contaminates-live class). The close RPC MIRRORS
-- rpc_commit_internal_close_v1's atomic guard structure (all-or-none,
-- server-derived cash, write-once, live-order isolation, non-finite guards)
-- against these isolated tables — honoring "never write close economics
-- sequentially" (V17-1) without depending on the champion tables.
--
-- Cash model (uniform, defined-risk collateral): at OPEN the account reserves
-- max_loss_total (the canonical defined-risk capital, the SAME basis C1's
-- capital_rejected uses); at EXPIRY it releases max_loss_total + realized_pnl.
-- realized_pnl = terminal_payoff_total - entry_net_cost_total. Net round-trip
-- cash change == realized_pnl for BOTH debit and credit defined-risk structures,
-- and the account can never over-deploy buying power.

BEGIN;

CREATE TABLE IF NOT EXISTS fleet_shadow_orders (
    order_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id uuid NOT NULL
        REFERENCES fleet_policy_decision_runs(run_id) ON DELETE RESTRICT,
    fleet_id uuid NOT NULL REFERENCES shadow_fleets(id) ON DELETE RESTRICT,
    fleet_epoch text NOT NULL CHECK (fleet_epoch = 'small_tier_v1'),
    shadow_micro_account_id uuid NOT NULL
        REFERENCES shadow_micro_accounts(id) ON DELETE RESTRICT,
    policy_registration_id text NOT NULL
        REFERENCES policy_registrations(policy_registration_id) ON DELETE RESTRICT,
    portfolio_id uuid NOT NULL REFERENCES paper_portfolios(id) ON DELETE RESTRICT,
    user_id uuid NOT NULL,
    candidate_suggestion_id uuid NOT NULL,
    underlying text NOT NULL CHECK (btrim(underlying) <> ''),
    legs jsonb NOT NULL CHECK (jsonb_typeof(legs) = 'array' AND jsonb_array_length(legs) >= 1),
    contracts integer NOT NULL CHECK (contracts >= 1),
    entry_net_cost_total numeric NOT NULL,
    max_loss_total numeric NOT NULL CHECK (max_loss_total > 0),
    expiry date NOT NULL,
    routing_mode text NOT NULL DEFAULT 'shadow_only' CHECK (routing_mode = 'shadow_only'),
    execution_mode text NOT NULL DEFAULT 'internal_paper' CHECK (execution_mode = 'internal_paper'),
    lifecycle_state text NOT NULL DEFAULT 'experimental' CHECK (lifecycle_state = 'experimental'),
    live_submit_allowed boolean NOT NULL DEFAULT false CHECK (live_submit_allowed = false),
    status text NOT NULL DEFAULT 'filled_internal' CHECK (status = 'filled_internal'),
    source_known_at timestamptz NOT NULL,
    filled_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, candidate_suggestion_id)
);

CREATE TABLE IF NOT EXISTS fleet_shadow_positions (
    position_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id uuid NOT NULL UNIQUE
        REFERENCES fleet_shadow_orders(order_id) ON DELETE RESTRICT,
    run_id uuid NOT NULL
        REFERENCES fleet_policy_decision_runs(run_id) ON DELETE RESTRICT,
    fleet_id uuid NOT NULL REFERENCES shadow_fleets(id) ON DELETE RESTRICT,
    fleet_epoch text NOT NULL CHECK (fleet_epoch = 'small_tier_v1'),
    shadow_micro_account_id uuid NOT NULL
        REFERENCES shadow_micro_accounts(id) ON DELETE RESTRICT,
    policy_registration_id text NOT NULL
        REFERENCES policy_registrations(policy_registration_id) ON DELETE RESTRICT,
    portfolio_id uuid NOT NULL REFERENCES paper_portfolios(id) ON DELETE RESTRICT,
    user_id uuid NOT NULL,
    candidate_suggestion_id uuid NOT NULL,
    underlying text NOT NULL CHECK (btrim(underlying) <> ''),
    legs jsonb NOT NULL CHECK (jsonb_typeof(legs) = 'array' AND jsonb_array_length(legs) >= 1),
    contracts integer NOT NULL CHECK (contracts >= 1),
    entry_net_cost_total numeric NOT NULL,
    max_loss_total numeric NOT NULL CHECK (max_loss_total > 0),
    expiry date NOT NULL,
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    routing_mode text NOT NULL DEFAULT 'shadow_only' CHECK (routing_mode = 'shadow_only'),
    execution_mode text NOT NULL DEFAULT 'internal_paper' CHECK (execution_mode = 'internal_paper'),
    lifecycle_state text NOT NULL DEFAULT 'experimental' CHECK (lifecycle_state = 'experimental'),
    live_submit_allowed boolean NOT NULL DEFAULT false CHECK (live_submit_allowed = false),
    opened_at timestamptz NOT NULL DEFAULT now(),
    closed_at timestamptz,
    terminal_spot numeric,
    terminal_payoff_total numeric,
    realized_pnl numeric,
    close_reason text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, candidate_suggestion_id),
    CHECK (
        (status = 'open' AND closed_at IS NULL AND terminal_spot IS NULL
         AND terminal_payoff_total IS NULL AND realized_pnl IS NULL AND close_reason IS NULL)
        OR
        (status = 'closed' AND closed_at IS NOT NULL AND terminal_spot IS NOT NULL
         AND terminal_payoff_total IS NOT NULL AND realized_pnl IS NOT NULL
         AND btrim(close_reason) <> '')
    )
);

CREATE TABLE IF NOT EXISTS fleet_shadow_outcomes (
    outcome_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    position_id uuid NOT NULL UNIQUE
        REFERENCES fleet_shadow_positions(position_id) ON DELETE RESTRICT,
    run_id uuid NOT NULL
        REFERENCES fleet_policy_decision_runs(run_id) ON DELETE RESTRICT,
    fleet_id uuid NOT NULL REFERENCES shadow_fleets(id) ON DELETE RESTRICT,
    shadow_micro_account_id uuid NOT NULL
        REFERENCES shadow_micro_accounts(id) ON DELETE RESTRICT,
    policy_registration_id text NOT NULL
        REFERENCES policy_registrations(policy_registration_id) ON DELETE RESTRICT,
    portfolio_id uuid NOT NULL REFERENCES paper_portfolios(id) ON DELETE RESTRICT,
    user_id uuid NOT NULL,
    candidate_suggestion_id uuid NOT NULL,
    underlying text NOT NULL,
    opened_at timestamptz NOT NULL,
    closed_at timestamptz NOT NULL,
    entry_net_cost_total numeric NOT NULL,
    max_loss_total numeric NOT NULL CHECK (max_loss_total > 0),
    terminal_payoff_total numeric NOT NULL,
    realized_pnl numeric NOT NULL,
    close_reason text NOT NULL CHECK (btrim(close_reason) <> ''),
    execution_mode text NOT NULL DEFAULT 'internal_paper' CHECK (execution_mode = 'internal_paper'),
    experiment text NOT NULL DEFAULT 'fleet_shadow' CHECK (experiment = 'fleet_shadow'),
    is_paper boolean NOT NULL DEFAULT true CHECK (is_paper = true),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS fleet_shadow_cash_events (
    cash_event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id uuid NOT NULL REFERENCES paper_portfolios(id) ON DELETE RESTRICT,
    policy_registration_id text NOT NULL
        REFERENCES policy_registrations(policy_registration_id) ON DELETE RESTRICT,
    shadow_micro_account_id uuid NOT NULL
        REFERENCES shadow_micro_accounts(id) ON DELETE RESTRICT,
    user_id uuid NOT NULL,
    order_id uuid REFERENCES fleet_shadow_orders(order_id) ON DELETE RESTRICT,
    position_id uuid REFERENCES fleet_shadow_positions(position_id) ON DELETE RESTRICT,
    event_type text NOT NULL CHECK (event_type IN ('entry_reservation', 'expiry_settlement')),
    amount numeric NOT NULL,
    balance_before numeric NOT NULL,
    balance_after numeric NOT NULL,
    idempotency_key text NOT NULL UNIQUE CHECK (btrim(idempotency_key) <> ''),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (
        (event_type = 'entry_reservation' AND order_id IS NOT NULL AND amount <= 0)
        OR
        (event_type = 'expiry_settlement' AND position_id IS NOT NULL)
    ),
    CHECK (balance_after = balance_before + amount)
);

CREATE INDEX IF NOT EXISTS idx_fleet_shadow_positions_open_expiry
    ON fleet_shadow_positions (expiry, user_id) WHERE status = 'open';
CREATE INDEX IF NOT EXISTS idx_fleet_shadow_positions_micro_open
    ON fleet_shadow_positions (shadow_micro_account_id) WHERE status = 'open';
CREATE INDEX IF NOT EXISTS idx_fleet_shadow_orders_policy_date
    ON fleet_shadow_orders (policy_registration_id, filled_at DESC);
CREATE INDEX IF NOT EXISTS idx_fleet_shadow_outcomes_policy_date
    ON fleet_shadow_outcomes (policy_registration_id, closed_at DESC);
CREATE INDEX IF NOT EXISTS idx_fleet_shadow_cash_portfolio_date
    ON fleet_shadow_cash_events (portfolio_id, created_at DESC);

-- Append-only orders / outcomes / cash; open->closed-only positions.
CREATE OR REPLACE FUNCTION fleet_shadow_append_only_guard()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END;
$$;

DROP TRIGGER IF EXISTS trg_fleet_shadow_orders_append_only ON fleet_shadow_orders;
CREATE TRIGGER trg_fleet_shadow_orders_append_only
    BEFORE UPDATE OR DELETE ON fleet_shadow_orders
    FOR EACH ROW EXECUTE FUNCTION fleet_shadow_append_only_guard();

DROP TRIGGER IF EXISTS trg_fleet_shadow_outcomes_append_only ON fleet_shadow_outcomes;
CREATE TRIGGER trg_fleet_shadow_outcomes_append_only
    BEFORE UPDATE OR DELETE ON fleet_shadow_outcomes
    FOR EACH ROW EXECUTE FUNCTION fleet_shadow_append_only_guard();

DROP TRIGGER IF EXISTS trg_fleet_shadow_cash_append_only ON fleet_shadow_cash_events;
CREATE TRIGGER trg_fleet_shadow_cash_append_only
    BEFORE UPDATE OR DELETE ON fleet_shadow_cash_events
    FOR EACH ROW EXECUTE FUNCTION fleet_shadow_append_only_guard();

CREATE OR REPLACE FUNCTION fleet_shadow_position_transition_guard()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'fleet_shadow_positions is not deletable'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.position_id IS DISTINCT FROM NEW.position_id
       OR OLD.order_id IS DISTINCT FROM NEW.order_id
       OR OLD.run_id IS DISTINCT FROM NEW.run_id
       OR OLD.shadow_micro_account_id IS DISTINCT FROM NEW.shadow_micro_account_id
       OR OLD.policy_registration_id IS DISTINCT FROM NEW.policy_registration_id
       OR OLD.portfolio_id IS DISTINCT FROM NEW.portfolio_id
       OR OLD.user_id IS DISTINCT FROM NEW.user_id
       OR OLD.candidate_suggestion_id IS DISTINCT FROM NEW.candidate_suggestion_id
       OR OLD.legs IS DISTINCT FROM NEW.legs
       OR OLD.contracts IS DISTINCT FROM NEW.contracts
       OR OLD.entry_net_cost_total IS DISTINCT FROM NEW.entry_net_cost_total
       OR OLD.max_loss_total IS DISTINCT FROM NEW.max_loss_total
       OR OLD.expiry IS DISTINCT FROM NEW.expiry
       OR OLD.opened_at IS DISTINCT FROM NEW.opened_at THEN
        RAISE EXCEPTION 'fleet_shadow_positions identity/economics are immutable'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.status = 'closed' THEN
        RAISE EXCEPTION 'closed fleet shadow position is immutable'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NOT (OLD.status = 'open' AND NEW.status = 'closed') THEN
        RAISE EXCEPTION 'only open -> closed transition is allowed'
            USING ERRCODE = 'restrict_violation';
    END IF;
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_fleet_shadow_position_transition ON fleet_shadow_positions;
CREATE TRIGGER trg_fleet_shadow_position_transition
    BEFORE UPDATE OR DELETE ON fleet_shadow_positions
    FOR EACH ROW EXECUTE FUNCTION fleet_shadow_position_transition_guard();

-- ── Shared leg validation: a legs array must be finite, typed, non-empty ─────
CREATE OR REPLACE FUNCTION fleet_shadow_validate_legs(p_legs jsonb)
RETURNS void
LANGUAGE plpgsql
IMMUTABLE
SET search_path = public, pg_temp
AS $$
DECLARE
    v_leg jsonb;
    v_ot text;
    v_strike numeric;
    v_sign int;
    v_lc int;
BEGIN
    IF p_legs IS NULL OR jsonb_typeof(p_legs) <> 'array'
       OR jsonb_array_length(p_legs) < 1 THEN
        RAISE EXCEPTION 'fleet_shadow: legs must be a non-empty array'
            USING ERRCODE = 'check_violation';
    END IF;
    FOR v_leg IN SELECT * FROM jsonb_array_elements(p_legs) LOOP
        v_ot := v_leg->>'option_type';
        v_strike := (v_leg->>'strike')::numeric;
        v_sign := (v_leg->>'sign')::int;
        v_lc := (v_leg->>'contracts')::int;
        IF v_ot NOT IN ('call', 'put') THEN
            RAISE EXCEPTION 'fleet_shadow: leg option_type must be call/put (got %)', v_ot
                USING ERRCODE = 'check_violation';
        END IF;
        IF v_strike IS NULL OR v_strike <= 0
           OR v_strike::text IN ('NaN','Infinity','-Infinity') THEN
            RAISE EXCEPTION 'fleet_shadow: leg strike invalid' USING ERRCODE = 'check_violation';
        END IF;
        IF v_sign NOT IN (1, -1) THEN
            RAISE EXCEPTION 'fleet_shadow: leg sign must be +/-1' USING ERRCODE = 'check_violation';
        END IF;
        IF v_lc IS NULL OR v_lc < 1 THEN
            RAISE EXCEPTION 'fleet_shadow: leg contracts must be >= 1' USING ERRCODE = 'check_violation';
        END IF;
    END LOOP;
END;
$$;

-- ── OPEN: atomic multi-leg internal fill with defined-risk reservation ───────
CREATE OR REPLACE FUNCTION rpc_open_fleet_shadow_position_v1(
    p_run_id uuid,
    p_shadow_micro_account_id uuid,
    p_policy_registration_id text,
    p_portfolio_id uuid,
    p_user_id uuid,
    p_candidate_suggestion_id uuid,
    p_underlying text,
    p_legs jsonb,
    p_contracts integer,
    p_entry_net_cost_total numeric,
    p_max_loss_total numeric,
    p_expiry date,
    p_source_known_at timestamptz,
    p_filled_at timestamptz DEFAULT now()
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_existing fleet_shadow_orders%ROWTYPE;
    v_micro shadow_micro_accounts%ROWTYPE;
    v_portfolio paper_portfolios%ROWTYPE;
    v_position_id uuid;
    v_order_id uuid;
    v_before numeric;
    v_after numeric;
BEGIN
    -- non-finite / domain guards (H9): reject before any lock or write.
    IF p_entry_net_cost_total IS NULL
       OR p_entry_net_cost_total::text IN ('NaN','Infinity','-Infinity') THEN
        RAISE EXCEPTION 'fleet open: entry_net_cost non-finite' USING ERRCODE = 'check_violation';
    END IF;
    IF p_max_loss_total IS NULL OR p_max_loss_total <= 0
       OR p_max_loss_total::text IN ('NaN','Infinity','-Infinity') THEN
        RAISE EXCEPTION 'fleet open: max_loss_total invalid' USING ERRCODE = 'check_violation';
    END IF;
    IF p_contracts IS NULL OR p_contracts < 1 THEN
        RAISE EXCEPTION 'fleet open: contracts must be >= 1' USING ERRCODE = 'check_violation';
    END IF;
    PERFORM fleet_shadow_validate_legs(p_legs);

    -- Idempotent replay: same (run, candidate) already filled.
    SELECT * INTO v_existing FROM fleet_shadow_orders
     WHERE run_id = p_run_id AND candidate_suggestion_id = p_candidate_suggestion_id;
    IF FOUND THEN
        SELECT position_id INTO v_position_id FROM fleet_shadow_positions
         WHERE order_id = v_existing.order_id;
        RETURN jsonb_build_object(
            'status', 'filled_internal', 'idempotent_replay', true,
            'order_id', v_existing.order_id, 'position_id', v_position_id,
            'reserved', v_existing.max_loss_total);
    END IF;

    -- The candidate must be a SELECTED fleet decision for THIS micro-account
    -- (identity anchor; never trade a rejected/absent candidate).
    PERFORM 1 FROM fleet_policy_decisions d
     WHERE d.decision_event_id = p_candidate_suggestion_id
       AND d.candidate_suggestion_id = p_candidate_suggestion_id
       AND d.shadow_micro_account_id = p_shadow_micro_account_id
       AND d.policy_registration_id = p_policy_registration_id
       AND d.disposition = 'selected';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'fleet open: no selected decision for candidate/micro-account'
            USING ERRCODE = 'restrict_violation';
    END IF;

    -- Micro-account must be ACTIVE + bound to this policy/portfolio, and its
    -- fleet must be ACTIVE. All false while inactive -> reject.
    SELECT m.* INTO v_micro FROM shadow_micro_accounts m
      JOIN shadow_fleets f ON f.id = m.fleet_id
     WHERE m.id = p_shadow_micro_account_id
       AND m.state = 'active'
       AND m.policy_registration_id = p_policy_registration_id
       AND m.portfolio_id = p_portfolio_id
       AND f.status = 'active'
       AND f.epoch_name = 'small_tier_v1'
     FOR UPDATE OF m;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'fleet open: micro-account/fleet not active or unbound'
            USING ERRCODE = 'restrict_violation';
    END IF;

    -- Portfolio must be shadow-only with enough cash to RESERVE the defined risk.
    SELECT * INTO v_portfolio FROM paper_portfolios
     WHERE id = p_portfolio_id AND user_id = p_user_id AND routing_mode = 'shadow_only'
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'fleet open: shadow-only portfolio missing'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF v_portfolio.cash_balance < p_max_loss_total THEN
        RAISE EXCEPTION 'fleet open: insufficient portfolio cash to reserve defined risk'
            USING ERRCODE = 'insufficient_funds';
    END IF;

    v_before := v_portfolio.cash_balance;
    v_after := v_before - p_max_loss_total;

    INSERT INTO fleet_shadow_orders (
        run_id, fleet_id, fleet_epoch, shadow_micro_account_id, policy_registration_id,
        portfolio_id, user_id, candidate_suggestion_id, underlying, legs, contracts,
        entry_net_cost_total, max_loss_total, expiry, source_known_at, filled_at
    ) VALUES (
        p_run_id, v_micro.fleet_id, 'small_tier_v1', p_shadow_micro_account_id,
        p_policy_registration_id, p_portfolio_id, p_user_id, p_candidate_suggestion_id,
        p_underlying, p_legs, p_contracts, round(p_entry_net_cost_total, 2),
        round(p_max_loss_total, 2), p_expiry, p_source_known_at, p_filled_at
    ) RETURNING order_id INTO v_order_id;

    INSERT INTO fleet_shadow_positions (
        order_id, run_id, fleet_id, fleet_epoch, shadow_micro_account_id,
        policy_registration_id, portfolio_id, user_id, candidate_suggestion_id,
        underlying, legs, contracts, entry_net_cost_total, max_loss_total, expiry, opened_at
    ) VALUES (
        v_order_id, p_run_id, v_micro.fleet_id, 'small_tier_v1', p_shadow_micro_account_id,
        p_policy_registration_id, p_portfolio_id, p_user_id, p_candidate_suggestion_id,
        p_underlying, p_legs, p_contracts, round(p_entry_net_cost_total, 2),
        round(p_max_loss_total, 2), p_expiry, p_filled_at
    ) RETURNING position_id INTO v_position_id;

    -- production paper_portfolios has NO updated_at column
    -- (id,user_id,name,cash_balance,net_liq,created_at,routing_mode).
    UPDATE paper_portfolios SET cash_balance = v_after
     WHERE id = p_portfolio_id;

    INSERT INTO fleet_shadow_cash_events (
        portfolio_id, policy_registration_id, shadow_micro_account_id, user_id,
        order_id, position_id, event_type, amount, balance_before, balance_after,
        idempotency_key
    ) VALUES (
        p_portfolio_id, p_policy_registration_id, p_shadow_micro_account_id, p_user_id,
        v_order_id, v_position_id, 'entry_reservation', -round(p_max_loss_total, 2),
        v_before, v_after, 'fleet_entry:' || v_order_id::text
    );

    RETURN jsonb_build_object(
        'status', 'filled_internal', 'idempotent_replay', false,
        'order_id', v_order_id, 'position_id', v_position_id,
        'reserved', round(p_max_loss_total, 2), 'cash_balance_after', v_after);
END;
$$;

-- ── CLOSE (expiry): atomic multi-leg terminal payoff + collateral release ────
CREATE OR REPLACE FUNCTION rpc_close_fleet_shadow_position_v1(
    p_position_id uuid,
    p_terminal_spot numeric,
    p_closed_at timestamptz DEFAULT now(),
    p_close_reason text DEFAULT 'expiry'
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_position fleet_shadow_positions%ROWTYPE;
    v_portfolio paper_portfolios%ROWTYPE;
    v_outcome fleet_shadow_outcomes%ROWTYPE;
    v_leg jsonb;
    v_ot text;
    v_strike numeric;
    v_sign int;
    v_lc int;
    v_intrinsic numeric;
    v_payoff numeric := 0;
    v_pnl numeric;
    v_release numeric;
    v_before numeric;
    v_after numeric;
    v_outcome_id uuid;
BEGIN
    IF p_terminal_spot IS NULL OR p_terminal_spot < 0
       OR p_terminal_spot::text IN ('NaN','Infinity','-Infinity') THEN
        RAISE EXCEPTION 'fleet close: invalid terminal spot' USING ERRCODE = 'check_violation';
    END IF;
    IF p_close_reason <> 'expiry' THEN
        RAISE EXCEPTION 'fleet close: only expiry settlement is supported in v1'
            USING ERRCODE = 'check_violation';
    END IF;

    SELECT * INTO v_position FROM fleet_shadow_positions
     WHERE position_id = p_position_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'fleet close: position not found' USING ERRCODE = 'no_data_found';
    END IF;

    IF v_position.status = 'closed' THEN
        SELECT * INTO v_outcome FROM fleet_shadow_outcomes WHERE position_id = p_position_id;
        RETURN jsonb_build_object(
            'status', 'closed', 'idempotent_replay', true, 'position_id', p_position_id,
            'outcome_id', v_outcome.outcome_id, 'terminal_payoff_total', v_outcome.terminal_payoff_total,
            'realized_pnl', v_outcome.realized_pnl);
    END IF;
    IF p_closed_at::date < v_position.expiry THEN
        RAISE EXCEPTION 'fleet close: cannot settle before expiry' USING ERRCODE = 'restrict_violation';
    END IF;

    -- Exact multi-leg terminal payoff from the STORED signed legs (immutable
    -- position identity). Malformed legs -> reject, never fabricate (H9 / §10).
    PERFORM fleet_shadow_validate_legs(v_position.legs);
    FOR v_leg IN SELECT * FROM jsonb_array_elements(v_position.legs) LOOP
        v_ot := v_leg->>'option_type';
        v_strike := (v_leg->>'strike')::numeric;
        v_sign := (v_leg->>'sign')::int;
        v_lc := (v_leg->>'contracts')::int;
        IF v_ot = 'call' THEN
            v_intrinsic := greatest(p_terminal_spot - v_strike, 0);
        ELSE
            v_intrinsic := greatest(v_strike - p_terminal_spot, 0);
        END IF;
        v_payoff := v_payoff + (v_sign * v_intrinsic * v_lc * 100);
    END LOOP;
    v_payoff := round(v_payoff, 2);
    v_pnl := round(v_payoff - v_position.entry_net_cost_total, 2);
    v_release := round(v_position.max_loss_total + v_pnl, 2);

    SELECT * INTO v_portfolio FROM paper_portfolios
     WHERE id = v_position.portfolio_id AND user_id = v_position.user_id
       AND routing_mode = 'shadow_only' FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'fleet close: shadow-only portfolio missing' USING ERRCODE = 'restrict_violation';
    END IF;

    v_before := v_portfolio.cash_balance;
    v_after := v_before + v_release;

    UPDATE fleet_shadow_positions SET
        status = 'closed', closed_at = p_closed_at, terminal_spot = p_terminal_spot,
        terminal_payoff_total = v_payoff, realized_pnl = v_pnl, close_reason = p_close_reason
     WHERE position_id = p_position_id AND status = 'open';

    -- production paper_portfolios has NO updated_at column (see open RPC note).
    UPDATE paper_portfolios SET
        cash_balance = v_after, net_liq = net_liq + v_pnl
     WHERE id = v_position.portfolio_id;

    INSERT INTO fleet_shadow_outcomes (
        position_id, run_id, fleet_id, shadow_micro_account_id, policy_registration_id,
        portfolio_id, user_id, candidate_suggestion_id, underlying, opened_at, closed_at,
        entry_net_cost_total, max_loss_total, terminal_payoff_total, realized_pnl, close_reason
    ) VALUES (
        p_position_id, v_position.run_id, v_position.fleet_id, v_position.shadow_micro_account_id,
        v_position.policy_registration_id, v_position.portfolio_id, v_position.user_id,
        v_position.candidate_suggestion_id, v_position.underlying, v_position.opened_at, p_closed_at,
        v_position.entry_net_cost_total, v_position.max_loss_total, v_payoff, v_pnl, p_close_reason
    ) RETURNING outcome_id INTO v_outcome_id;

    INSERT INTO fleet_shadow_cash_events (
        portfolio_id, policy_registration_id, shadow_micro_account_id, user_id,
        position_id, event_type, amount, balance_before, balance_after, idempotency_key
    ) VALUES (
        v_position.portfolio_id, v_position.policy_registration_id,
        v_position.shadow_micro_account_id, v_position.user_id, p_position_id,
        'expiry_settlement', v_release, v_before, v_after,
        'fleet_expiry:' || p_position_id::text
    );

    RETURN jsonb_build_object(
        'status', 'closed', 'idempotent_replay', false, 'position_id', p_position_id,
        'outcome_id', v_outcome_id, 'terminal_payoff_total', v_payoff,
        'realized_pnl', v_pnl, 'cash_balance_after', v_after);
END;
$$;

ALTER TABLE fleet_shadow_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE fleet_shadow_positions ENABLE ROW LEVEL SECURITY;
ALTER TABLE fleet_shadow_outcomes ENABLE ROW LEVEL SECURITY;
ALTER TABLE fleet_shadow_cash_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role read fleet_shadow_orders"
    ON fleet_shadow_orders FOR SELECT USING (auth.role() = 'service_role');
CREATE POLICY "Service role read fleet_shadow_positions"
    ON fleet_shadow_positions FOR SELECT USING (auth.role() = 'service_role');
CREATE POLICY "Service role read fleet_shadow_outcomes"
    ON fleet_shadow_outcomes FOR SELECT USING (auth.role() = 'service_role');
CREATE POLICY "Service role read fleet_shadow_cash_events"
    ON fleet_shadow_cash_events FOR SELECT USING (auth.role() = 'service_role');

REVOKE ALL ON fleet_shadow_orders FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON fleet_shadow_positions FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON fleet_shadow_outcomes FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON fleet_shadow_cash_events FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON fleet_shadow_orders TO service_role;
GRANT SELECT ON fleet_shadow_positions TO service_role;
GRANT SELECT ON fleet_shadow_outcomes TO service_role;
GRANT SELECT ON fleet_shadow_cash_events TO service_role;

REVOKE ALL ON FUNCTION rpc_open_fleet_shadow_position_v1(
    uuid,uuid,text,uuid,uuid,uuid,text,jsonb,integer,numeric,numeric,date,timestamptz,timestamptz
) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION rpc_close_fleet_shadow_position_v1(
    uuid,numeric,timestamptz,text
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION rpc_open_fleet_shadow_position_v1(
    uuid,uuid,text,uuid,uuid,uuid,text,jsonb,integer,numeric,numeric,date,timestamptz,timestamptz
) TO service_role;
GRANT EXECUTE ON FUNCTION rpc_close_fleet_shadow_position_v1(
    uuid,numeric,timestamptz,text
) TO service_role;

COMMENT ON TABLE fleet_shadow_orders IS
    'Internal-paper multi-leg fills for selected fleet candidates; no broker order exists.';
COMMENT ON TABLE fleet_shadow_positions IS
    'Multi-leg fleet shadow positions, isolated from the champion trading book and live learning.';
COMMENT ON FUNCTION rpc_open_fleet_shadow_position_v1 IS
    'Atomic multi-leg shadow-only internal fill: validates selected-decision identity, fleet/micro active, shadow-only routing, reserves the defined-risk collateral, never calls a broker.';
COMMENT ON FUNCTION rpc_close_fleet_shadow_position_v1 IS
    'Atomic expiry settlement: exact multi-leg intrinsic terminal payoff from the stored signed legs, releases collateral + realized P&L, all-or-none, write-once idempotent.';

COMMIT;
NOTIFY pgrst, 'reload schema';
