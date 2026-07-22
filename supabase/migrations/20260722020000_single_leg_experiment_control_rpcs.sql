-- Guarded setup / approval / enable / pause controls for the independent
-- one-contract single-leg shadow experiment.
--
-- Applying this migration creates FUNCTIONS ONLY. It inserts no policy,
-- portfolio, binding, epoch, order, position, outcome, or fleet row and enables
-- nothing. Production data transitions require explicit service-role RPC calls.

BEGIN;

CREATE OR REPLACE FUNCTION single_leg_experiment_expected_policies_v1()
RETURNS TABLE (
    policy_registration_id text,
    config_hash text,
    experimental boolean
)
LANGUAGE sql
IMMUTABLE
SET search_path = public, pg_temp
AS $$
    VALUES
      ('sl_exp_throughput_v1', '71e854a6e9f098d561748b49161c5997459b4f2a7a19e27eebcb741c1987db5e', true),
      ('sl_ctrl_throughput_v1', '441ace2f5dc5b7842f6ae41db30db3dcd32ffbb1afa5585794659b04421fb310', false),
      ('sl_exp_conviction_v1', '59e02e8f09b3030f7fa5f3cd6f281ee42e80100e73f2a6e8fdcfe1e56374cf09', true),
      ('sl_ctrl_conviction_v1', '5f74bffe2d819d850f9c74be992b82f353a0ff15d5d2912abd9fb96502fc7de0', false)
$$;

CREATE OR REPLACE FUNCTION single_leg_experiment_current_fingerprint_v1(
    p_user_id uuid,
    p_starting_capital numeric DEFAULT 2000
)
RETURNS text
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_bindings text;
BEGIN
    SELECT string_agg(
               b.policy_registration_id || ':' || pr.config_hash || ':'
               || b.portfolio_id::text,
               ',' ORDER BY b.policy_registration_id COLLATE "C"
           )
      INTO v_bindings
      FROM single_leg_experiment_bindings b
      JOIN policy_registrations pr
        ON pr.policy_registration_id = b.policy_registration_id
     WHERE b.user_id = p_user_id
       AND b.epoch_name = 'single_leg_experiment_v1'
       AND b.role = 'experimental';
    IF v_bindings IS NULL THEN
        RETURN NULL;
    END IF;
    RETURN encode(
        extensions.digest(
            p_user_id::text || '|single_leg_experiment_v1|'
            || p_starting_capital::text || '|' || v_bindings,
            'sha256'
        ),
        'hex'
    );
END;
$$;

CREATE OR REPLACE FUNCTION rpc_setup_single_leg_experiment_v1(
    p_user_id uuid,
    p_starting_capital numeric DEFAULT 2000,
    p_created_by text DEFAULT 'operator'
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_expected record;
    v_binding single_leg_experiment_bindings%ROWTYPE;
    v_portfolio paper_portfolios%ROWTYPE;
    v_portfolio_id uuid;
    v_epoch_hash text;
    v_fingerprint text;
    v_created_portfolios int := 0;
    v_created_bindings int := 0;
    v_bad int;
    v_enabled int;
BEGIN
    IF p_user_id IS NULL THEN
        RAISE EXCEPTION 'p_user_id is required' USING ERRCODE = '23502';
    END IF;
    IF p_starting_capital IS DISTINCT FROM 2000::numeric THEN
        RAISE EXCEPTION 'single-leg experiment v1 starting capital is fixed at 2000'
            USING ERRCODE = '23514';
    END IF;
    IF btrim(coalesce(p_created_by, '')) = '' THEN
        RAISE EXCEPTION 'p_created_by is required' USING ERRCODE = '23514';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended('single_leg_experiment_v1:' || p_user_id::text, 0)
    );

    -- Exact manifest contract: all four rows exist under the correct epoch and
    -- hash. Controls omit the opt-in; experiment rows carry it.
    SELECT count(*) INTO v_bad
      FROM single_leg_experiment_expected_policies_v1() e
      LEFT JOIN policy_registrations pr
        ON pr.policy_registration_id = e.policy_registration_id
       AND pr.effective_epoch = 'single_leg_experiment_v1'
     WHERE pr.policy_registration_id IS NULL
        OR pr.config_hash <> e.config_hash
        OR pr.approval_status NOT IN ('draft', 'approved')
        OR (
            e.experimental
            AND lower(coalesce(
                pr.policy_config->>'single_leg_experiment_enabled', 'false'
            )) NOT IN ('true','1','yes','on')
        )
        OR (
            NOT e.experimental
            AND pr.policy_config ? 'single_leg_experiment_enabled'
        );
    IF v_bad <> 0 THEN
        RAISE EXCEPTION 'single-leg manifest registry contract failed for % row(s)',
            v_bad USING ERRCODE = '23001';
    END IF;

    SELECT count(*) INTO v_bad
      FROM policy_registrations
     WHERE effective_epoch = 'single_leg_experiment_v1'
       AND policy_registration_id NOT IN (
           SELECT policy_registration_id
             FROM single_leg_experiment_expected_policies_v1()
       );
    IF v_bad <> 0 THEN
        RAISE EXCEPTION 'unexpected policy rows exist in single_leg_experiment_v1'
            USING ERRCODE = '23001';
    END IF;

    SELECT encode(
               extensions.digest(
                   'single_leg_experiment_v1|shadow_only|internal_paper|1|false|2000|'
                   || string_agg(
                       policy_registration_id || ':' || config_hash,
                       ',' ORDER BY policy_registration_id COLLATE "C"
                   ),
                   'sha256'
               ),
               'hex'
           )
      INTO v_epoch_hash
      FROM single_leg_experiment_expected_policies_v1();

    INSERT INTO single_leg_experiment_epochs (
        epoch_name, state, routing_mode, max_contracts, live_submit_allowed,
        config_hash, version, created_by
    ) VALUES (
        'single_leg_experiment_v1', 'disabled', 'shadow_only', 1, false,
        v_epoch_hash, 1, p_created_by
    )
    ON CONFLICT (epoch_name) DO NOTHING;

    -- Setup is deliberately a T1-only operation. Replays are permitted while
    -- disabled, but it refuses to masquerade as a zero-enable setup after a
    -- pause or enable transition.
    SELECT count(*) INTO v_bad
      FROM single_leg_experiment_epochs
     WHERE epoch_name = 'single_leg_experiment_v1'
       AND (
           state <> 'disabled'
           OR routing_mode <> 'shadow_only'
           OR max_contracts <> 1
           OR live_submit_allowed
           OR config_hash <> v_epoch_hash
           OR version <> 1
       );
    IF v_bad <> 0 THEN
        RAISE EXCEPTION 'single-leg disabled epoch contract drifted'
            USING ERRCODE = '23001';
    END IF;

    -- V1 is intentionally single-user. A global epoch cannot honestly be
    -- enabled for one account while another account's bindings remain live.
    SELECT count(*) INTO v_bad
      FROM single_leg_experiment_bindings
     WHERE epoch_name = 'single_leg_experiment_v1'
       AND user_id <> p_user_id;
    IF v_bad <> 0 THEN
        RAISE EXCEPTION 'single-leg experiment v1 already belongs to another user'
            USING ERRCODE = '23001';
    END IF;

    FOR v_expected IN
        SELECT *
          FROM single_leg_experiment_expected_policies_v1()
         WHERE experimental
         ORDER BY policy_registration_id COLLATE "C"
    LOOP
        SELECT * INTO v_binding
          FROM single_leg_experiment_bindings
         WHERE policy_registration_id = v_expected.policy_registration_id
           AND epoch_name = 'single_leg_experiment_v1';

        IF FOUND THEN
            SELECT * INTO v_portfolio
              FROM paper_portfolios
             WHERE id = v_binding.portfolio_id
               AND user_id = p_user_id
               AND routing_mode = 'shadow_only';
            IF NOT FOUND
               OR v_binding.user_id <> p_user_id
               OR v_binding.role <> 'experimental'
               OR v_binding.routing_mode <> 'shadow_only'
               OR v_binding.execution_mode <> 'internal_paper'
               OR v_binding.enabled THEN
                RAISE EXCEPTION 'existing disabled binding/portfolio drifted for %',
                    v_expected.policy_registration_id
                    USING ERRCODE = '23001';
            END IF;
            CONTINUE;
        END IF;

        INSERT INTO paper_portfolios (
            user_id, name, cash_balance, net_liq, routing_mode
        ) VALUES (
            p_user_id,
            CASE v_expected.policy_registration_id
                WHEN 'sl_exp_throughput_v1' THEN 'Single Leg Throughput v1'
                ELSE 'Single Leg Conviction v1'
            END,
            p_starting_capital,
            p_starting_capital,
            'shadow_only'
        ) RETURNING id INTO v_portfolio_id;
        v_created_portfolios := v_created_portfolios + 1;

        INSERT INTO single_leg_experiment_bindings (
            policy_registration_id, epoch_name, portfolio_id, user_id, role,
            routing_mode, execution_mode, enabled, created_by
        ) VALUES (
            v_expected.policy_registration_id,
            'single_leg_experiment_v1',
            v_portfolio_id,
            p_user_id,
            'experimental',
            'shadow_only',
            'internal_paper',
            false,
            p_created_by
        );
        v_created_bindings := v_created_bindings + 1;
    END LOOP;

    SELECT count(*) INTO v_bad
      FROM single_leg_experiment_bindings
     WHERE epoch_name = 'single_leg_experiment_v1'
       AND user_id = p_user_id
       AND (
           role <> 'experimental'
           OR routing_mode <> 'shadow_only'
           OR execution_mode <> 'internal_paper'
           OR policy_registration_id NOT IN (
               'sl_exp_throughput_v1','sl_exp_conviction_v1'
           )
       );
    IF v_bad <> 0 THEN
        RAISE EXCEPTION 'single-leg binding set contains unexpected rows'
            USING ERRCODE = '23001';
    END IF;

    SELECT count(*), count(*) FILTER (WHERE enabled)
      INTO v_bad, v_enabled
      FROM single_leg_experiment_bindings
     WHERE epoch_name = 'single_leg_experiment_v1'
       AND user_id = p_user_id;
    IF v_bad <> 2 OR v_enabled <> 0 THEN
        RAISE EXCEPTION 'single-leg setup expected 2 disabled bindings, got % total / % enabled',
            v_bad, v_enabled USING ERRCODE = '23001';
    END IF;

    v_fingerprint := single_leg_experiment_current_fingerprint_v1(
        p_user_id, p_starting_capital
    );
    RETURN jsonb_build_object(
        'status', 'disabled_setup_ready',
        'user_id', p_user_id,
        'policy_epoch', 'single_leg_experiment_v1',
        'starting_capital', p_starting_capital,
        'setup_fingerprint', v_fingerprint,
        'created_portfolios', v_created_portfolios,
        'created_bindings', v_created_bindings,
        'policy_rows', 4,
        'experimental_bindings', 2,
        'enabled_bindings', v_enabled
    );
END;
$$;

CREATE OR REPLACE FUNCTION rpc_approve_single_leg_experiment_v1(
    p_user_id uuid,
    p_setup_fingerprint text,
    p_approved_by text DEFAULT 'operator'
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_current text;
    v_draft int;
    v_approved int;
BEGIN
    IF btrim(coalesce(p_approved_by, '')) = '' THEN
        RAISE EXCEPTION 'p_approved_by is required' USING ERRCODE = '23514';
    END IF;
    PERFORM pg_advisory_xact_lock(
        hashtextextended('single_leg_experiment_v1:' || p_user_id::text, 0)
    );
    v_current := single_leg_experiment_current_fingerprint_v1(p_user_id, 2000);
    IF v_current IS NULL OR v_current <> p_setup_fingerprint THEN
        RAISE EXCEPTION 'single-leg setup fingerprint mismatch'
            USING ERRCODE = '23001';
    END IF;
    PERFORM 1 FROM single_leg_experiment_epochs
     WHERE epoch_name = 'single_leg_experiment_v1'
       AND state = 'disabled'
       AND live_submit_allowed = false;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'single-leg epoch must be disabled for approval'
            USING ERRCODE = '23001';
    END IF;

    SELECT count(*) FILTER (WHERE approval_status = 'draft'),
           count(*) FILTER (WHERE approval_status = 'approved')
      INTO v_draft, v_approved
      FROM policy_registrations pr
      JOIN single_leg_experiment_expected_policies_v1() e
        ON e.policy_registration_id = pr.policy_registration_id
       AND e.config_hash = pr.config_hash
     WHERE pr.effective_epoch = 'single_leg_experiment_v1';

    IF v_approved = 4 AND v_draft = 0 THEN
        RETURN jsonb_build_object(
            'status','approved',
            'idempotent_replay',true,
            'setup_fingerprint',v_current,
            'approved_rows',4,
            'approved_by',p_approved_by
        );
    END IF;
    IF v_draft <> 4 OR v_approved <> 0 THEN
        RAISE EXCEPTION 'policy approval state is mixed, drifted, or incomplete'
            USING ERRCODE = '23001';
    END IF;

    UPDATE policy_registrations
       SET approval_status = 'approved',
           approved_at = now()
     WHERE effective_epoch = 'single_leg_experiment_v1'
       AND policy_registration_id IN (
           SELECT policy_registration_id
             FROM single_leg_experiment_expected_policies_v1()
       )
       AND approval_status = 'draft';

    RETURN jsonb_build_object(
        'status','approved',
        'idempotent_replay',false,
        'setup_fingerprint',v_current,
        'approved_rows',4,
        'approved_by',p_approved_by
    );
END;
$$;

CREATE OR REPLACE FUNCTION rpc_enable_single_leg_experiment_v1(
    p_user_id uuid,
    p_setup_fingerprint text,
    p_enabled_by text DEFAULT 'operator'
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_current text;
    v_approved int;
    v_bindings int;
    v_enabled int;
    v_state text;
BEGIN
    IF btrim(coalesce(p_enabled_by, '')) = '' THEN
        RAISE EXCEPTION 'p_enabled_by is required' USING ERRCODE = '23514';
    END IF;
    PERFORM pg_advisory_xact_lock(
        hashtextextended('single_leg_experiment_v1:' || p_user_id::text, 0)
    );
    v_current := single_leg_experiment_current_fingerprint_v1(p_user_id, 2000);
    IF v_current IS NULL OR v_current <> p_setup_fingerprint THEN
        RAISE EXCEPTION 'single-leg setup fingerprint mismatch'
            USING ERRCODE = '23001';
    END IF;

    SELECT state INTO v_state
      FROM single_leg_experiment_epochs
     WHERE epoch_name = 'single_leg_experiment_v1'
     FOR UPDATE;
    IF v_state = 'enabled' THEN
        SELECT count(*) INTO v_enabled
          FROM single_leg_experiment_bindings
         WHERE epoch_name = 'single_leg_experiment_v1'
           AND user_id = p_user_id
           AND role = 'experimental'
           AND enabled;
        IF v_enabled = 2 THEN
            RETURN jsonb_build_object(
                'status','enabled',
                'idempotent_replay',true,
                'setup_fingerprint',v_current,
                'enabled_bindings',2,
                'enabled_by',p_enabled_by
            );
        END IF;
        RAISE EXCEPTION 'enabled epoch has incomplete binding state'
            USING ERRCODE = '23001';
    END IF;
    IF v_state NOT IN ('disabled','paused') THEN
        RAISE EXCEPTION 'single-leg epoch cannot be enabled from state %', v_state
            USING ERRCODE = '23001';
    END IF;

    SELECT count(*) INTO v_approved
      FROM policy_registrations pr
      JOIN single_leg_experiment_expected_policies_v1() e
        ON e.policy_registration_id = pr.policy_registration_id
       AND e.config_hash = pr.config_hash
     WHERE pr.effective_epoch = 'single_leg_experiment_v1'
       AND pr.approval_status = 'approved';
    IF v_approved <> 4 THEN
        RAISE EXCEPTION 'single-leg enable requires 4 exact approved policies'
            USING ERRCODE = '23001';
    END IF;

    SELECT count(*) INTO v_bindings
      FROM single_leg_experiment_bindings b
      JOIN paper_portfolios pp ON pp.id = b.portfolio_id
     WHERE b.epoch_name = 'single_leg_experiment_v1'
       AND b.user_id = p_user_id
       AND b.role = 'experimental'
       AND b.routing_mode = 'shadow_only'
       AND b.execution_mode = 'internal_paper'
       AND b.policy_registration_id IN (
           'sl_exp_throughput_v1','sl_exp_conviction_v1'
       )
       AND pp.user_id = p_user_id
       AND pp.routing_mode = 'shadow_only';
    IF v_bindings <> 2 THEN
        RAISE EXCEPTION 'single-leg enable requires 2 exact shadow bindings'
            USING ERRCODE = '23001';
    END IF;

    SELECT count(*) INTO v_enabled
      FROM single_leg_experiment_bindings
     WHERE epoch_name = 'single_leg_experiment_v1'
       AND user_id <> p_user_id
       AND enabled;
    IF v_enabled <> 0 THEN
        RAISE EXCEPTION 'another user has enabled single-leg bindings'
            USING ERRCODE = '23001';
    END IF;

    UPDATE single_leg_experiment_bindings
       SET enabled = true
     WHERE epoch_name = 'single_leg_experiment_v1'
       AND user_id = p_user_id
       AND role = 'experimental';

    UPDATE single_leg_experiment_epochs
       SET state = 'enabled',
           enabled_at = now(),
           enabled_by = p_enabled_by
     WHERE epoch_name = 'single_leg_experiment_v1';

    RETURN jsonb_build_object(
        'status','enabled',
        'idempotent_replay',false,
        'setup_fingerprint',v_current,
        'enabled_bindings',2,
        'routing_mode','shadow_only',
        'execution_mode','internal_paper',
        'max_contracts',1,
        'live_submit_allowed',false,
        'enabled_by',p_enabled_by
    );
END;
$$;

CREATE OR REPLACE FUNCTION rpc_pause_single_leg_experiment_v1(
    p_user_id uuid,
    p_reason text DEFAULT 'operator_pause'
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_state text;
BEGIN
    IF btrim(coalesce(p_reason,'')) = '' THEN
        RAISE EXCEPTION 'pause reason is required' USING ERRCODE = '23514';
    END IF;
    PERFORM pg_advisory_xact_lock(
        hashtextextended('single_leg_experiment_v1:' || p_user_id::text, 0)
    );
    SELECT state INTO v_state
      FROM single_leg_experiment_epochs
     WHERE epoch_name = 'single_leg_experiment_v1'
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'single-leg epoch missing' USING ERRCODE = '23001';
    END IF;
    PERFORM 1
      FROM single_leg_experiment_bindings
     WHERE epoch_name = 'single_leg_experiment_v1'
       AND user_id = p_user_id
       AND role = 'experimental';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'single-leg user binding missing' USING ERRCODE = '23001';
    END IF;

    -- The epoch is global; pause every binding under it so no second account can
    -- continue generating after the persisted kill switch is set.
    UPDATE single_leg_experiment_bindings
       SET enabled = false
     WHERE epoch_name = 'single_leg_experiment_v1';
    UPDATE single_leg_experiment_epochs
       SET state = 'paused'
     WHERE epoch_name = 'single_leg_experiment_v1';

    RETURN jsonb_build_object(
        'status','paused',
        'prior_state',v_state,
        'reason',p_reason,
        'enabled_bindings',0
    );
END;
$$;

REVOKE ALL ON FUNCTION single_leg_experiment_expected_policies_v1()
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION single_leg_experiment_current_fingerprint_v1(uuid,numeric)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION rpc_setup_single_leg_experiment_v1(uuid,numeric,text)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION rpc_approve_single_leg_experiment_v1(uuid,text,text)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION rpc_enable_single_leg_experiment_v1(uuid,text,text)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION rpc_pause_single_leg_experiment_v1(uuid,text)
    FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION single_leg_experiment_expected_policies_v1()
    TO service_role;
GRANT EXECUTE ON FUNCTION single_leg_experiment_current_fingerprint_v1(uuid,numeric)
    TO service_role;
GRANT EXECUTE ON FUNCTION rpc_setup_single_leg_experiment_v1(uuid,numeric,text)
    TO service_role;
GRANT EXECUTE ON FUNCTION rpc_approve_single_leg_experiment_v1(uuid,text,text)
    TO service_role;
GRANT EXECUTE ON FUNCTION rpc_enable_single_leg_experiment_v1(uuid,text,text)
    TO service_role;
GRANT EXECUTE ON FUNCTION rpc_pause_single_leg_experiment_v1(uuid,text)
    TO service_role;

COMMENT ON FUNCTION rpc_setup_single_leg_experiment_v1 IS
    'Creates/validates a disabled single-user epoch plus exactly two shadow-only internal-paper experimental portfolios/bindings; never approves or enables.';
COMMENT ON FUNCTION rpc_approve_single_leg_experiment_v1 IS
    'Approves the four exact manifest-hash policy rows after a fingerprinted disabled setup; no enablement.';
COMMENT ON FUNCTION rpc_enable_single_leg_experiment_v1 IS
    'Atomically enables only the two experimental bindings and persisted shadow-only epoch after exact policy/setup checks.';
COMMENT ON FUNCTION rpc_pause_single_leg_experiment_v1 IS
    'Immediate persisted kill switch: disables all epoch bindings and pauses new child scans while preserving evidence/open positions.';

COMMIT;
NOTIFY pgrst, 'reload schema';
