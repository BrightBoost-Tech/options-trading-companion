-- Follow-up to 20260722010000: serialize exact-replay opens on the run row
-- before checking for an existing order, and use a valid SQLSTATE for
-- insufficient experimental cash. No schema/data change and safe to reapply.

BEGIN;

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
        RAISE EXCEPTION 'invalid fill_price_per_share' USING ERRCODE = '23514';
    END IF;
    IF p_strike IS NULL OR p_strike <= 0
       OR p_strike::text IN ('NaN', 'Infinity', '-Infinity') THEN
        RAISE EXCEPTION 'invalid strike' USING ERRCODE = '23514';
    END IF;
    IF p_option_type NOT IN ('call', 'put')
       OR p_strategy_type <> ('long_' || p_option_type) THEN
        RAISE EXCEPTION 'single-leg option/strategy mismatch' USING ERRCODE = '23514';
    END IF;

    -- The run lock serializes two workers attempting the same exact candidate.
    -- The loser observes the existing order and returns the same receipt rather
    -- than surfacing a uniqueness error or double-debiting portfolio cash.
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
        RAISE EXCEPTION 'single-leg run identity/state invalid' USING ERRCODE = '23001';
    END IF;

    SELECT * INTO v_existing
      FROM single_leg_shadow_orders
     WHERE run_id = p_run_id
       AND policy_registration_id = p_policy_registration_id
       AND portfolio_id = p_portfolio_id
       AND user_id = p_user_id
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

    SELECT * INTO v_attempt
      FROM single_leg_shadow_attempts
     WHERE run_id = p_run_id
       AND policy_registration_id = p_policy_registration_id
       AND candidate_fingerprint = p_candidate_fingerprint
       AND symbol = p_symbol
       AND stage = 'candidate_generated';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'candidate_generated evidence missing' USING ERRCODE = '23001';
    END IF;
    IF v_attempt.occ_symbol IS DISTINCT FROM p_occ_symbol
       OR v_attempt.strike IS DISTINCT FROM p_strike
       OR v_attempt.expiry IS DISTINCT FROM p_expiry
       OR v_attempt.strategy_type IS DISTINCT FROM p_strategy_type THEN
        RAISE EXCEPTION 'candidate execution identity mismatch' USING ERRCODE = '23001';
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
            USING ERRCODE = '23001';
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
            USING ERRCODE = '23001';
    END IF;
    v_max_text := v_policy.policy_config->>'single_leg_max_debit_per_contract';
    IF v_max_text ~ '^[0-9]+([.][0-9]+)?$' THEN
        v_max_debit := v_max_text::numeric;
    END IF;

    v_debit := round(p_fill_price_per_share * 100, 2);
    IF v_debit <= 0 OR v_debit > v_max_debit THEN
        RAISE EXCEPTION 'execution debit % exceeds policy cap %', v_debit, v_max_debit
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO v_portfolio
      FROM paper_portfolios
     WHERE id = p_portfolio_id
       AND user_id = p_user_id
       AND routing_mode = 'shadow_only'
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'shadow-only experiment portfolio missing'
            USING ERRCODE = '23001';
    END IF;
    IF v_portfolio.cash_balance < v_debit THEN
        RAISE EXCEPTION 'insufficient experimental portfolio cash'
            USING ERRCODE = '23514';
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

REVOKE ALL ON FUNCTION rpc_open_single_leg_shadow_position_v1(
    uuid,text,uuid,uuid,text,text,text,text,text,numeric,date,numeric,timestamptz,timestamptz
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION rpc_open_single_leg_shadow_position_v1(
    uuid,text,uuid,uuid,text,text,text,text,text,numeric,date,numeric,timestamptz,timestamptz
) TO service_role;

COMMIT;
NOTIFY pgrst, 'reload schema';
