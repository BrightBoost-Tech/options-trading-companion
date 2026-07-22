-- One-contract single-leg shadow experiment: internal-paper lifecycle.
--
-- Adds dedicated order/position/outcome/cash evidence and two atomic RPCs.
-- The lifecycle is structurally isolated from trade_suggestions, broker orders,
-- Policy Lab learning, fleet activation, and every live routing surface.
-- Applying this migration creates NO policy, portfolio, binding, order, position,
-- outcome, cash movement, or experiment activation.

BEGIN;

CREATE TABLE IF NOT EXISTS single_leg_shadow_orders (
    order_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id uuid NOT NULL REFERENCES single_leg_shadow_runs(run_id) ON DELETE RESTRICT,
    attempt_id uuid NOT NULL REFERENCES single_leg_shadow_attempts(attempt_id) ON DELETE RESTRICT,
    policy_registration_id text NOT NULL
        REFERENCES policy_registrations(policy_registration_id) ON DELETE RESTRICT,
    portfolio_id uuid NOT NULL REFERENCES paper_portfolios(id) ON DELETE RESTRICT,
    user_id uuid NOT NULL,
    candidate_fingerprint text NOT NULL CHECK (btrim(candidate_fingerprint) <> ''),
    symbol text NOT NULL CHECK (btrim(symbol) <> ''),
    occ_symbol text NOT NULL CHECK (btrim(occ_symbol) <> ''),
    option_type text NOT NULL CHECK (option_type IN ('call', 'put')),
    strategy_type text NOT NULL CHECK (strategy_type IN ('long_call', 'long_put')),
    side text NOT NULL DEFAULT 'buy' CHECK (side = 'buy'),
    contracts integer NOT NULL DEFAULT 1 CHECK (contracts = 1),
    fill_price_per_share numeric NOT NULL CHECK (fill_price_per_share > 0),
    debit_total numeric NOT NULL CHECK (debit_total > 0),
    source_known_at timestamptz NOT NULL,
    routing_mode text NOT NULL DEFAULT 'shadow_only' CHECK (routing_mode = 'shadow_only'),
    execution_mode text NOT NULL DEFAULT 'internal_paper' CHECK (execution_mode = 'internal_paper'),
    lifecycle_state text NOT NULL DEFAULT 'experimental' CHECK (lifecycle_state = 'experimental'),
    live_submit_allowed boolean NOT NULL DEFAULT false CHECK (live_submit_allowed = false),
    status text NOT NULL DEFAULT 'filled_internal' CHECK (status = 'filled_internal'),
    filled_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, candidate_fingerprint),
    UNIQUE (attempt_id)
);

CREATE TABLE IF NOT EXISTS single_leg_shadow_positions (
    position_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id uuid NOT NULL UNIQUE
        REFERENCES single_leg_shadow_orders(order_id) ON DELETE RESTRICT,
    run_id uuid NOT NULL REFERENCES single_leg_shadow_runs(run_id) ON DELETE RESTRICT,
    policy_registration_id text NOT NULL
        REFERENCES policy_registrations(policy_registration_id) ON DELETE RESTRICT,
    portfolio_id uuid NOT NULL REFERENCES paper_portfolios(id) ON DELETE RESTRICT,
    user_id uuid NOT NULL,
    candidate_fingerprint text NOT NULL CHECK (btrim(candidate_fingerprint) <> ''),
    symbol text NOT NULL CHECK (btrim(symbol) <> ''),
    occ_symbol text NOT NULL CHECK (btrim(occ_symbol) <> ''),
    option_type text NOT NULL CHECK (option_type IN ('call', 'put')),
    strategy_type text NOT NULL CHECK (strategy_type IN ('long_call', 'long_put')),
    strike numeric NOT NULL CHECK (strike > 0),
    expiry date NOT NULL,
    contracts integer NOT NULL DEFAULT 1 CHECK (contracts = 1),
    entry_price_per_share numeric NOT NULL CHECK (entry_price_per_share > 0),
    entry_debit_total numeric NOT NULL CHECK (entry_debit_total > 0),
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    routing_mode text NOT NULL DEFAULT 'shadow_only' CHECK (routing_mode = 'shadow_only'),
    execution_mode text NOT NULL DEFAULT 'internal_paper' CHECK (execution_mode = 'internal_paper'),
    lifecycle_state text NOT NULL DEFAULT 'experimental' CHECK (lifecycle_state = 'experimental'),
    live_submit_allowed boolean NOT NULL DEFAULT false CHECK (live_submit_allowed = false),
    opened_at timestamptz NOT NULL DEFAULT now(),
    closed_at timestamptz,
    terminal_spot numeric,
    terminal_value numeric,
    realized_pnl numeric,
    close_reason text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, candidate_fingerprint),
    CHECK (
        (status = 'open' AND closed_at IS NULL AND terminal_value IS NULL
         AND realized_pnl IS NULL AND close_reason IS NULL)
        OR
        (status = 'closed' AND closed_at IS NOT NULL AND terminal_spot IS NOT NULL
         AND terminal_value IS NOT NULL AND realized_pnl IS NOT NULL
         AND btrim(close_reason) <> '')
    )
);

CREATE TABLE IF NOT EXISTS single_leg_shadow_outcomes (
    outcome_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    position_id uuid NOT NULL UNIQUE
        REFERENCES single_leg_shadow_positions(position_id) ON DELETE RESTRICT,
    run_id uuid NOT NULL REFERENCES single_leg_shadow_runs(run_id) ON DELETE RESTRICT,
    policy_registration_id text NOT NULL
        REFERENCES policy_registrations(policy_registration_id) ON DELETE RESTRICT,
    portfolio_id uuid NOT NULL REFERENCES paper_portfolios(id) ON DELETE RESTRICT,
    user_id uuid NOT NULL,
    candidate_fingerprint text NOT NULL CHECK (btrim(candidate_fingerprint) <> ''),
    symbol text NOT NULL CHECK (btrim(symbol) <> ''),
    strategy_type text NOT NULL CHECK (strategy_type IN ('long_call', 'long_put')),
    opened_at timestamptz NOT NULL,
    closed_at timestamptz NOT NULL,
    entry_debit_total numeric NOT NULL CHECK (entry_debit_total > 0),
    terminal_value numeric NOT NULL CHECK (terminal_value >= 0),
    realized_pnl numeric NOT NULL,
    close_reason text NOT NULL CHECK (btrim(close_reason) <> ''),
    execution_mode text NOT NULL DEFAULT 'internal_paper' CHECK (execution_mode = 'internal_paper'),
    experiment text NOT NULL DEFAULT 'single_leg' CHECK (experiment = 'single_leg'),
    is_paper boolean NOT NULL DEFAULT true CHECK (is_paper = true),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS single_leg_shadow_cash_events (
    cash_event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id uuid NOT NULL REFERENCES paper_portfolios(id) ON DELETE RESTRICT,
    policy_registration_id text NOT NULL
        REFERENCES policy_registrations(policy_registration_id) ON DELETE RESTRICT,
    user_id uuid NOT NULL,
    order_id uuid REFERENCES single_leg_shadow_orders(order_id) ON DELETE RESTRICT,
    position_id uuid REFERENCES single_leg_shadow_positions(position_id) ON DELETE RESTRICT,
    event_type text NOT NULL CHECK (event_type IN ('entry_debit', 'expiry_settlement')),
    amount numeric NOT NULL,
    balance_before numeric NOT NULL,
    balance_after numeric NOT NULL,
    idempotency_key text NOT NULL UNIQUE CHECK (btrim(idempotency_key) <> ''),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (
        (event_type = 'entry_debit' AND order_id IS NOT NULL AND amount < 0)
        OR
        (event_type = 'expiry_settlement' AND position_id IS NOT NULL AND amount >= 0)
    ),
    CHECK (balance_after = balance_before + amount)
);

CREATE INDEX IF NOT EXISTS idx_single_leg_shadow_positions_open_expiry
    ON single_leg_shadow_positions (expiry, user_id)
    WHERE status = 'open';
CREATE INDEX IF NOT EXISTS idx_single_leg_shadow_orders_policy_date
    ON single_leg_shadow_orders (policy_registration_id, filled_at DESC);
CREATE INDEX IF NOT EXISTS idx_single_leg_shadow_outcomes_policy_date
    ON single_leg_shadow_outcomes (policy_registration_id, closed_at DESC);
CREATE INDEX IF NOT EXISTS idx_single_leg_shadow_cash_portfolio_date
    ON single_leg_shadow_cash_events (portfolio_id, created_at DESC);

-- The foundation event taxonomy gains one honest post-open unavailable state.
ALTER TABLE single_leg_shadow_lifecycle_events
    DROP CONSTRAINT IF EXISTS single_leg_shadow_lifecycle_events_event_type_check;
ALTER TABLE single_leg_shadow_lifecycle_events
    ADD CONSTRAINT single_leg_shadow_lifecycle_events_event_type_check
    CHECK (event_type IN (
        'candidate_generated',
        'candidate_persisted',
        'execution_rejected',
        'order_created',
        'filled_internal',
        'position_opened',
        'settlement_deferred',
        'position_closed',
        'outcome_recorded'
    ));

CREATE OR REPLACE FUNCTION single_leg_shadow_append_only_guard()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END;
$$;

DROP TRIGGER IF EXISTS trg_single_leg_orders_append_only ON single_leg_shadow_orders;
CREATE TRIGGER trg_single_leg_orders_append_only
    BEFORE UPDATE OR DELETE ON single_leg_shadow_orders
    FOR EACH ROW EXECUTE FUNCTION single_leg_shadow_append_only_guard();

DROP TRIGGER IF EXISTS trg_single_leg_outcomes_append_only ON single_leg_shadow_outcomes;
CREATE TRIGGER trg_single_leg_outcomes_append_only
    BEFORE UPDATE OR DELETE ON single_leg_shadow_outcomes
    FOR EACH ROW EXECUTE FUNCTION single_leg_shadow_append_only_guard();

DROP TRIGGER IF EXISTS trg_single_leg_cash_append_only ON single_leg_shadow_cash_events;
CREATE TRIGGER trg_single_leg_cash_append_only
    BEFORE UPDATE OR DELETE ON single_leg_shadow_cash_events
    FOR EACH ROW EXECUTE FUNCTION single_leg_shadow_append_only_guard();

CREATE OR REPLACE FUNCTION single_leg_shadow_position_transition_guard()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
    IF OLD.position_id IS DISTINCT FROM NEW.position_id
       OR OLD.order_id IS DISTINCT FROM NEW.order_id
       OR OLD.run_id IS DISTINCT FROM NEW.run_id
       OR OLD.policy_registration_id IS DISTINCT FROM NEW.policy_registration_id
       OR OLD.portfolio_id IS DISTINCT FROM NEW.portfolio_id
       OR OLD.user_id IS DISTINCT FROM NEW.user_id
       OR OLD.candidate_fingerprint IS DISTINCT FROM NEW.candidate_fingerprint
       OR OLD.symbol IS DISTINCT FROM NEW.symbol
       OR OLD.occ_symbol IS DISTINCT FROM NEW.occ_symbol
       OR OLD.option_type IS DISTINCT FROM NEW.option_type
       OR OLD.strategy_type IS DISTINCT FROM NEW.strategy_type
       OR OLD.strike IS DISTINCT FROM NEW.strike
       OR OLD.expiry IS DISTINCT FROM NEW.expiry
       OR OLD.contracts IS DISTINCT FROM NEW.contracts
       OR OLD.entry_price_per_share IS DISTINCT FROM NEW.entry_price_per_share
       OR OLD.entry_debit_total IS DISTINCT FROM NEW.entry_debit_total
       OR OLD.routing_mode IS DISTINCT FROM NEW.routing_mode
       OR OLD.execution_mode IS DISTINCT FROM NEW.execution_mode
       OR OLD.lifecycle_state IS DISTINCT FROM NEW.lifecycle_state
       OR OLD.live_submit_allowed IS DISTINCT FROM NEW.live_submit_allowed
       OR OLD.opened_at IS DISTINCT FROM NEW.opened_at THEN
        RAISE EXCEPTION 'single_leg_shadow_positions identity/economics are immutable'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.status = 'closed' THEN
        RAISE EXCEPTION 'closed single-leg shadow position is immutable'
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

DROP TRIGGER IF EXISTS trg_single_leg_position_transition ON single_leg_shadow_positions;
CREATE TRIGGER trg_single_leg_position_transition
    BEFORE UPDATE ON single_leg_shadow_positions
    FOR EACH ROW EXECUTE FUNCTION single_leg_shadow_position_transition_guard();

CREATE OR REPLACE FUNCTION rpc_open_single_leg_shadow_position_v1(
    p_run_id uuid,
    p_policy_registration_id text,
    p_portfolio_id uuid,
    p_user_id uuid,
    p_candidate_fingerprint text,
    p_symbol text,
    p_occ_symbol text,
    p_option_type text,
    p_strategy_type text,
    p_strike numeric,
    p_expiry date,
    p_fill_price_per_share numeric,
    p_source_known_at timestamptz,
    p_filled_at timestamptz DEFAULT now()
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_run single_leg_shadow_runs%ROWTYPE;
    v_attempt single_leg_shadow_attempts%ROWTYPE;
    v_portfolio paper_portfolios%ROWTYPE;
    v_policy policy_registrations%ROWTYPE;
    v_existing single_leg_shadow_orders%ROWTYPE;
    v_order_id uuid;
    v_position_id uuid;
    v_debit numeric;
    v_before numeric;
    v_after numeric;
    v_max_debit numeric := 150;
    v_max_text text;
BEGIN
    IF p_fill_price_per_share IS NULL
       OR p_fill_price_per_share <= 0
       OR p_fill_price_per_share::text IN ('NaN', 'Infinity', '-Infinity') THEN
        RAISE EXCEPTION 'invalid fill_price_per_share' USING ERRCODE = 'check_violation';
    END IF;
    IF p_strike IS NULL OR p_strike <= 0
       OR p_strike::text IN ('NaN', 'Infinity', '-Infinity') THEN
        RAISE EXCEPTION 'invalid strike' USING ERRCODE = 'check_violation';
    END IF;
    IF p_option_type NOT IN ('call', 'put')
       OR p_strategy_type <> ('long_' || p_option_type) THEN
        RAISE EXCEPTION 'single-leg option/strategy mismatch' USING ERRCODE = 'check_violation';
    END IF;

    SELECT * INTO v_existing
      FROM single_leg_shadow_orders
     WHERE run_id = p_run_id
       AND candidate_fingerprint = p_candidate_fingerprint;
    IF FOUND THEN
        SELECT position_id INTO v_position_id
          FROM single_leg_shadow_positions
         WHERE order_id = v_existing.order_id;
        RETURN jsonb_build_object(
            'status', 'filled_internal',
            'idempotent_replay', true,
            'order_id', v_existing.order_id,
            'position_id', v_position_id,
            'debit_total', v_existing.debit_total
        );
    END IF;

    SELECT * INTO v_run
      FROM single_leg_shadow_runs
     WHERE run_id = p_run_id
       AND policy_registration_id = p_policy_registration_id
       AND portfolio_id = p_portfolio_id
       AND user_id = p_user_id
       AND policy_epoch = 'single_leg_experiment_v1'
       AND status IN ('running', 'succeeded', 'partial')
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'single-leg run identity/state invalid' USING ERRCODE = 'restrict_violation';
    END IF;

    SELECT * INTO v_attempt
      FROM single_leg_shadow_attempts
     WHERE run_id = p_run_id
       AND policy_registration_id = p_policy_registration_id
       AND candidate_fingerprint = p_candidate_fingerprint
       AND symbol = p_symbol
       AND stage = 'candidate_generated';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'candidate_generated evidence missing' USING ERRCODE = 'restrict_violation';
    END IF;
    IF v_attempt.occ_symbol IS DISTINCT FROM p_occ_symbol
       OR v_attempt.strike IS DISTINCT FROM p_strike
       OR v_attempt.expiry IS DISTINCT FROM p_expiry
       OR v_attempt.strategy_type IS DISTINCT FROM p_strategy_type THEN
        RAISE EXCEPTION 'candidate execution identity mismatch' USING ERRCODE = 'restrict_violation';
    END IF;

    PERFORM 1
      FROM single_leg_experiment_bindings b
      JOIN single_leg_experiment_epochs e ON e.epoch_name = b.epoch_name
     WHERE b.policy_registration_id = p_policy_registration_id
       AND b.portfolio_id = p_portfolio_id
       AND b.user_id = p_user_id
       AND b.role = 'experimental'
       AND b.enabled
       AND b.routing_mode = 'shadow_only'
       AND b.execution_mode = 'internal_paper'
       AND e.epoch_name = 'single_leg_experiment_v1'
       AND e.state = 'enabled'
       AND e.routing_mode = 'shadow_only'
       AND e.max_contracts = 1
       AND e.live_submit_allowed = false;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'single-leg experiment binding/epoch is not enabled'
            USING ERRCODE = 'restrict_violation';
    END IF;

    SELECT * INTO v_policy
      FROM policy_registrations
     WHERE policy_registration_id = p_policy_registration_id
       AND effective_epoch = 'single_leg_experiment_v1'
       AND approval_status = 'approved'
       AND lower(coalesce(policy_config->>'single_leg_experiment_enabled', 'false'))
           IN ('true', '1', 'yes', 'on');
    IF NOT FOUND THEN
        RAISE EXCEPTION 'approved single-leg opt-in policy missing'
            USING ERRCODE = 'restrict_violation';
    END IF;
    v_max_text := v_policy.policy_config->>'single_leg_max_debit_per_contract';
    IF v_max_text ~ '^[0-9]+([.][0-9]+)?$' THEN
        v_max_debit := v_max_text::numeric;
    END IF;

    v_debit := round(p_fill_price_per_share * 100, 2);
    IF v_debit <= 0 OR v_debit > v_max_debit THEN
        RAISE EXCEPTION 'execution debit % exceeds policy cap %', v_debit, v_max_debit
            USING ERRCODE = 'check_violation';
    END IF;

    SELECT * INTO v_portfolio
      FROM paper_portfolios
     WHERE id = p_portfolio_id
       AND user_id = p_user_id
       AND routing_mode = 'shadow_only'
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'shadow-only experiment portfolio missing'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF v_portfolio.cash_balance < v_debit THEN
        RAISE EXCEPTION 'insufficient experimental portfolio cash'
            USING ERRCODE = 'insufficient_funds';
    END IF;

    v_before := v_portfolio.cash_balance;
    v_after := v_before - v_debit;

    INSERT INTO single_leg_shadow_orders (
        run_id, attempt_id, policy_registration_id, portfolio_id, user_id,
        candidate_fingerprint, symbol, occ_symbol, option_type, strategy_type,
        fill_price_per_share, debit_total, source_known_at, filled_at
    ) VALUES (
        p_run_id, v_attempt.attempt_id, p_policy_registration_id, p_portfolio_id,
        p_user_id, p_candidate_fingerprint, p_symbol, p_occ_symbol, p_option_type,
        p_strategy_type, p_fill_price_per_share, v_debit, p_source_known_at,
        p_filled_at
    ) RETURNING order_id INTO v_order_id;

    INSERT INTO single_leg_shadow_positions (
        order_id, run_id, policy_registration_id, portfolio_id, user_id,
        candidate_fingerprint, symbol, occ_symbol, option_type, strategy_type,
        strike, expiry, entry_price_per_share, entry_debit_total, opened_at
    ) VALUES (
        v_order_id, p_run_id, p_policy_registration_id, p_portfolio_id, p_user_id,
        p_candidate_fingerprint, p_symbol, p_occ_symbol, p_option_type,
        p_strategy_type, p_strike, p_expiry, p_fill_price_per_share, v_debit,
        p_filled_at
    ) RETURNING position_id INTO v_position_id;

    UPDATE paper_portfolios
       SET cash_balance = v_after,
           updated_at = now()
     WHERE id = p_portfolio_id;

    INSERT INTO single_leg_shadow_cash_events (
        portfolio_id, policy_registration_id, user_id, order_id, position_id,
        event_type, amount, balance_before, balance_after, idempotency_key
    ) VALUES (
        p_portfolio_id, p_policy_registration_id, p_user_id, v_order_id,
        v_position_id, 'entry_debit', -v_debit, v_before, v_after,
        'single_leg_entry:' || v_order_id::text
    );

    INSERT INTO single_leg_shadow_lifecycle_events (
        run_id, policy_registration_id, user_id, event_type, entity_type,
        entity_id, candidate_fingerprint, payload, occurred_at
    ) VALUES
        (p_run_id, p_policy_registration_id, p_user_id, 'order_created',
         'order', v_order_id::text, p_candidate_fingerprint,
         jsonb_build_object('execution_mode','internal_paper','broker_called',false),
         p_filled_at),
        (p_run_id, p_policy_registration_id, p_user_id, 'filled_internal',
         'order', v_order_id::text, p_candidate_fingerprint,
         jsonb_build_object('fill_price_per_share',p_fill_price_per_share,
                            'debit_total',v_debit,'contracts',1), p_filled_at),
        (p_run_id, p_policy_registration_id, p_user_id, 'position_opened',
         'position', v_position_id::text, p_candidate_fingerprint,
         jsonb_build_object('order_id',v_order_id,'expiry',p_expiry), p_filled_at)
    ON CONFLICT DO NOTHING;

    RETURN jsonb_build_object(
        'status', 'filled_internal',
        'idempotent_replay', false,
        'order_id', v_order_id,
        'position_id', v_position_id,
        'debit_total', v_debit,
        'cash_balance_after', v_after
    );
END;
$$;

CREATE OR REPLACE FUNCTION rpc_close_single_leg_shadow_position_v1(
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
    v_position single_leg_shadow_positions%ROWTYPE;
    v_portfolio paper_portfolios%ROWTYPE;
    v_outcome single_leg_shadow_outcomes%ROWTYPE;
    v_terminal numeric;
    v_pnl numeric;
    v_before numeric;
    v_after numeric;
    v_outcome_id uuid;
BEGIN
    IF p_terminal_spot IS NULL OR p_terminal_spot < 0
       OR p_terminal_spot::text IN ('NaN', 'Infinity', '-Infinity') THEN
        RAISE EXCEPTION 'invalid terminal spot' USING ERRCODE = 'check_violation';
    END IF;
    IF p_close_reason <> 'expiry' THEN
        RAISE EXCEPTION 'only expiry settlement is supported in v1'
            USING ERRCODE = 'check_violation';
    END IF;

    SELECT * INTO v_position
      FROM single_leg_shadow_positions
     WHERE position_id = p_position_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'single-leg shadow position not found' USING ERRCODE = 'no_data_found';
    END IF;

    IF v_position.status = 'closed' THEN
        SELECT * INTO v_outcome
          FROM single_leg_shadow_outcomes
         WHERE position_id = p_position_id;
        RETURN jsonb_build_object(
            'status', 'closed',
            'idempotent_replay', true,
            'position_id', p_position_id,
            'outcome_id', v_outcome.outcome_id,
            'terminal_value', v_outcome.terminal_value,
            'realized_pnl', v_outcome.realized_pnl
        );
    END IF;
    IF p_closed_at::date < v_position.expiry THEN
        RAISE EXCEPTION 'position cannot settle before expiry'
            USING ERRCODE = 'restrict_violation';
    END IF;

    IF v_position.option_type = 'call' THEN
        v_terminal := greatest(p_terminal_spot - v_position.strike, 0) * 100;
    ELSE
        v_terminal := greatest(v_position.strike - p_terminal_spot, 0) * 100;
    END IF;
    v_terminal := round(v_terminal, 2);
    v_pnl := v_terminal - v_position.entry_debit_total;

    SELECT * INTO v_portfolio
      FROM paper_portfolios
     WHERE id = v_position.portfolio_id
       AND user_id = v_position.user_id
       AND routing_mode = 'shadow_only'
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'shadow-only experiment portfolio missing'
            USING ERRCODE = 'restrict_violation';
    END IF;

    v_before := v_portfolio.cash_balance;
    v_after := v_before + v_terminal;

    UPDATE single_leg_shadow_positions
       SET status = 'closed',
           closed_at = p_closed_at,
           terminal_spot = p_terminal_spot,
           terminal_value = v_terminal,
           realized_pnl = v_pnl,
           close_reason = p_close_reason
     WHERE position_id = p_position_id;

    UPDATE paper_portfolios
       SET cash_balance = v_after,
           net_liq = net_liq + v_pnl,
           updated_at = now()
     WHERE id = v_position.portfolio_id;

    INSERT INTO single_leg_shadow_outcomes (
        position_id, run_id, policy_registration_id, portfolio_id, user_id,
        candidate_fingerprint, symbol, strategy_type, opened_at, closed_at,
        entry_debit_total, terminal_value, realized_pnl, close_reason
    ) VALUES (
        p_position_id, v_position.run_id, v_position.policy_registration_id,
        v_position.portfolio_id, v_position.user_id,
        v_position.candidate_fingerprint, v_position.symbol,
        v_position.strategy_type, v_position.opened_at, p_closed_at,
        v_position.entry_debit_total, v_terminal, v_pnl, p_close_reason
    ) RETURNING outcome_id INTO v_outcome_id;

    INSERT INTO single_leg_shadow_cash_events (
        portfolio_id, policy_registration_id, user_id, position_id,
        event_type, amount, balance_before, balance_after, idempotency_key
    ) VALUES (
        v_position.portfolio_id, v_position.policy_registration_id,
        v_position.user_id, p_position_id, 'expiry_settlement', v_terminal,
        v_before, v_after, 'single_leg_expiry:' || p_position_id::text
    );

    INSERT INTO single_leg_shadow_lifecycle_events (
        run_id, policy_registration_id, user_id, event_type, entity_type,
        entity_id, candidate_fingerprint, payload, occurred_at
    ) VALUES
        (v_position.run_id, v_position.policy_registration_id, v_position.user_id,
         'position_closed', 'position', p_position_id::text,
         v_position.candidate_fingerprint,
         jsonb_build_object('terminal_spot',p_terminal_spot,
                            'terminal_value',v_terminal,
                            'realized_pnl',v_pnl,
                            'close_reason',p_close_reason), p_closed_at),
        (v_position.run_id, v_position.policy_registration_id, v_position.user_id,
         'outcome_recorded', 'outcome', v_outcome_id::text,
         v_position.candidate_fingerprint,
         jsonb_build_object('position_id',p_position_id,
                            'execution_mode','internal_paper',
                            'experiment','single_leg'), p_closed_at)
    ON CONFLICT DO NOTHING;

    RETURN jsonb_build_object(
        'status', 'closed',
        'idempotent_replay', false,
        'position_id', p_position_id,
        'outcome_id', v_outcome_id,
        'terminal_value', v_terminal,
        'realized_pnl', v_pnl,
        'cash_balance_after', v_after
    );
END;
$$;

ALTER TABLE single_leg_shadow_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE single_leg_shadow_positions ENABLE ROW LEVEL SECURITY;
ALTER TABLE single_leg_shadow_outcomes ENABLE ROW LEVEL SECURITY;
ALTER TABLE single_leg_shadow_cash_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role read single_leg_shadow_orders"
    ON single_leg_shadow_orders FOR SELECT
    USING (auth.role() = 'service_role');
CREATE POLICY "Service role read single_leg_shadow_positions"
    ON single_leg_shadow_positions FOR SELECT
    USING (auth.role() = 'service_role');
CREATE POLICY "Service role read single_leg_shadow_outcomes"
    ON single_leg_shadow_outcomes FOR SELECT
    USING (auth.role() = 'service_role');
CREATE POLICY "Service role read single_leg_shadow_cash_events"
    ON single_leg_shadow_cash_events FOR SELECT
    USING (auth.role() = 'service_role');

REVOKE ALL ON single_leg_shadow_orders FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON single_leg_shadow_positions FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON single_leg_shadow_outcomes FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON single_leg_shadow_cash_events FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON single_leg_shadow_orders TO service_role;
GRANT SELECT ON single_leg_shadow_positions TO service_role;
GRANT SELECT ON single_leg_shadow_outcomes TO service_role;
GRANT SELECT ON single_leg_shadow_cash_events TO service_role;

REVOKE ALL ON FUNCTION rpc_open_single_leg_shadow_position_v1(
    uuid,text,uuid,uuid,text,text,text,text,text,numeric,date,numeric,timestamptz,timestamptz
) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION rpc_close_single_leg_shadow_position_v1(
    uuid,numeric,timestamptz,text
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION rpc_open_single_leg_shadow_position_v1(
    uuid,text,uuid,uuid,text,text,text,text,text,numeric,date,numeric,timestamptz,timestamptz
) TO service_role;
GRANT EXECUTE ON FUNCTION rpc_close_single_leg_shadow_position_v1(
    uuid,numeric,timestamptz,text
) TO service_role;

COMMENT ON TABLE single_leg_shadow_orders IS
    'Internal-paper fills for one-contract single-leg experiment candidates; no broker order exists.';
COMMENT ON TABLE single_leg_shadow_positions IS
    'One-contract long-option experimental positions, isolated from paper_positions and live learning.';
COMMENT ON TABLE single_leg_shadow_outcomes IS
    'Expiry outcomes for internal-paper single-leg experiment positions; never broker-live evidence.';
COMMENT ON FUNCTION rpc_open_single_leg_shadow_position_v1 IS
    'Atomic one-contract shadow-only internal fill: validates epoch/binding/policy/candidate, locks portfolio cash, and never calls a broker.';
COMMENT ON FUNCTION rpc_close_single_leg_shadow_position_v1 IS
    'Atomic expiry settlement using exact long-call/long-put intrinsic payoff; writes isolated outcome and cash evidence.';

COMMIT;
NOTIFY pgrst, 'reload schema';
