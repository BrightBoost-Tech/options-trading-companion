"""V17-2 F-A8-FLEET-ACTIVATION-ARTIFACT-UNBOUND — in-transaction binding.

Two mirrors meet here (the #1291 SQL-mirror parity pattern; no ephemeral
Postgres is available locally, so the SQL clauses are reproduced by a faithful
Python mirror that is drift-locked to the migration TEXT):

  A. CANONICAL SERIALIZATION parity. The hardened activation RPC
     (20260719020000) builds the binding-manifest canonical string
       '[' || string_agg(format('[%s,"%s"]', slot, id), ',' ORDER BY slot) || ']'
     and fingerprints it with encode(digest(...,'sha256'),'hex'). This test
     proves the REAL Python ``canonical_binding_manifest`` produces the
     byte-identical string, so client and SQL fingerprint the same bytes.

  B. THE SIX BYPASS SCENARIOS. Each of the six bypasses the unbound RPC
     ACCEPTED is now rejected — driven through the REAL service
     (``execute_activation`` — the production preflight) AND through a faithful
     Python mirror of the RPC's own clauses (the SQL is the FINAL authority, so
     a direct service-role RPC call that skips the preflight must still fail).
     Failure injected at the ORIGIN (the registry rows / the payload / the
     attested fingerprint), truth asserted at the TOP (typed refusal + zero
     rpc/writes, or the mirror RAISE + zero activation).

Scenario 5 (reconciliation-receipt EXISTENCE) is OPEN by design — there is no
durable typed receipt contract to validate against yet
(docs/review/fleet-receipt-contract-prerequisite-2026-07-19.md). The current
NON-BLANK behavior is pinned below so the gap is EXPLICIT, never silent.
"""

import re
from pathlib import Path

import pytest

from packages.quantum.policy_lab import fleet_policy_design as design
from packages.quantum.policy_lab.shadow_fleet import FLEET_EPOCH, MICRO_ACCOUNT_COUNT
from packages.quantum.services import shadow_fleet_activation as sfa

# Reuse the behavioral fake + fixtures from the Lane-3A service test module.
from packages.quantum.tests.test_shadow_fleet_activation import (
    FakeSupabase,
    USER,
    _approved_registry_rows,
    _attestation,
    _clean_activatable_fake,
    _closed_positions,
    _fleet_row,
    _micro_rows,
    _registrations,
    _terminal_orders,
)

HARDEN_MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "supabase" / "migrations"
    / "20260719020000_harden_shadow_fleet_activation_rpc.sql"
)


def _harden_sql() -> str:
    return HARDEN_MIGRATION.read_text(encoding="utf-8")


def _authorize(monkeypatch):
    monkeypatch.setenv(sfa.AUTHORIZATION_ENV, "1")


# ── A. Canonical-serialization parity (Python REAL fn ↔ SQL string builder) ──

def _sql_manifest_canonical(mapping) -> str:
    """Faithful Python mirror of the RPC's manifest string build:
    '[' || string_agg(format('[%s,"%s"]', slot, id), ',' ORDER BY slot) || ']'.
    Drift-locked to the migration text by TestHardenMigrationDriftLock."""
    norm = {int(k): v for k, v in mapping.items()}
    elems = [f'[{slot},"{norm[slot]}"]' for slot in sorted(norm)]
    return "[" + ",".join(elems) + "]"


def _fixture_mapping():
    # pol-01..pol-50 sorted ASC → slot N ← pol-{N:02d} (already sorted).
    return {s: f"pol-{s:02d}" for s in range(1, MICRO_ACCOUNT_COUNT + 1)}


def _real_mapping():
    ids = sorted(r["policy_registration_id"] for r in design.build_registrations())
    return {s: ids[s - 1] for s in range(1, MICRO_ACCOUNT_COUNT + 1)}


class TestCanonicalSerializationParity:
    @pytest.mark.parametrize(
        "mapping", [_fixture_mapping(), _real_mapping()],
        ids=["fixture_ids", "real_design_ids"],
    )
    def test_python_and_sql_manifest_bytes_identical(self, mapping):
        assert sfa.canonical_binding_manifest(mapping) == \
            _sql_manifest_canonical(mapping)

    def test_fingerprint_is_sha256_of_canonical(self):
        import hashlib
        m = _real_mapping()
        expect = hashlib.sha256(
            sfa.canonical_binding_manifest(m).encode("utf-8")).hexdigest()
        assert sfa.binding_manifest_fingerprint(m) == expect

    def test_real_registry_anchors_land_at_17_33_50(self):
        m = _real_mapping()
        assert m[17] == "aggressive_anchor"
        assert m[33] == "conservative_anchor"
        assert m[50] == "neutral_anchor"

    def test_permutation_changes_the_fingerprint(self):
        base = _real_mapping()
        swapped = dict(base)
        swapped[1], swapped[2] = base[2], base[1]
        assert sfa.binding_manifest_fingerprint(swapped) != \
            sfa.binding_manifest_fingerprint(base)

    def test_charset_guard_rejects_escaping_chars(self):
        bad = _fixture_mapping()
        bad[7] = 'pol"07'  # a quote would break JSON/SQL byte parity
        with pytest.raises(ValueError):
            sfa.canonical_binding_manifest(bad)

    def test_derive_requires_exactly_50_approved(self):
        with pytest.raises(sfa.ShadowFleetActivationError):
            sfa.derive_binding_manifest([f"pol-{s:02d}" for s in range(1, 50)])
        m = sfa.derive_binding_manifest(
            [f"pol-{s:02d}" for s in range(1, 51)])
        assert m == _fixture_mapping()


# ── A'. Collation determinism (COLLATE "C" == Python codepoint) ──────────────

class TestCollationDeterminism:
    """FIX 1. The RPC orders the derivation by ``COLLATE "C"`` (byte/codepoint),
    which equals the Python client's codepoint ``sorted`` for the id charset.
    The canary is a set spanning ``[A-Za-z0-9_-]`` with case / digit / underscore
    / hyphen contention — precisely where a locale-aware collation
    (en_US.UTF-8: case-insensitive primary weight, punctuation largely ignored)
    reorders the SAME set. No live Postgres is available, so ``COLLATE "C"``
    ordering is modelled by byte order (``s.encode()``); the drift-lock
    (TestHardenMigrationDriftLock) pins the literal ``COLLATE "C"`` in the SQL."""

    # Mixed case, a leading underscore, a leading digit, and hyphen/underscore
    # contention — codepoint order and en_US.UTF-8 order diverge on this set.
    CANARY = [
        "Zeta_01", "alpha-9", "Alpha_9", "beta-10", "beta_2",
        "gamma-1", "GAMMA_1", "_lead", "9nine", "A-dash",
    ]

    def test_collate_c_equals_python_codepoint_ordering(self):
        # COLLATE "C" is byte order; every canary id is ASCII, so byte order ==
        # Unicode codepoint order == Python sorted(). This is the invariant the
        # SQL COLLATE "C" pin guarantees against the client's codepoint sort.
        codepoint = sorted(self.CANARY)
        collate_c = sorted(self.CANARY, key=lambda s: s.encode("utf-8"))
        assert codepoint == collate_c

    def test_canary_reorders_under_a_locale_aware_collation(self):
        # A case-insensitive (locale-like) ordering reorders the SAME canary —
        # proving the collation choice is load-bearing and COLLATE "C" /
        # codepoint is the deterministic one the fingerprint depends on. Without
        # the pin, the SQL derivation could silently diverge from the attested
        # (codepoint) fingerprint and brick activation.
        codepoint = sorted(self.CANARY)
        locale_like = sorted(self.CANARY, key=str.lower)
        assert codepoint != locale_like

    def test_real_registry_fingerprint_unchanged_under_collate_c(self):
        # COLLATE "C" == codepoint for the real 50 approved ids, so the derived
        # binding and its fingerprint are byte-identical to the pre-collation
        # value — the pin is a structural guarantee, not a value change.
        assert sfa.binding_manifest_fingerprint(_real_mapping()) == \
            "1cd004b5167429cf469652bdd04b16d522b0f8b87d98d5a9aa68481c19231a76"


# ── B. Faithful Python mirror of the RPC's binding decision (drift-locked) ───

class RpcRaise(Exception):
    """A modelled RAISE from the activation RPC (the SQL is the final
    authority; this mirror reproduces its binding clauses)."""

    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def _rpc_activate_mirror(approved_rows, epoch, p_policy_registrations,
                         p_expected_binding_fingerprint):
    """Reproduce the RPC's registry-binding clauses (the ones a direct
    service-role call would hit). Returns the server-derived slot→id map on
    success; RAISEs (RpcRaise) exactly where the SQL RAISEs. Reads the approved
    set at CALL time — modelling the in-txn re-read that closes the TOCTOU."""
    if p_expected_binding_fingerprint is None \
            or not str(p_expected_binding_fingerprint).strip():
        raise RpcRaise("expected_binding_fingerprint_required")
    expected = str(p_expected_binding_fingerprint).strip().lower()

    approved = [r for r in approved_rows
                if r.get("approval_status") == "approved"
                and r.get("effective_epoch") == epoch]
    if len(approved) != MICRO_ACCOUNT_COUNT:
        raise RpcRaise("registry_not_exactly_50_approved")

    for r in approved:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", r["policy_registration_id"]):
            raise RpcRaise("registry_id_charset_invalid")

    ordered = sorted(r["policy_registration_id"] for r in approved)
    derived = {s: ordered[s - 1] for s in range(1, MICRO_ACCOUNT_COUNT + 1)}
    manifest_canonical = _sql_manifest_canonical(derived)
    import hashlib
    derived_fp = hashlib.sha256(manifest_canonical.encode("utf-8")).hexdigest()

    if derived_fp != expected:
        raise RpcRaise("binding_fingerprint_mismatch")

    payload_canonical = (
        "[" + ",".join(
            f'[{int(k)},"{str(v).strip()}"]'
            for k, v in sorted(p_policy_registrations.items(),
                               key=lambda kv: int(kv[0])))
        + "]"
    )
    if payload_canonical != manifest_canonical:
        raise RpcRaise("payload_binding_mismatch")
    return derived


def _wire(mapping):
    """The wire shape the RPC/route sees: {"1".."50": id}."""
    return {str(s): rid for s, rid in mapping.items()}


class TestRpcMirrorIsFinalAuthority:
    def test_correct_reviewed_mapping_binds_all_50(self):
        rows = _approved_registry_rows(_real_mapping())
        m = _real_mapping()
        fp = sfa.binding_manifest_fingerprint(m)
        derived = _rpc_activate_mirror(rows, FLEET_EPOCH, _wire(m), fp)
        assert derived == m and len(derived) == 50

    def test_direct_service_role_bypass_permutation_fails(self):
        """A direct service-role RPC call that SKIPS the Python preflight and
        submits a permuted slot map (with the correct fingerprint) still fails
        at the SQL layer — the server derivation is authoritative."""
        rows = _approved_registry_rows(_real_mapping())
        m = _real_mapping()
        fp = sfa.binding_manifest_fingerprint(m)  # correct fingerprint
        permuted = dict(m)
        permuted[1], permuted[2] = m[2], m[1]
        with pytest.raises(RpcRaise) as exc:
            _rpc_activate_mirror(rows, FLEET_EPOCH, _wire(permuted), fp)
        assert exc.value.reason == "payload_binding_mismatch"

    def test_toctou_row_retired_after_readiness_fails_at_bind(self):
        """Readiness saw 50 approved; a row is retired BEFORE the RPC binds.
        The RPC re-reads the approved set under lock at bind time → 49 → RAISE.
        (The mirror reads approved at call time, modelling the in-txn re-read.)"""
        rows = _approved_registry_rows(_real_mapping())
        m = _real_mapping()
        fp = sfa.binding_manifest_fingerprint(m)
        # readiness-time snapshot binds fine:
        assert _rpc_activate_mirror(rows, FLEET_EPOCH, _wire(m), fp) == m
        # a concurrent retire lands between readiness and bind:
        rows[0]["approval_status"] = "retired"
        with pytest.raises(RpcRaise) as exc:
            _rpc_activate_mirror(rows, FLEET_EPOCH, _wire(m), fp)
        assert exc.value.reason == "registry_not_exactly_50_approved"

    def test_wrong_fingerprint_fails_at_rpc(self):
        rows = _approved_registry_rows(_real_mapping())
        m = _real_mapping()
        with pytest.raises(RpcRaise) as exc:
            _rpc_activate_mirror(rows, FLEET_EPOCH, _wire(m), "0" * 64)
        assert exc.value.reason == "binding_fingerprint_mismatch"

    def test_missing_fingerprint_fails_at_rpc(self):
        rows = _approved_registry_rows(_real_mapping())
        m = _real_mapping()
        with pytest.raises(RpcRaise) as exc:
            _rpc_activate_mirror(rows, FLEET_EPOCH, _wire(m), "")
        assert exc.value.reason == "expected_binding_fingerprint_required"

    def test_wrong_epoch_registry_fails_at_rpc(self):
        rows = _approved_registry_rows(_real_mapping(), epoch="other_epoch")
        m = _real_mapping()
        fp = sfa.binding_manifest_fingerprint(m)
        with pytest.raises(RpcRaise) as exc:
            _rpc_activate_mirror(rows, FLEET_EPOCH, _wire(m), fp)
        assert exc.value.reason == "registry_not_exactly_50_approved"


# ── B'. Same scenarios through the REAL production preflight (service) ───────

class TestServicePreflightRejects:
    def _fake(self, registrations_rows=None):
        if registrations_rows is None:
            registrations_rows = _approved_registry_rows(_registrations())
        return FakeSupabase(
            fleets=[_fleet_row()], micro_accounts=_micro_rows(),
            orders=_terminal_orders(), positions=_closed_positions(),
            registrations=registrations_rows,
        )

    def test_permutation_blocked_zero_rpc(self, monkeypatch):
        _authorize(monkeypatch)
        fake = self._fake()
        permuted = _registrations()
        permuted[1], permuted[2] = permuted[2], permuted[1]
        with pytest.raises(sfa.BindingManifestMismatch):
            sfa.execute_activation(
                fake, USER, idempotency_key="k",
                policy_registrations=permuted,
                attestation=_attestation(), confirm=sfa.CONFIRM_LITERAL)
        assert fake.rpc_calls == [] and fake.writes == []

    def test_unregistered_id_blocked_zero_rpc(self, monkeypatch):
        _authorize(monkeypatch)
        fake = self._fake()
        regs = _registrations()
        regs[50] = "pol-does-not-exist"
        with pytest.raises(sfa.ReadinessBlocked) as exc:
            sfa.execute_activation(
                fake, USER, idempotency_key="k",
                policy_registrations=regs,
                attestation=_attestation(), confirm=sfa.CONFIRM_LITERAL)
        assert exc.value.outcome == sfa.POLICY_NOT_REGISTERED
        assert fake.rpc_calls == [] and fake.writes == []

    def test_retired_id_blocked_zero_rpc(self, monkeypatch):
        _authorize(monkeypatch)
        rows = _approved_registry_rows(_registrations())
        rows[0]["approval_status"] = "retired"
        fake = self._fake(registrations_rows=rows)
        with pytest.raises(sfa.ReadinessBlocked) as exc:
            sfa.execute_activation(
                fake, USER, idempotency_key="k",
                policy_registrations=_registrations(),
                attestation=_attestation(), confirm=sfa.CONFIRM_LITERAL)
        assert exc.value.outcome == sfa.POLICY_NOT_APPROVED
        assert fake.rpc_calls == [] and fake.writes == []

    def test_wrong_epoch_blocked_zero_rpc(self, monkeypatch):
        _authorize(monkeypatch)
        rows = _approved_registry_rows(_registrations(), epoch="other_epoch")
        fake = self._fake(registrations_rows=rows)
        with pytest.raises(sfa.ReadinessBlocked) as exc:
            sfa.execute_activation(
                fake, USER, idempotency_key="k",
                policy_registrations=_registrations(),
                attestation=_attestation(), confirm=sfa.CONFIRM_LITERAL)
        assert exc.value.outcome == sfa.POLICY_NOT_REGISTERED
        assert fake.rpc_calls == [] and fake.writes == []

    def test_wrong_fingerprint_blocked_zero_rpc(self, monkeypatch):
        _authorize(monkeypatch)
        fake = self._fake()
        att = _attestation()
        att["expected_binding_fingerprint"] = "a" * 64  # wrong, valid shape
        with pytest.raises(sfa.BindingManifestMismatch):
            sfa.execute_activation(
                fake, USER, idempotency_key="k",
                policy_registrations=_registrations(),
                attestation=att, confirm=sfa.CONFIRM_LITERAL)
        assert fake.rpc_calls == [] and fake.writes == []

    def test_missing_fingerprint_blocked_zero_rpc(self, monkeypatch):
        _authorize(monkeypatch)
        fake = self._fake()
        att = _attestation()
        del att["expected_binding_fingerprint"]
        with pytest.raises(sfa.AttestationInvalid):
            sfa.execute_activation(
                fake, USER, idempotency_key="k",
                policy_registrations=_registrations(),
                attestation=att, confirm=sfa.CONFIRM_LITERAL)
        assert fake.rpc_calls == [] and fake.writes == []

    def test_more_than_50_approved_blocked_zero_rpc(self, monkeypatch):
        """readiness passes (the 50 supplied ids are all approved) but the
        registry has 51 approved rows → the server derivation is ambiguous →
        derive raises, RPC never called."""
        _authorize(monkeypatch)
        rows = _approved_registry_rows(_registrations())
        rows.append({"policy_registration_id": "pol-51",
                     "approval_status": "approved",
                     "effective_epoch": "small_tier_v1"})
        fake = self._fake(registrations_rows=rows)
        with pytest.raises(sfa.ShadowFleetActivationError):
            sfa.execute_activation(
                fake, USER, idempotency_key="k",
                policy_registrations=_registrations(),
                attestation=_attestation(), confirm=sfa.CONFIRM_LITERAL)
        assert fake.rpc_calls == [] and fake.writes == []

    def test_correct_mapping_reaches_single_rpc_with_fingerprint(self, monkeypatch):
        _authorize(monkeypatch)
        fake = _clean_activatable_fake()
        result = sfa.execute_activation(
            fake, USER, idempotency_key="k",
            policy_registrations=_registrations(),
            attestation=_attestation(), confirm=sfa.CONFIRM_LITERAL)
        assert result["status"] == "rpc_complete"
        assert len(fake.rpc_calls) == 1
        params = fake.rpc_calls[0]["params"]
        assert params["p_expected_binding_fingerprint"] == \
            sfa.binding_manifest_fingerprint(_registrations())
        assert fake.writes == []

    def test_already_active_replay_is_idempotent_zero_writes(self, monkeypatch):
        _authorize(monkeypatch)
        fake = FakeSupabase(
            fleets=[_fleet_row(status="active",
                               effective_at="2026-07-19T15:00:00+00:00")],
            micro_accounts=_micro_rows(state="active"),
            orders=_terminal_orders(), positions=_closed_positions(),
            registrations=_approved_registry_rows(_registrations()))
        result = sfa.execute_activation(
            fake, USER, idempotency_key="k",
            policy_registrations=_registrations(),
            attestation=_attestation(), confirm=sfa.CONFIRM_LITERAL)
        assert result["status"] == sfa.ALREADY_ACTIVE
        assert result["writes_performed"] == 0
        assert fake.rpc_calls == [] and fake.writes == []


# ── Dry-run reports the server-derived fingerprint (owner-facing shape) ──────

class TestPlanReportsFingerprint:
    def test_plan_activation_reports_derived_fingerprint_and_match(self):
        plan = sfa.plan_activation(
            _clean_activatable_fake(), USER, idempotency_key="k",
            policy_registrations=_registrations(), attestation=_attestation())
        expect = sfa.binding_manifest_fingerprint(_registrations())
        assert plan["derived_binding_fingerprint"] == expect
        assert plan["binding_fingerprint_matches"] is True
        assert plan["would_execute"] is True
        assert plan["plan"]["binding_rule"] == \
            "server_derived_order_by_policy_registration_id_asc"

    def test_plan_activation_flags_wrong_fingerprint(self):
        att = _attestation()
        att["expected_binding_fingerprint"] = "b" * 64
        plan = sfa.plan_activation(
            _clean_activatable_fake(), USER, idempotency_key="k",
            policy_registrations=_registrations(), attestation=att)
        assert plan["binding_fingerprint_matches"] is False
        assert plan["would_execute"] is False


# ── Scenario 5 (receipt existence) — OPEN, but PINNED, never silent ──────────

class TestScenario5ReceiptExistenceOpen:
    def test_receipt_reference_nonblank_is_enforced(self):
        att = _attestation()
        att["stale_order_reconciliation_receipt"] = "   "
        with pytest.raises(sfa.AttestationInvalid):
            sfa.validate_attestation(att)

    def test_receipt_existence_is_not_yet_enforced_OPEN(self):
        """SCENARIO 5 OPEN. There is no durable typed receipt contract, so a
        syntactically-valid-but-FABRICATED (nonexistent) receipt reference is
        currently ACCEPTED — only non-blank is checked. This test PINS that
        gap so it is explicit, not silent. Closing it requires the operator to
        adopt the contract designed in
        docs/review/fleet-receipt-contract-prerequisite-2026-07-19.md; until
        then, activation must not proceed on receipt existence alone."""
        att = _attestation()
        att["stale_order_reconciliation_receipt"] = "risk_alerts:does-not-exist-999"
        normalized = sfa.validate_attestation(att)  # accepted today (OPEN)
        assert normalized["stale_order_reconciliation_receipt"] == \
            "risk_alerts:does-not-exist-999"


# ── Migration drift-lock: the RPC TEXT still carries every hardening clause ──

class TestHardenMigrationDriftLock:
    @pytest.fixture(scope="class")
    def sql(self):
        return _harden_sql()

    def test_old_unbound_overload_is_dropped(self, sql):
        assert re.search(
            r"DROP\s+FUNCTION\s+IF\s+EXISTS\s+"
            r"rpc_shadow_fleet_activate\(uuid,\s*text,\s*jsonb,\s*jsonb\)",
            sql)

    def test_new_overload_takes_expected_binding_fingerprint(self, sql):
        assert re.search(
            r"CREATE\s+OR\s+REPLACE\s+FUNCTION\s+rpc_shadow_fleet_activate\(",
            sql)
        assert "p_expected_binding_fingerprint text" in sql

    def test_grants_only_service_role_on_new_overload(self, sql):
        assert re.search(
            r"REVOKE\s+ALL\s+ON\s+FUNCTION\s+"
            r"rpc_shadow_fleet_activate\(uuid,\s*text,\s*jsonb,\s*jsonb,\s*text\)"
            r"\s+FROM\s+PUBLIC,\s*anon,\s*authenticated", sql)
        assert re.search(
            r"GRANT\s+EXECUTE\s+ON\s+FUNCTION\s+"
            r"rpc_shadow_fleet_activate\(uuid,\s*text,\s*jsonb,\s*jsonb,\s*text\)"
            r"\s+TO\s+service_role", sql)

    def test_fixed_search_path(self, sql):
        assert "SET search_path = public, extensions, pg_temp" in sql

    def test_server_derived_order_is_collation_pinned(self, sql):
        # FIX 1: the derivation orders by COLLATE "C" (byte/codepoint), matching
        # the Python client's codepoint sort structurally — NOT a bare, locale-
        # dependent ORDER BY. No un-collated id ordering may remain.
        assert 'ORDER BY policy_registration_id COLLATE "C" ASC' in sql
        assert "ORDER BY policy_registration_id ASC" not in sql  # no bare order
        # The audit registry fingerprint is collation-pinned too.
        assert 'ORDER BY policy_registration_id COLLATE "C")' in sql

    def test_bind_update_driven_from_verified_derived_map(self, sql):
        # FIX 2: the bind UPDATE reads the already-fingerprinted v_derived_map,
        # NOT a fresh re-query — so a concurrent approved INSERT can't shift the
        # committed binding away from the attested fingerprint.
        code = "\n".join(l.split("--", 1)[0] for l in sql.splitlines())
        assert "jsonb_each_text(v_derived_map)" in code
        # The bind UPDATE targets shadow_micro_accounts from the derived map.
        assert re.search(
            r"UPDATE\s+shadow_micro_accounts\s+sma[\s\S]*?"
            r"FROM\s*\(\s*SELECT\s+\(r\.key\)::int\s+AS\s+slot,\s+r\.value\s+AS\s+pid"
            r"\s+FROM\s+jsonb_each_text\(v_derived_map\)\s+r\s*\)\s+d",
            code)

    def test_canonical_string_builder_matches_python(self, sql):
        # FIX 3: pin BOTH the inner element format() AND the outer wrapper
        # ('[' || string_agg(..., ',' ORDER BY slot) || ']') the Python mirror
        # reproduces — the full serialization, not just the element.
        assert 'format(\'[%s,"%s"]\', slot, policy_registration_id)' in sql
        code = "\n".join(l.split("--", 1)[0] for l in sql.splitlines())
        assert re.search(
            r"'\['\s*\|\|\s*string_agg\(\s*"
            r"format\('\[%s,\"%s\"\]', slot, policy_registration_id\),\s*"
            r"','\s+ORDER BY slot\)\s*\|\|\s*'\]'",
            code)

    def test_charset_guard_present(self, sql):
        assert "'^[A-Za-z0-9_-]+$'" in sql

    def test_toctou_for_update_lock_on_approved(self, sql):
        code = "\n".join(l.split("--", 1)[0] for l in sql.splitlines())
        # The approved registry rows are locked FOR UPDATE before derivation.
        assert re.search(
            r"FROM\s+policy_registrations\s+WHERE\s+effective_epoch\s*=\s*"
            r"v_fleet\.epoch_name\s+AND\s+approval_status\s*=\s*'approved'\s+"
            r"FOR\s+UPDATE", code, re.S)

    def test_exactly_50_approved_and_mismatch_raises(self, sql):
        for clause in (
            "registry_not_exactly_50_approved",
            "binding_fingerprint_mismatch",
            "payload_binding_mismatch",
        ):
            assert clause in sql, clause

    def test_fingerprint_uses_sha256_digest(self, sql):
        assert "extensions.digest(v_manifest_canonical, 'sha256')" in sql

    def test_all_or_nothing_50_binding_gate_preserved(self, sql):
        code = "\n".join(l.split("--", 1)[0] for l in sql.splitlines())
        assert "GET DIAGNOSTICS v_updated = ROW_COUNT" in code
        assert "v_updated <> 50" in code
        assert not re.search(r"^\s*COMMIT\s*;", code, re.M)

    def test_legacy_rows_never_rewritten(self, sql):
        code = "\n".join(l.split("--", 1)[0] for l in sql.splitlines())
        assert not re.search(r"UPDATE\s+paper_orders", code, re.I)
        assert not re.search(r"DELETE\s+FROM\s+paper_orders", code, re.I)
        assert not re.search(r"UPDATE\s+paper_positions", code, re.I)
        assert not re.search(r"DELETE\s+FROM\s+paper_positions", code, re.I)

    def test_shadow_only_never_live_eligible(self, sql):
        code = "\n".join(l.split("--", 1)[0] for l in sql.splitlines())
        assert "'shadow_only'" in code
        assert "'live_eligible'" not in code


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
