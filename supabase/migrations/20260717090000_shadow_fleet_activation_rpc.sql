-- =============================================================================
-- F-SHADOW-CAPITAL-PARITY (Lane 3A): shadow-fleet provisioning/activation RPCs
-- =============================================================================
-- NOT APPLIED BY THIS PR. This file ships with the activation-service code so
-- the atomic unit is reviewable next to its caller; it is applied only via a
-- later operator-owned migration prompt (docs/migration_procedure.md).
--
-- Why an RPC: supabase-py has no client-side transactions. Provisioning is a
-- 101-row write (1 fleet + 50 portfolios + 50 slots) and activation is a
-- 51-row transition (50 slots + 1 fleet) plus a receipt. Any partial subset
-- of those writes is a lie about the fleet's state, so both steps execute
-- entirely inside a single plpgsql function body — one server-side
-- transaction; any RAISE rolls the whole step back. No compensating client
-- steps exist, so no partially-visible activation can exist.
--
-- Fail-closed contract (mirrors packages/quantum/services/
-- shadow_fleet_activation.py — the drift-lock test pins the two together):
--   * Legacy scope = every paper_orders / paper_positions row whose
--     portfolio_id is NOT one of THIS fleet's micro-account portfolios
--     (NULL portfolio_id counts as legacy). Membership-based, not
--     timestamp-based: everything predating the fleet epoch is legacy by
--     construction, and clock skew cannot narrow the scope.
--   * Order terminality is an ALLOWLIST. Anything not in it — including the
--     six stale 2026-04-09 'submitted' rows, 'needs_manual_review', and any
--     unknown future status — blocks activation.
--   * legacy_terminal_verified_at comes ONLY from the operator attestation
--     payload (which must reference the stale-order reconciliation receipt).
--     It is never invented server-side.
--   * effective_at / activated_at are DB now() captured once inside the
--     activation transaction — never a client-supplied timestamp.
--   * Legacy rows are never rewritten: neither function UPDATEs or DELETEs
--     any paper_orders / paper_positions row.
--   * Operator-only: EXECUTE is revoked from PUBLIC/anon/authenticated;
--     only service_role (the signed-task backend) may call these.
-- =============================================================================

-- =============================================================================
-- rpc_shadow_fleet_provision
-- =============================================================================
-- Creates, atomically: 1 shadow_fleets row (status 'pending_legacy_terminal')
-- + 50 isolated $2,000 paper_portfolios (routing_mode 'shadow_only', NEVER
-- 'live_eligible') + 50 inactive shadow_micro_accounts rows binding them,
-- + 1 risk_alerts info receipt row.
--
-- Idempotency: the durable anchor is UNIQUE(user_id, epoch_name) on
-- shadow_fleets, serialized by an advisory xact lock. A second invocation
-- (any idempotency key) finds the fleet and returns 'already_provisioned'
-- ('already_active' if activated) with zero writes. p_idempotency_key is
-- required and recorded in the receipt for audit; there is no dedicated
-- idempotency-key column on shadow_fleets (noted gap — a durable
-- receipt/idempotency table would be a separate migration PR).

CREATE OR REPLACE FUNCTION rpc_shadow_fleet_provision(
    p_user_id uuid,
    p_idempotency_key text
)
RETURNS jsonb
LANGUAGE plpgsql
AS $$
DECLARE
    v_fleet shadow_fleets%ROWTYPE;
    v_portfolio_id uuid;
    v_slot integer;
    v_slots_created integer := 0;
BEGIN
    IF p_user_id IS NULL THEN
        RAISE EXCEPTION 'shadow_fleet_provision: p_user_id is required';
    END IF;
    IF p_idempotency_key IS NULL OR btrim(p_idempotency_key) = '' THEN
        RAISE EXCEPTION 'shadow_fleet_provision: p_idempotency_key is required';
    END IF;

    -- Serialize concurrent invocations for this user's fleet.
    PERFORM pg_advisory_xact_lock(
        hashtext('shadow_fleet:small_tier_v1:' || p_user_id::text)
    );

    SELECT * INTO v_fleet
      FROM shadow_fleets
     WHERE user_id = p_user_id
       AND epoch_name = 'small_tier_v1'
       FOR UPDATE;

    IF FOUND THEN
        -- Idempotent no-op: zero writes on re-invocation.
        RETURN jsonb_build_object(
            'status', CASE WHEN v_fleet.status = 'active'
                           THEN 'already_active'
                           ELSE 'already_provisioned' END,
            'fleet_id', v_fleet.id,
            'fleet_status', v_fleet.status,
            'portfolios_created', 0,
            'slots_created', 0
        );
    END IF;

    -- Contract columns set explicitly; the 20260716060000 CHECKs enforce them.
    INSERT INTO shadow_fleets (
        user_id, epoch_name, legacy_epoch_name, capital_basis,
        micro_account_count, capital_per_account, shared_capital_enabled,
        decision_event_basis, status
    ) VALUES (
        p_user_id, 'small_tier_v1', 'legacy_100k', 'fixed_small_tier',
        50, 2000, false,
        'source_suggestion_id', 'pending_legacy_terminal'
    )
    RETURNING * INTO v_fleet;

    FOR v_slot IN 1..50 LOOP
        -- Isolated $2k book. routing_mode MUST be set explicitly: the table
        -- default is 'live_eligible' and a fleet slot must never carry it.
        INSERT INTO paper_portfolios (
            user_id, name, cash_balance, net_liq, routing_mode
        ) VALUES (
            p_user_id,
            'Shadow Fleet small_tier_v1 - Slot ' || lpad(v_slot::text, 2, '0'),
            2000, 2000, 'shadow_only'
        )
        RETURNING id INTO v_portfolio_id;

        INSERT INTO shadow_micro_accounts (
            fleet_id, slot_number, portfolio_id, state,
            initial_net_liq, initial_cash
        ) VALUES (
            v_fleet.id, v_slot, v_portfolio_id, 'inactive',
            2000, 2000
        );

        v_slots_created := v_slots_created + 1;
    END LOOP;

    IF v_slots_created <> 50 THEN
        RAISE EXCEPTION
            'shadow_fleet_provision: expected 50 slots, created % — aborting',
            v_slots_created;
    END IF;

    -- Audit receipt (info row; same transaction as the writes it describes).
    INSERT INTO risk_alerts (
        user_id, alert_type, severity, message, resolved, metadata
    ) VALUES (
        p_user_id,
        'shadow_fleet_provisioned',
        'info',
        'Shadow fleet small_tier_v1 provisioned: 50 x $2,000 isolated '
            || 'shadow_only slots, status pending_legacy_terminal.',
        false,
        jsonb_build_object(
            'step', 'provision',
            'idempotency_key', p_idempotency_key,
            'fleet_id', v_fleet.id,
            'epoch_name', 'small_tier_v1',
            'micro_account_count', 50,
            'capital_per_account', 2000,
            'shared_capital', false,
            'routing_mode', 'shadow_only'
        )
    );

    RETURN jsonb_build_object(
        'status', 'provisioned',
        'fleet_id', v_fleet.id,
        'fleet_status', 'pending_legacy_terminal',
        'portfolios_created', 50,
        'slots_created', 50
    );
END;
$$;

COMMENT ON FUNCTION rpc_shadow_fleet_provision(uuid, text) IS
    'Atomically provisions the 50x$2,000 small_tier_v1 shadow fleet '
    '(fleet row + 50 shadow_only paper_portfolios + 50 inactive slots + '
    'receipt) in one transaction. Idempotent via UNIQUE(user_id, epoch_name); '
    're-invocation returns already_provisioned with zero writes. '
    'Operator-only (service_role).';

-- =============================================================================
-- rpc_shadow_fleet_activate
-- =============================================================================
-- Activates the provisioned fleet, atomically, iff:
--   * fleet exists and is not already active/retired (already-active returns
--     an idempotent no-op with zero writes);
--   * every legacy paper_orders row (scope above) has an allowlisted terminal
--     status and every legacy paper_positions row is 'closed' — re-verified
--     INSIDE this transaction, immediately before the transition;
--   * the operator payload binds all 50 slots to unique, non-blank,
--     pre-registered policy ids (never invented or defaulted here);
--   * the attestation payload references the stale-order reconciliation
--     receipt and carries the legacy_terminal_verified_at timestamp.
-- Any violation RAISEs and the whole transaction rolls back: there is no
-- partially-visible activation state.

CREATE OR REPLACE FUNCTION rpc_shadow_fleet_activate(
    p_user_id uuid,
    p_idempotency_key text,
    p_policy_registrations jsonb,
    p_attestation jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
AS $$
DECLARE
    v_fleet shadow_fleets%ROWTYPE;
    v_effective_at timestamptz;
    v_verified_at timestamptz;
    v_receipt_ref text;
    v_attested_by text;
    v_count integer;
    v_updated integer;
    v_slot_numbers integer[];
BEGIN
    IF p_user_id IS NULL THEN
        RAISE EXCEPTION 'shadow_fleet_activate: p_user_id is required';
    END IF;
    IF p_idempotency_key IS NULL OR btrim(p_idempotency_key) = '' THEN
        RAISE EXCEPTION 'shadow_fleet_activate: p_idempotency_key is required';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtext('shadow_fleet:small_tier_v1:' || p_user_id::text)
    );

    SELECT * INTO v_fleet
      FROM shadow_fleets
     WHERE user_id = p_user_id
       AND epoch_name = 'small_tier_v1'
       FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'shadow_fleet_activate: fleet_not_provisioned';
    END IF;

    IF v_fleet.status = 'active' THEN
        -- Idempotent no-op: zero writes on re-invocation.
        RETURN jsonb_build_object(
            'status', 'already_active',
            'fleet_id', v_fleet.id,
            'effective_at', v_fleet.effective_at,
            'slots_activated', 0
        );
    END IF;

    IF v_fleet.status = 'retired' THEN
        RAISE EXCEPTION 'shadow_fleet_activate: fleet_retired';
    END IF;

    -- ── Attestation (operator-supplied; NEVER defaulted) ────────────────────
    IF p_attestation IS NULL OR jsonb_typeof(p_attestation) <> 'object' THEN
        RAISE EXCEPTION 'shadow_fleet_activate: attestation_payload_required';
    END IF;
    v_receipt_ref := btrim(
        COALESCE(p_attestation->>'stale_order_reconciliation_receipt', '')
    );
    IF v_receipt_ref = '' THEN
        RAISE EXCEPTION
            'shadow_fleet_activate: attestation_missing_stale_order_reconciliation_receipt';
    END IF;
    v_attested_by := btrim(COALESCE(p_attestation->>'attested_by', ''));
    IF v_attested_by = '' THEN
        RAISE EXCEPTION 'shadow_fleet_activate: attestation_missing_attested_by';
    END IF;
    -- legacy_terminal_verified_at comes ONLY from the attestation.
    v_verified_at := (p_attestation->>'legacy_terminal_verified_at')::timestamptz;
    IF v_verified_at IS NULL THEN
        RAISE EXCEPTION
            'shadow_fleet_activate: attestation_missing_legacy_terminal_verified_at';
    END IF;

    -- ── Slot inventory (lock, then verify the 50-slot / $2k contract) ───────
    PERFORM 1 FROM shadow_micro_accounts
      WHERE fleet_id = v_fleet.id
      FOR UPDATE;

    SELECT COUNT(*), array_agg(slot_number ORDER BY slot_number)
      INTO v_count, v_slot_numbers
      FROM shadow_micro_accounts
     WHERE fleet_id = v_fleet.id;
    IF v_count <> 50
       OR v_slot_numbers IS DISTINCT FROM ARRAY(SELECT generate_series(1, 50))
    THEN
        RAISE EXCEPTION
            'shadow_fleet_activate: slot_count_invalid (% rows)', v_count;
    END IF;

    SELECT COUNT(*) INTO v_count
      FROM shadow_micro_accounts
     WHERE fleet_id = v_fleet.id
       AND (state <> 'inactive'
            OR portfolio_id IS NULL
            OR initial_net_liq <> 2000
            OR initial_cash <> 2000);
    IF v_count > 0 THEN
        RAISE EXCEPTION
            'shadow_fleet_activate: capital_contract_invalid (% slots)', v_count;
    END IF;

    -- Every fleet portfolio must still be shadow-routed; never live_eligible.
    SELECT COUNT(*) INTO v_count
      FROM shadow_micro_accounts sma
      JOIN paper_portfolios pp ON pp.id = sma.portfolio_id
     WHERE sma.fleet_id = v_fleet.id
       AND pp.routing_mode <> 'shadow_only';
    IF v_count > 0 THEN
        RAISE EXCEPTION
            'shadow_fleet_activate: fleet_portfolio_not_shadow_routed (% rows)',
            v_count;
    END IF;

    -- ── Legacy-terminal re-verification (inside THIS transaction) ───────────
    -- Terminal-order ALLOWLIST: anything else blocks (fail-closed), including
    -- the stale 2026-04-09 'submitted' rows and 'needs_manual_review'.
    SELECT COUNT(*) INTO v_count
      FROM paper_orders o
     WHERE o.status NOT IN (
               'filled', 'cancelled', 'watchdog_cancelled',
               'expired', 'rejected', 'manual_close_complete'
           )
       AND (o.portfolio_id IS NULL
            OR o.portfolio_id NOT IN (
                   SELECT sma.portfolio_id FROM shadow_micro_accounts sma
                    WHERE sma.fleet_id = v_fleet.id
                      AND sma.portfolio_id IS NOT NULL
               ));
    IF v_count > 0 THEN
        RAISE EXCEPTION
            'shadow_fleet_activate: legacy_orders_not_terminal (% rows)', v_count;
    END IF;

    SELECT COUNT(*) INTO v_count
      FROM paper_positions p
     WHERE p.status NOT IN ('closed')
       AND (p.portfolio_id IS NULL
            OR p.portfolio_id NOT IN (
                   SELECT sma.portfolio_id FROM shadow_micro_accounts sma
                    WHERE sma.fleet_id = v_fleet.id
                      AND sma.portfolio_id IS NOT NULL
               ));
    IF v_count > 0 THEN
        RAISE EXCEPTION
            'shadow_fleet_activate: legacy_positions_not_terminal (% rows)', v_count;
    END IF;

    -- ── Policy registrations: exactly 50, slots 1..50, unique, non-blank ────
    IF p_policy_registrations IS NULL
       OR jsonb_typeof(p_policy_registrations) <> 'object' THEN
        RAISE EXCEPTION 'shadow_fleet_activate: policy_registration_missing';
    END IF;

    SELECT COUNT(*) INTO v_count
      FROM jsonb_each_text(p_policy_registrations);
    IF v_count <> 50 THEN
        RAISE EXCEPTION
            'shadow_fleet_activate: policy_registration_missing (% of 50)', v_count;
    END IF;

    SELECT COUNT(*) INTO v_count
      FROM jsonb_each_text(p_policy_registrations) r
     WHERE r.key ~ '^[0-9]+$'
       AND (r.key)::int BETWEEN 1 AND 50;
    IF v_count <> 50 THEN
        RAISE EXCEPTION
            'shadow_fleet_activate: policy_registration_missing (bad slot keys)';
    END IF;

    SELECT COUNT(*) INTO v_count
      FROM jsonb_each_text(p_policy_registrations) r
     WHERE r.value IS NULL OR btrim(r.value) = '';
    IF v_count > 0 THEN
        RAISE EXCEPTION
            'shadow_fleet_activate: policy_registration_missing (% blank ids)',
            v_count;
    END IF;

    SELECT COUNT(DISTINCT btrim(r.value)) INTO v_count
      FROM jsonb_each_text(p_policy_registrations) r;
    IF v_count <> 50 THEN
        RAISE EXCEPTION
            'shadow_fleet_activate: policy_registration_duplicate (% distinct)',
            v_count;
    END IF;

    -- ── Effective boundary: DB time, captured once, same transaction ────────
    v_effective_at := now();

    UPDATE shadow_micro_accounts sma
       SET policy_registration_id = btrim(r.value),
           state = 'active',
           activated_at = v_effective_at
      FROM jsonb_each_text(p_policy_registrations) r
     WHERE sma.fleet_id = v_fleet.id
       AND sma.slot_number = (r.key)::int
       AND sma.state = 'inactive';
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    IF v_updated <> 50 THEN
        RAISE EXCEPTION
            'shadow_fleet_activate: expected 50 slot activations, got % — aborting (no partial activation)',
            v_updated;
    END IF;

    UPDATE shadow_fleets
       SET status = 'active',
           legacy_terminal_verified_at = v_verified_at,
           effective_at = v_effective_at
     WHERE id = v_fleet.id;

    -- Audit receipt (info row; same transaction as the transition).
    INSERT INTO risk_alerts (
        user_id, alert_type, severity, message, resolved, metadata
    ) VALUES (
        p_user_id,
        'shadow_fleet_activated',
        'info',
        'Shadow fleet small_tier_v1 ACTIVATED: 50 slots bound to '
            || 'pre-registered policies; legacy book attested terminal.',
        false,
        jsonb_build_object(
            'step', 'activate',
            'idempotency_key', p_idempotency_key,
            'fleet_id', v_fleet.id,
            'effective_at', v_effective_at,
            'legacy_terminal_verified_at', v_verified_at,
            'stale_order_reconciliation_receipt', v_receipt_ref,
            'attested_by', v_attested_by,
            'slots_activated', 50
        )
    );

    RETURN jsonb_build_object(
        'status', 'activated',
        'fleet_id', v_fleet.id,
        'effective_at', v_effective_at,
        'legacy_terminal_verified_at', v_verified_at,
        'slots_activated', 50
    );
END;
$$;

COMMENT ON FUNCTION rpc_shadow_fleet_activate(uuid, text, jsonb, jsonb) IS
    'Atomically activates the small_tier_v1 shadow fleet: re-verifies the '
    'legacy book is terminal (allowlist, fail-closed) inside the transaction, '
    'binds all 50 slots to unique operator-supplied pre-registered policy '
    'ids, stamps DB-now() as the effective boundary, and takes '
    'legacy_terminal_verified_at only from the operator attestation. Any '
    'violation rolls the whole step back. Idempotent: already-active returns '
    'a no-op. Operator-only (service_role).';

-- =============================================================================
-- Operator-only execution surface
-- =============================================================================
REVOKE ALL ON FUNCTION rpc_shadow_fleet_provision(uuid, text)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION rpc_shadow_fleet_activate(uuid, text, jsonb, jsonb)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION rpc_shadow_fleet_provision(uuid, text)
    TO service_role;
GRANT EXECUTE ON FUNCTION rpc_shadow_fleet_activate(uuid, text, jsonb, jsonb)
    TO service_role;
