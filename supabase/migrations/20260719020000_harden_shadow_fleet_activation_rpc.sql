-- =============================================================================
-- V17-2 F-A8-FLEET-ACTIVATION-ARTIFACT-UNBOUND (Lane 2 hardening)
-- Bind registry + epoch + manifest INSIDE the activation transaction.
-- =============================================================================
-- NOT APPLIED BY THIS PR. Schema/RPC only; applied later via the operator-owned
-- migration procedure (docs/migration_procedure.md). Applying it changes NO
-- fleet state, activates nothing, and binds no slot — it only REPLACES the
-- activation RPC with a hardened overload. The fleet stays INACTIVE.
--
-- WHY: the applied rpc_shadow_fleet_activate (20260717090000) validated only
-- the STRUCTURE of the operator's slot->id payload (50 / slots 1..50 / unique /
-- non-blank). It never proved those ids were the APPROVED registry rows for the
-- fleet epoch, never derived the binding from the registry itself, and carried
-- NO manifest fingerprint. Six bypasses ACCEPTED: (1) a permuted slot->id map,
-- (2) structurally-valid but UNREGISTERED ids, (3) draft/retired/revoked ids,
-- (4) a row retired mid-flight after readiness, (5) a fabricated reconciliation
-- receipt (see scenario 5 below — still OPEN), (6) a wrong binding manifest.
--
-- THE FIX (all inside the single activation transaction):
--   * The binding is SERVER-DERIVED, not trusted from the payload: slot N <- the
--     Nth of the 50 approved policy_registrations rows for the fleet epoch,
--     ORDER BY policy_registration_id COLLATE "C" ASC. This structurally
--     eliminates bypasses (1)(2)(3): a permutation, an unregistered id, or a
--     draft/retired/revoked id can never equal the derived set. COLLATE "C" is
--     byte/codepoint order, matching the Python client's codepoint `sorted`
--     EXACTLY — not merely coincidentally under the DB default en_US.UTF-8 — so
--     a glibc collation-version change or a future case/underscore-contended id
--     set can never silently reorder the SQL derivation vs the attested
--     (codepoint) fingerprint and permanently brick activation.
--   * The approved rows are LOCKED (FOR UPDATE) before derivation, and count +
--     derivation + binding all read that locked set — closing bypass (4)
--     (mid-flight retirement TOCTOU) by re-reading under lock in-txn. The bind
--     UPDATE is driven off the already-verified/fingerprinted v_derived_map (not
--     a fresh re-query), so a concurrent approved-row INSERT under READ
--     COMMITTED cannot shift the committed binding away from the fingerprinted
--     mapping.
--   * A binding-manifest fingerprint is recomputed server-side over the derived
--     mapping and must equal the operator-attested p_expected_binding_fingerprint
--     (new required param) — closing bypass (6). The canonical serialization is
--     shared, byte-for-byte, with the Python client
--     (packages/quantum/services/shadow_fleet_activation.py
--     canonical_binding_manifest / binding_manifest_fingerprint): a compact JSON
--     array of [slot_number,"policy_registration_id"] pairs ORDER BY slot,
--     SHA-256 hex. Ids are charset-guarded ([A-Za-z0-9_-]) so json.dumps never
--     escapes and this string builder emits verbatim — no escaping divergence.
--   * The operator payload (if supplied) must EQUAL the server-derived binding
--     (belt-and-suspenders); the server derivation is authoritative.
--   * scenario 5 (reconciliation-receipt EXISTENCE) stays a non-blank check
--     only — there is no durable typed receipt contract to validate against yet.
--     It is OPEN by design; see
--     docs/review/fleet-receipt-contract-prerequisite-2026-07-19.md. Until the
--     operator adopts that contract, receipt-existence binding cannot be
--     enforced and activation must not proceed on that basis alone.
--
-- Preserved from 20260717090000 verbatim: attestation gate, 50-slot / $2k
-- contract, shadow_only routing, legacy-terminal allowlist re-verification,
-- DB-now() effective boundary, GET DIAGNOSTICS all-or-nothing 50-binding gate,
-- idempotent already-active no-op, operator-only (service_role) grants, legacy
-- rows never rewritten.
--
-- SIGNATURE CHANGE: this adds p_expected_binding_fingerprint, so the callable
-- overload changes from (uuid,text,jsonb,jsonb) to (uuid,text,jsonb,jsonb,text).
-- The old 4-arg overload is DROPPED in this same migration so no bypass overload
-- (unbound activation) survives.
-- =============================================================================

-- Remove the pre-hardening overload so no unbound activation path remains.
DROP FUNCTION IF EXISTS rpc_shadow_fleet_activate(uuid, text, jsonb, jsonb);

CREATE OR REPLACE FUNCTION rpc_shadow_fleet_activate(
    p_user_id uuid,
    p_idempotency_key text,
    p_policy_registrations jsonb,
    p_attestation jsonb,
    p_expected_binding_fingerprint text
)
RETURNS jsonb
LANGUAGE plpgsql
-- Fixed, safe search_path (no mutable/implicit resolution); digest() is fully
-- schema-qualified below regardless.
SET search_path = public, extensions, pg_temp
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
    v_expected_fp text;
    v_derived_fp text;
    v_registry_fp text;
    v_manifest_canonical text;
    v_payload_canonical text;
    v_registry_canonical text;
    v_derived_map jsonb;
    v_schema_versions integer[];
    v_bad_id text;
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
    -- scenario 5: EXISTENCE cannot be enforced yet (no durable typed receipt
    -- contract). Non-blank is the strongest check available today — OPEN by
    -- design (docs/review/fleet-receipt-contract-prerequisite-2026-07-19.md).
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

    -- Operator-attested binding fingerprint (required; NEVER defaulted).
    IF p_expected_binding_fingerprint IS NULL
       OR btrim(p_expected_binding_fingerprint) = '' THEN
        RAISE EXCEPTION
            'shadow_fleet_activate: expected_binding_fingerprint_required';
    END IF;
    v_expected_fp := lower(btrim(p_expected_binding_fingerprint));

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
    -- Retained STRUCTURAL validation of the operator payload. The AUTHORITATIVE
    -- binding is derived below; these clauses reject a malformed payload early.
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

    -- ── Registry binding (SERVER-AUTHORITATIVE; the payload is only checked) ─
    -- Lock the approved registry rows for this epoch so their approval_status
    -- cannot change (retire/revoke) between derivation and binding — closes the
    -- mid-flight-retirement TOCTOU. Every read below uses this locked set.
    PERFORM 1
       FROM policy_registrations
      WHERE effective_epoch = v_fleet.epoch_name
        AND approval_status = 'approved'
      FOR UPDATE;

    -- Exactly 50 approved rows must exist (the fleet has exactly 50 slots; an
    -- ambiguous count can never bind).
    SELECT COUNT(*) INTO v_count
      FROM policy_registrations
     WHERE effective_epoch = v_fleet.epoch_name
       AND approval_status = 'approved';
    IF v_count <> 50 THEN
        RAISE EXCEPTION
            'shadow_fleet_activate: registry_not_exactly_50_approved '
            '(% approved for epoch %)', v_count, v_fleet.epoch_name;
    END IF;

    -- Canonical-serialization charset guard: every approved id must match the
    -- shared charset so the SQL canonical string is byte-identical to the
    -- Python client's json.dumps (no escaping divergence). Fail-closed.
    SELECT policy_registration_id INTO v_bad_id
      FROM policy_registrations
     WHERE effective_epoch = v_fleet.epoch_name
       AND approval_status = 'approved'
       AND policy_registration_id !~ '^[A-Za-z0-9_-]+$'
     LIMIT 1;
    IF v_bad_id IS NOT NULL THEN
        RAISE EXCEPTION
            'shadow_fleet_activate: registry_id_charset_invalid (%)', v_bad_id;
    END IF;

    -- Server-derived binding: slot N <- the Nth approved id ORDER BY
    -- policy_registration_id COLLATE "C" ASC. Derive the map AND the canonical
    -- manifest string in one pass. The canonical string mirrors the client's
    -- canonical_binding_manifest byte-for-byte:
    --   [[<slot>,"<id>"],...]  (compact, ORDER BY slot).
    -- COLLATE "C" is byte/codepoint order; the client sorts ids by Python
    -- codepoint (str `sorted`). Pinning "C" makes the two structurally equal
    -- (not merely coincidentally equal under the DB's default en_US.UTF-8) so a
    -- glibc collation-version change or a future case/underscore-contended id
    -- set can never silently reorder the SQL derivation out from under the
    -- operator-attested (codepoint) fingerprint.
    WITH approved AS (
        SELECT policy_registration_id,
               row_number() OVER (
                   ORDER BY policy_registration_id COLLATE "C" ASC) AS slot
          FROM policy_registrations
         WHERE effective_epoch = v_fleet.epoch_name
           AND approval_status = 'approved'
    )
    SELECT
        jsonb_object_agg(slot::text, policy_registration_id),
        '[' || string_agg(
                   format('[%s,"%s"]', slot, policy_registration_id),
                   ',' ORDER BY slot)
             || ']'
      INTO v_derived_map, v_manifest_canonical
      FROM approved;

    v_derived_fp := encode(
        extensions.digest(v_manifest_canonical, 'sha256'), 'hex');

    -- Operator-attested fingerprint must equal the server derivation.
    IF v_derived_fp <> v_expected_fp THEN
        RAISE EXCEPTION
            'shadow_fleet_activate: binding_fingerprint_mismatch '
            '(expected %, server-derived %)', v_expected_fp, v_derived_fp;
    END IF;

    -- Belt-and-suspenders: the operator slot map must EQUAL the server-derived
    -- binding. A permutation, an unregistered id, or a draft/retired id can
    -- never reproduce the derived canonical string.
    SELECT '[' || string_agg(
                   format('[%s,"%s"]', (r.key)::int, btrim(r.value)),
                   ',' ORDER BY (r.key)::int)
             || ']'
      INTO v_payload_canonical
      FROM jsonb_each_text(p_policy_registrations) r;
    IF v_payload_canonical IS DISTINCT FROM v_manifest_canonical THEN
        RAISE EXCEPTION
            'shadow_fleet_activate: payload_binding_mismatch '
            '(operator slot map != server-derived ORDER BY '
            'policy_registration_id COLLATE "C" ASC binding)';
    END IF;

    -- Registry-content fingerprint (audit-only; NOT operator-attested): binds
    -- the exact parameterization identity behind the ids, ORDER BY id (same
    -- COLLATE "C" determinism as the binding derivation).
    SELECT
        '[' || string_agg(
                   format('["%s","%s"]', policy_registration_id, config_hash),
                   ',' ORDER BY policy_registration_id COLLATE "C")
             || ']',
        array_agg(DISTINCT schema_version ORDER BY schema_version)
      INTO v_registry_canonical, v_schema_versions
      FROM policy_registrations
     WHERE effective_epoch = v_fleet.epoch_name
       AND approval_status = 'approved';
    v_registry_fp := encode(
        extensions.digest(v_registry_canonical, 'sha256'), 'hex');

    -- ── Effective boundary: DB time, captured once, same transaction ────────
    v_effective_at := now();

    -- Bind from the ALREADY-VERIFIED / ALREADY-FINGERPRINTED v_derived_map — NOT
    -- a fresh re-query of policy_registrations. Under READ COMMITTED a
    -- concurrent approved-row INSERT between the fingerprint check above and
    -- this UPDATE could otherwise shift the derivation (still exactly 50 rows,
    -- so the count gate would pass) while the receipt records the stale
    -- fingerprint. Driving the bind off v_derived_map makes the COMMITTED
    -- binding provably the mapping the attested fingerprint was computed over.
    -- (The approved rows remain locked FOR UPDATE from above.)
    UPDATE shadow_micro_accounts sma
       SET policy_registration_id = d.pid,
           state = 'active',
           activated_at = v_effective_at
      FROM (
          SELECT (r.key)::int AS slot, r.value AS pid
            FROM jsonb_each_text(v_derived_map) r
      ) d
     WHERE sma.fleet_id = v_fleet.id
       AND sma.slot_number = d.slot
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

    -- Audit receipt (info row; same transaction as the transition). Records the
    -- manifest fingerprint, registry fingerprint/versions, effective epoch, the
    -- 50-slot binding, and the operator receipt references.
    INSERT INTO risk_alerts (
        user_id, alert_type, severity, message, resolved, metadata
    ) VALUES (
        p_user_id,
        'shadow_fleet_activated',
        'info',
        'Shadow fleet small_tier_v1 ACTIVATED: 50 slots bound to '
            || 'server-derived approved registry policies; legacy book attested terminal.',
        false,
        jsonb_build_object(
            'step', 'activate',
            'idempotency_key', p_idempotency_key,
            'fleet_id', v_fleet.id,
            'effective_at', v_effective_at,
            'legacy_terminal_verified_at', v_verified_at,
            'stale_order_reconciliation_receipt', v_receipt_ref,
            'attested_by', v_attested_by,
            'binding_manifest_fingerprint', v_derived_fp,
            'registry_config_fingerprint', v_registry_fp,
            'registry_effective_epoch', v_fleet.epoch_name,
            'registry_schema_versions', to_jsonb(v_schema_versions),
            'binding_slot_map', v_derived_map,
            'slots_activated', 50
        )
    );

    RETURN jsonb_build_object(
        'status', 'activated',
        'fleet_id', v_fleet.id,
        'effective_at', v_effective_at,
        'legacy_terminal_verified_at', v_verified_at,
        'binding_manifest_fingerprint', v_derived_fp,
        'registry_config_fingerprint', v_registry_fp,
        'slots_activated', 50
    );
END;
$$;

COMMENT ON FUNCTION rpc_shadow_fleet_activate(uuid, text, jsonb, jsonb, text) IS
    'Atomically activates the small_tier_v1 shadow fleet with an IN-TRANSACTION '
    'registry+epoch+manifest binding (V17-2). The slot->policy binding is '
    'SERVER-DERIVED (slot N <- Nth approved policy_registrations id for the '
    'fleet epoch, ORDER BY policy_registration_id COLLATE "C" ASC == the '
    'client codepoint sort) under a FOR UPDATE lock, bound off the verified '
    'v_derived_map, never trusted from the payload; a recomputed '
    'binding-manifest fingerprint '
    'must equal the operator-attested p_expected_binding_fingerprint (canonical '
    'serialization shared byte-for-byte with the Python client); the operator '
    'payload must equal the derived binding. Preserves the attestation gate, '
    '50-slot/$2k contract, shadow_only routing, legacy-terminal allowlist '
    're-verification, DB-now() effective boundary, and the all-or-nothing '
    '50-binding gate. Operator-only (service_role). Scenario 5 (receipt '
    'existence) remains a non-blank check only — OPEN, see the prerequisite '
    'packet.';

-- =============================================================================
-- Operator-only execution surface (hardened overload)
-- =============================================================================
REVOKE ALL ON FUNCTION rpc_shadow_fleet_activate(uuid, text, jsonb, jsonb, text)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION rpc_shadow_fleet_activate(uuid, text, jsonb, jsonb, text)
    TO service_role;
