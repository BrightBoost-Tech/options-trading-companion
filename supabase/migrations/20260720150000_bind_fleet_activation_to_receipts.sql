-- =============================================================================
-- V17-2 F-A8-FLEET-ACTIVATION-ARTIFACT-UNBOUND, scenario 5 — CLOSE receipt
-- existence. Bind the activation attestation's reconciliation receipts to the
-- durable fleet_reconciliation_receipts table INSIDE the activation transaction.
-- =============================================================================
-- NOT APPLIED BY THIS PR. Schema/RPC only; applied later via the operator-owned
-- migration procedure. Applying it changes NO fleet state, activates nothing,
-- and binds no slot — it REPLACES the activation RPC body with a strictly
-- TIGHTER one. The fleet stays INACTIVE and activation remains FORBIDDEN.
--
-- Requires 20260720140000_fleet_reconciliation_receipts.sql applied first
-- (this migration reads that table). Layers strictly on top of
-- 20260719020000_harden_shadow_fleet_activation_rpc.sql — every gate there is
-- preserved verbatim.
--
-- WHAT CHANGES (scenario 5, the only OPEN bypass after Lane-2 hardening):
--   Before: the receipt reference was checked NON-BLANK only — a fabricated /
--           nonexistent receipt was ACCEPTED (OPEN by design; no durable typed
--           receipt object existed to bind to).
--   After:  the attestation MUST carry a typed reconciliation-receipt bundle
--           (p_attestation->'reconciliation_receipts', a jsonb array). Each
--           element {receipt_id, receipt_kind, content_fingerprint} must resolve
--           to EXACTLY ONE row in fleet_reconciliation_receipts with the correct
--           user (p_user_id), effective_epoch (= the fleet epoch), receipt_kind,
--           content_fingerprint, and a present source ref — else RAISE
--           receipt_not_found. A nonexistent / wrong-user / wrong-kind /
--           wrong-epoch / wrong-fingerprint receipt now FAILS.
--
-- SMALLEST HONEST CONTRACT (multiple prerequisites, one field was not enough):
--   The pre-existing attestation carried ONE reference
--   (stale_order_reconciliation_receipt) but TWO reconciliations are cited as
--   prerequisites (prerequisite packet §1): the stale-order reconciliation
--   (fp 04317fc1…, kind stale_order) AND the seventh-row adjudication
--   (fp 5d5cd9fc…, kind manual_review). To not SILENTLY IGNORE the second, the
--   contract requires a typed BUNDLE and REQUIRED_KINDS = {stale_order,
--   manual_review}: both must be present AND validated. The bundle rides INSIDE
--   the existing p_attestation jsonb, so the RPC SIGNATURE is UNCHANGED
--   (uuid,text,jsonb,jsonb,text) — no new overload, no bypass surface. (The
--   orphan-run reconciliation (fp 40258ba9…) is job_runs hygiene, NOT part of
--   the order/position legacy-terminal boundary the activation re-verifies, so
--   it is deliberately NOT a required activation prerequisite; if listed, it is
--   still validated, never ignored.) The legacy non-blank
--   stale_order_reconciliation_receipt check is PRESERVED (belt-and-suspenders).
--
-- FAIL-CLOSED: with fleet_reconciliation_receipts empty (the D2 backfill verdict
-- is BLOCKED_RECEIPT_ID_NOT_DURABLE — no durable receipt exists), EVERY
-- activation attestation now RAISEs receipt_not_found. That is correct and
-- intended: activation stays fail-closed and FORBIDDEN until a durable receipt
-- is created by a proper receipt-writer (id + kind + epoch + full fingerprint
-- at reconciliation time) — never by rewriting the scattered prose stamps.
--
-- SIGNATURE: UNCHANGED 5-arg (uuid,text,jsonb,jsonb,text). CREATE OR REPLACE
-- preserves grants; we re-issue REVOKE/GRANT explicitly. The pre-hardening 4-arg
-- overload was dropped in 20260719020000 and is defensively re-dropped here so
-- no unbound activation path can survive in any environment.
-- =============================================================================

-- Defensive: ensure no unbound legacy overload lingers anywhere.
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
    -- scenario-5 receipt binding
    v_receipt jsonb;
    v_receipt_id text;
    v_receipt_kind text;
    v_receipt_fp text;
    v_found integer;
    v_kinds text[];
    v_required_kind text;
    v_receipt_ids jsonb;
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
    -- Legacy non-blank check PRESERVED (belt-and-suspenders). Existence is now
    -- enforced by the typed receipt bundle below (scenario 5 CLOSED).
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

    -- ── scenario 5 CLOSED: reconciliation-receipt EXISTENCE binding ─────────
    -- The attestation MUST carry a typed reconciliation-receipt bundle. Each
    -- element must resolve to EXACTLY ONE fleet_reconciliation_receipts row with
    -- the correct user + epoch + kind + content_fingerprint + present source
    -- ref. REQUIRED_KINDS {stale_order, manual_review} must both be covered.
    v_receipt_ids := p_attestation->'reconciliation_receipts';
    IF v_receipt_ids IS NULL
       OR jsonb_typeof(v_receipt_ids) <> 'array'
       OR jsonb_array_length(v_receipt_ids) = 0 THEN
        RAISE EXCEPTION
            'shadow_fleet_activate: attestation_missing_reconciliation_receipts '
            '(a typed [{receipt_id,receipt_kind,content_fingerprint},...] bundle '
            'is required; scenario 5)';
    END IF;

    v_kinds := ARRAY[]::text[];
    FOR v_receipt IN SELECT jsonb_array_elements(v_receipt_ids)
    LOOP
        v_receipt_id   := btrim(COALESCE(v_receipt->>'receipt_id', ''));
        v_receipt_kind := btrim(COALESCE(v_receipt->>'receipt_kind', ''));
        v_receipt_fp   := lower(btrim(COALESCE(v_receipt->>'content_fingerprint', '')));
        IF v_receipt_id = '' OR v_receipt_kind = '' OR v_receipt_fp = '' THEN
            RAISE EXCEPTION
                'shadow_fleet_activate: reconciliation_receipt_malformed '
                '(receipt_id, receipt_kind, content_fingerprint all required)';
        END IF;
        -- Receipt EXISTS with correct user + epoch + kind + fingerprint AND a
        -- present provenance (source_alert_id OR source_table+source_row_id).
        SELECT count(*) INTO v_found
          FROM fleet_reconciliation_receipts r
         WHERE r.receipt_id = v_receipt_id
           AND r.user_id = p_user_id
           AND r.effective_epoch = v_fleet.epoch_name
           AND r.receipt_kind = v_receipt_kind
           AND lower(r.content_fingerprint) = v_receipt_fp
           AND (r.source_alert_id IS NOT NULL
                OR (btrim(COALESCE(r.source_table, '')) <> ''
                    AND btrim(COALESCE(r.source_row_id, '')) <> ''));
        IF v_found <> 1 THEN
            RAISE EXCEPTION
                'shadow_fleet_activate: receipt_not_found '
                '(receipt_id=%, kind=%, epoch=% — no matching '
                'fleet_reconciliation_receipts row for this user/epoch/kind/'
                'fingerprint with present provenance)',
                v_receipt_id, v_receipt_kind, v_fleet.epoch_name;
        END IF;
        v_kinds := v_kinds || v_receipt_kind;
    END LOOP;

    -- Both documented prerequisite kinds must be present (never silently drop
    -- the manual_review receipt because only stale_order was cited historically).
    FOREACH v_required_kind IN ARRAY ARRAY['stale_order', 'manual_review']
    LOOP
        IF NOT (v_required_kind = ANY (v_kinds)) THEN
            RAISE EXCEPTION
                'shadow_fleet_activate: reconciliation_receipt_kind_missing (%) '
                '— REQUIRED_KINDS are {stale_order, manual_review}', v_required_kind;
        END IF;
    END LOOP;

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
    -- 50-slot binding, the operator receipt references, AND the bound
    -- reconciliation-receipt bundle (scenario 5 provenance).
    INSERT INTO risk_alerts (
        user_id, alert_type, severity, message, resolved, metadata
    ) VALUES (
        p_user_id,
        'shadow_fleet_activated',
        'info',
        'Shadow fleet small_tier_v1 ACTIVATED: 50 slots bound to '
            || 'server-derived approved registry policies; legacy book attested terminal; '
            || 'reconciliation receipts bound.',
        false,
        jsonb_build_object(
            'step', 'activate',
            'idempotency_key', p_idempotency_key,
            'fleet_id', v_fleet.id,
            'effective_at', v_effective_at,
            'legacy_terminal_verified_at', v_verified_at,
            'stale_order_reconciliation_receipt', v_receipt_ref,
            'reconciliation_receipts', v_receipt_ids,
            'reconciliation_receipt_kinds', to_jsonb(v_kinds),
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
        'reconciliation_receipt_kinds', to_jsonb(v_kinds),
        'slots_activated', 50
    );
END;
$$;

COMMENT ON FUNCTION rpc_shadow_fleet_activate(uuid, text, jsonb, jsonb, text) IS
    'Atomically activates the small_tier_v1 shadow fleet with an IN-TRANSACTION '
    'registry+epoch+manifest binding (V17-2 Lane-2) AND reconciliation-receipt '
    'EXISTENCE binding (V17-2 scenario 5). The attestation must carry a typed '
    'reconciliation-receipt bundle (p_attestation->reconciliation_receipts); '
    'each element must resolve to exactly one fleet_reconciliation_receipts row '
    'for this user + fleet epoch + kind + content_fingerprint with present '
    'provenance, and REQUIRED_KINDS {stale_order, manual_review} must both be '
    'covered, else RAISE receipt_not_found / reconciliation_receipt_kind_missing. '
    'The slot->policy binding is SERVER-DERIVED (ORDER BY policy_registration_id '
    'COLLATE "C" ASC == the client codepoint sort) under FOR UPDATE, bound off '
    'the verified v_derived_map; the recomputed binding-manifest fingerprint must '
    'equal p_expected_binding_fingerprint. Preserves the attestation gate, '
    '50-slot/$2k contract, shadow_only routing, legacy-terminal allowlist '
    're-verification, DB-now() effective boundary, and the all-or-nothing '
    '50-binding gate. Operator-only (service_role). Signature UNCHANGED (5-arg).';

-- =============================================================================
-- Operator-only execution surface (unchanged 5-arg overload)
-- =============================================================================
REVOKE ALL ON FUNCTION rpc_shadow_fleet_activate(uuid, text, jsonb, jsonb, text)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION rpc_shadow_fleet_activate(uuid, text, jsonb, jsonb, text)
    TO service_role;
