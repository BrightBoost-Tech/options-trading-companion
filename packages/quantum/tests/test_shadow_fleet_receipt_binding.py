"""V17-2 F-A8-FLEET-ACTIVATION-ARTIFACT-UNBOUND, scenario 5 — receipt EXISTENCE.

Option-A immutable reconciliation-receipt contract + activation binding. Two
mirrors meet here (the #1291 SQL-mirror parity pattern; no ephemeral Postgres is
available locally, so the RPC's receipt clauses are reproduced by a faithful
Python mirror drift-locked to the migration TEXT — the SQL is the FINAL
authority):

  A. THE RPC RECEIPT-BINDING CLAUSES. The activation RPC
     (20260720150000_bind_fleet_activation_to_receipts.sql) requires a typed
     reconciliation-receipt bundle in the attestation; each element must resolve
     to EXACTLY ONE fleet_reconciliation_receipts row for the activating user +
     fleet epoch + kind + content_fingerprint with a present provenance, and both
     REQUIRED_KINDS {stale_order, manual_review} must be covered — else
     receipt_not_found / reconciliation_receipt_kind_missing. A DIRECT
     service-role RPC call that skips the Python preflight is still gated by
     these clauses (the SQL is authoritative). Failure injected at the ORIGIN
     (the receipt rows / the attested bundle), truth asserted at the TOP (typed
     RAISE + no activation).

  B. THE REAL SERVICE PREFLIGHT. execute_activation validates the bundle
     STRUCTURE and threads it to the RPC; a structurally-invalid bundle fails
     before any RPC call (zero writes), and a server-side receipt_not_found
     leaves zero client-side writes (fleet stays inactive).

Plus migration drift-locks pinning the D1 schema (immutability / RLS / checks)
and the D3 RPC (receipt clauses + every preserved prior gate) against the file
TEXT, so a contract change breaks the build, not the fleet.

Activation remains FORBIDDEN: nothing here calls the production RPC or writes any
production row.
"""

import re
from pathlib import Path

import pytest

from packages.quantum.policy_lab.shadow_fleet import FLEET_EPOCH
from packages.quantum.services import shadow_fleet_activation as sfa

from packages.quantum.tests.test_shadow_fleet_activation import (
    FakeSupabase,
    USER,
    _attestation,
    _clean_activatable_fake,
    _closed_positions,
    _fleet_row,
    _micro_rows,
    _reconciliation_receipts,
    _receipt_rows,
    _registrations,
    _terminal_orders,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_MIGRATION = (
    REPO_ROOT / "supabase" / "migrations"
    / "20260720140000_fleet_reconciliation_receipts.sql"
)
BIND_MIGRATION = (
    REPO_ROOT / "supabase" / "migrations"
    / "20260720150000_bind_fleet_activation_to_receipts.sql"
)
BACKFILL_ARTIFACT = (
    REPO_ROOT / "supabase" / "backfills"
    / "20260720140500_fleet_reconciliation_receipts_backfill.sql"
)


def _authorize(monkeypatch):
    monkeypatch.setenv(sfa.AUTHORIZATION_ENV, "1")


def _strip_sql_comments(sql: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


# ── A. Faithful Python mirror of the RPC's receipt-binding clauses ───────────

class RpcReceiptRaise(Exception):
    """A modelled RAISE from the activation RPC's receipt clauses (the SQL is
    the final authority; this mirror reproduces those clauses)."""

    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def _rpc_receipt_mirror(receipt_rows, user, epoch, attestation):
    """Reproduce the RPC's reconciliation-receipt clauses (the ones a direct
    service-role call would hit). Returns the covered kinds on success; RAISEs
    (RpcReceiptRaise) exactly where the SQL RAISEs. Reads the receipt rows at
    CALL time (the receipt existence is checked in-transaction)."""
    bundle = attestation.get("reconciliation_receipts")
    if bundle is None or not isinstance(bundle, (list, tuple)) or len(bundle) == 0:
        raise RpcReceiptRaise("attestation_missing_reconciliation_receipts")
    kinds = []
    for elem in bundle:
        rid = str(elem.get("receipt_id") or "").strip()
        kind = str(elem.get("receipt_kind") or "").strip()
        fp = str(elem.get("content_fingerprint") or "").strip().lower()
        if not rid or not kind or not fp:
            raise RpcReceiptRaise("reconciliation_receipt_malformed")
        matches = [
            r for r in receipt_rows
            if r.get("receipt_id") == rid
            and r.get("user_id") == user
            and r.get("effective_epoch") == epoch
            and r.get("receipt_kind") == kind
            and str(r.get("content_fingerprint") or "").lower() == fp
            and (r.get("source_alert_id") is not None
                 or (str(r.get("source_table") or "").strip() != ""
                     and str(r.get("source_row_id") or "").strip() != ""))
        ]
        if len(matches) != 1:
            raise RpcReceiptRaise("receipt_not_found")
        kinds.append(kind)
    for req in sfa.REQUIRED_RECEIPT_KINDS:
        if req not in kinds:
            raise RpcReceiptRaise("reconciliation_receipt_kind_missing")
    return kinds


class TestRpcReceiptMirrorIsFinalAuthority:
    def test_exact_valid_bundle_passes(self):
        rows = _receipt_rows()
        kinds = _rpc_receipt_mirror(
            rows, USER, FLEET_EPOCH, _attestation())
        assert set(kinds) == {"stale_order", "manual_review"}

    def test_nonexistent_receipt_id_rejected(self):
        rows = _receipt_rows()
        att = _attestation()
        att["reconciliation_receipts"][0]["receipt_id"] = "recon:does-not-exist"
        with pytest.raises(RpcReceiptRaise) as exc:
            _rpc_receipt_mirror(rows, USER, FLEET_EPOCH, att)
        assert exc.value.reason == "receipt_not_found"

    def test_wrong_user_rejected(self):
        rows = _receipt_rows()
        with pytest.raises(RpcReceiptRaise) as exc:
            _rpc_receipt_mirror(rows, "someone-else", FLEET_EPOCH, _attestation())
        assert exc.value.reason == "receipt_not_found"

    def test_wrong_epoch_rejected(self):
        rows = _receipt_rows()
        with pytest.raises(RpcReceiptRaise) as exc:
            _rpc_receipt_mirror(rows, USER, "other_epoch", _attestation())
        assert exc.value.reason == "receipt_not_found"

    def test_wrong_kind_rejected(self):
        rows = _receipt_rows()
        att = _attestation()
        # Flip stale_order -> orphan_run: the (id,kind,fp) triple no longer
        # matches any row -> receipt_not_found (before the kind-coverage check).
        att["reconciliation_receipts"][0]["receipt_kind"] = "orphan_run"
        with pytest.raises(RpcReceiptRaise) as exc:
            _rpc_receipt_mirror(rows, USER, FLEET_EPOCH, att)
        assert exc.value.reason == "receipt_not_found"

    def test_wrong_fingerprint_rejected(self):
        rows = _receipt_rows()
        att = _attestation()
        att["reconciliation_receipts"][0]["content_fingerprint"] = "0" * 64
        with pytest.raises(RpcReceiptRaise) as exc:
            _rpc_receipt_mirror(rows, USER, FLEET_EPOCH, att)
        assert exc.value.reason == "receipt_not_found"

    def test_missing_provenance_rejected(self):
        """source ref mismatch: a receipt row with NO provenance
        (source_alert_id null AND source_table/row blank) is excluded by the
        RPC's provenance predicate -> receipt_not_found."""
        rows = _receipt_rows()
        rows[0]["source_table"] = ""
        rows[0]["source_row_id"] = ""
        rows[0]["source_alert_id"] = None
        with pytest.raises(RpcReceiptRaise) as exc:
            _rpc_receipt_mirror(rows, USER, FLEET_EPOCH, _attestation())
        assert exc.value.reason == "receipt_not_found"

    def test_missing_required_kind_rejected(self):
        rows = _receipt_rows()
        att = _attestation()
        att["reconciliation_receipts"] = [
            r for r in att["reconciliation_receipts"]
            if r["receipt_kind"] == "stale_order"]
        # Only stale_order present -> manual_review missing.
        with pytest.raises(RpcReceiptRaise) as exc:
            _rpc_receipt_mirror(rows, USER, FLEET_EPOCH, att)
        assert exc.value.reason == "reconciliation_receipt_kind_missing"

    def test_empty_bundle_rejected(self):
        att = _attestation()
        att["reconciliation_receipts"] = []
        with pytest.raises(RpcReceiptRaise) as exc:
            _rpc_receipt_mirror(_receipt_rows(), USER, FLEET_EPOCH, att)
        assert exc.value.reason == "attestation_missing_reconciliation_receipts"

    def test_direct_service_role_bypass_empty_table_still_gated(self):
        """A direct service-role RPC call that SKIPS the Python preflight and
        submits a fabricated bundle against an EMPTY receipt table (the real
        state — backfill BLOCKED) still fails: receipt_not_found."""
        with pytest.raises(RpcReceiptRaise) as exc:
            _rpc_receipt_mirror([], USER, FLEET_EPOCH, _attestation())
        assert exc.value.reason == "receipt_not_found"


# ── B. Same scenarios through the REAL production preflight (service) ────────

class TestServicePreflightReceipts:
    def _fake(self):
        return _clean_activatable_fake(receipts=_receipt_rows())

    def test_valid_bundle_reaches_single_rpc_and_threads_it(self, monkeypatch):
        _authorize(monkeypatch)
        fake = self._fake()
        result = sfa.execute_activation(
            fake, USER, idempotency_key="k",
            policy_registrations=_registrations(),
            attestation=_attestation(), confirm=sfa.CONFIRM_LITERAL)
        assert result["status"] == "rpc_complete"
        assert len(fake.rpc_calls) == 1
        att = fake.rpc_calls[0]["params"]["p_attestation"]
        kinds = {r["receipt_kind"] for r in att["reconciliation_receipts"]}
        assert kinds == {"stale_order", "manual_review"}
        assert fake.writes == []

    def test_missing_bundle_blocked_zero_rpc(self, monkeypatch):
        _authorize(monkeypatch)
        fake = self._fake()
        att = _attestation()
        del att["reconciliation_receipts"]
        with pytest.raises(sfa.AttestationInvalid):
            sfa.execute_activation(
                fake, USER, idempotency_key="k",
                policy_registrations=_registrations(),
                attestation=att, confirm=sfa.CONFIRM_LITERAL)
        assert fake.rpc_calls == [] and fake.writes == []

    def test_bad_kind_blocked_zero_rpc(self, monkeypatch):
        _authorize(monkeypatch)
        fake = self._fake()
        att = _attestation()
        att["reconciliation_receipts"][0]["receipt_kind"] = "not_a_kind"
        with pytest.raises(sfa.AttestationInvalid):
            sfa.execute_activation(
                fake, USER, idempotency_key="k",
                policy_registrations=_registrations(),
                attestation=att, confirm=sfa.CONFIRM_LITERAL)
        assert fake.rpc_calls == [] and fake.writes == []

    def test_truncated_fingerprint_blocked_zero_rpc(self, monkeypatch):
        _authorize(monkeypatch)
        fake = self._fake()
        att = _attestation()
        att["reconciliation_receipts"][0]["content_fingerprint"] = "04317fc1"  # 8 < 32
        with pytest.raises(sfa.AttestationInvalid):
            sfa.execute_activation(
                fake, USER, idempotency_key="k",
                policy_registrations=_registrations(),
                attestation=att, confirm=sfa.CONFIRM_LITERAL)
        assert fake.rpc_calls == [] and fake.writes == []

    def test_missing_required_kind_blocked_zero_rpc(self, monkeypatch):
        _authorize(monkeypatch)
        fake = self._fake()
        att = _attestation()
        att["reconciliation_receipts"] = [
            r for r in att["reconciliation_receipts"]
            if r["receipt_kind"] == "stale_order"]
        with pytest.raises(sfa.AttestationInvalid):
            sfa.execute_activation(
                fake, USER, idempotency_key="k",
                policy_registrations=_registrations(),
                attestation=att, confirm=sfa.CONFIRM_LITERAL)
        assert fake.rpc_calls == [] and fake.writes == []

    def test_server_receipt_not_found_leaves_zero_client_writes(self, monkeypatch):
        """Structure is valid (preflight passes) but the RPC raises
        receipt_not_found at the DEEPEST callee (server authority) → the error
        propagates and the service has performed ZERO table writes; the fleet
        row is untouched (still inactive) — rollback leaves 0 active / 0
        bindings / 0 activation receipt."""
        _authorize(monkeypatch)

        def _receipt_not_found(fn, params):
            raise RuntimeError("shadow_fleet_activate: receipt_not_found")

        fake = _clean_activatable_fake(
            receipts=_receipt_rows(), rpc_handler=_receipt_not_found)
        with pytest.raises(RuntimeError, match="receipt_not_found"):
            sfa.execute_activation(
                fake, USER, idempotency_key="k",
                policy_registrations=_registrations(),
                attestation=_attestation(), confirm=sfa.CONFIRM_LITERAL)
        assert fake.writes == []
        assert fake.tables["shadow_fleets"][0]["status"] == \
            "pending_legacy_terminal"
        # No activation receipt row was written by the client.
        assert not any(
            w["table"] == "risk_alerts" for w in fake.writes)


# ── Plan reports the receipt bundle (owner-facing dry-run shape) ─────────────

class TestPlanReportsReceipts:
    def test_plan_reports_receipt_kinds_and_count(self):
        fake = _clean_activatable_fake(receipts=_receipt_rows())
        plan = sfa.plan_activation(
            fake, USER, idempotency_key="k",
            policy_registrations=_registrations(), attestation=_attestation())
        assert plan["reconciliation_receipts_attested"] == 2
        assert plan["reconciliation_receipt_kinds"] == \
            ["manual_review", "stale_order"]
        assert plan["required_receipt_kinds"] == ["stale_order", "manual_review"]
        assert plan["plan"]["reconciliation_receipt_existence"] == \
            "enforced_in_rpc_against_fleet_reconciliation_receipts"


# ── Vocabulary + constants ───────────────────────────────────────────────────

def test_required_receipt_kinds_and_allowlist():
    assert sfa.REQUIRED_RECEIPT_KINDS == ("stale_order", "manual_review")
    assert sfa.RECONCILIATION_RECEIPT_KINDS == {
        "stale_order", "manual_review", "orphan_run"}
    assert sfa.MIN_CONTENT_FINGERPRINT_LEN == 32


# ── D1 schema migration drift-lock ───────────────────────────────────────────

class TestD1SchemaDriftLock:
    @pytest.fixture(scope="class")
    def sql(self):
        return SCHEMA_MIGRATION.read_text(encoding="utf-8")

    def test_table_created(self, sql):
        assert "CREATE TABLE IF NOT EXISTS fleet_reconciliation_receipts" in sql

    def test_receipt_id_pk_nonblank(self, sql):
        assert re.search(
            r"receipt_id\s+text\s+PRIMARY KEY\s+CHECK\s*\(\s*btrim\(receipt_id\)\s*<>\s*''",
            sql)

    def test_user_and_epoch_scope_notnull(self, sql):
        assert re.search(r"user_id\s+uuid\s+NOT NULL", sql)
        assert re.search(r"effective_epoch\s+text\s+NOT NULL", sql)

    def test_receipt_kind_allowlist(self, sql):
        assert "receipt_kind IN ('stale_order', 'manual_review', 'orphan_run')" \
            in sql

    def test_content_fingerprint_full_length_check(self, sql):
        assert re.search(
            r"content_fingerprint\s+text\s+NOT NULL[\s\S]*?char_length\(content_fingerprint\)\s*>=\s*32",
            sql)

    def test_source_alert_fk_and_typed_source_ref(self, sql):
        # provenance form (a): nullable FK to risk_alerts
        assert "source_alert_id     uuid REFERENCES risk_alerts(id)" in sql \
            or re.search(r"source_alert_id\s+uuid\s+REFERENCES\s+risk_alerts\(id\)", sql)
        # provenance form (b): typed source_ref triple
        for col in ("source_table", "source_row_id", "source_fingerprint"):
            assert re.search(rf"\b{col}\b\s+text", sql), col

    def test_provenance_present_check(self, sql):
        assert "fleet_recon_receipt_provenance_present" in sql

    def test_source_alert_uniqueness(self, sql):
        assert re.search(
            r"CREATE UNIQUE INDEX[^\n]*ux_fleet_recon_receipts_source_alert[\s\S]*?"
            r"\(source_alert_id\)\s*WHERE source_alert_id IS NOT NULL", sql)

    def test_kind_fp_unique_backfill_idempotency_key(self, sql):
        assert "UNIQUE (receipt_kind, content_fingerprint)" in sql

    def test_append_only_immutability_trigger(self, sql):
        code = _strip_sql_comments(sql)
        assert re.search(
            r"CREATE TRIGGER\s+trg_fleet_recon_receipts_immutable\s+"
            r"BEFORE UPDATE OR DELETE ON fleet_reconciliation_receipts", code)
        assert "fleet_reconciliation_receipts_immutable" in code
        # The trigger fn RAISEs (no UPDATE/DELETE of receipt truth).
        assert "append-only" in sql

    def test_fixed_search_path_on_helper(self, sql):
        assert "SET search_path = public, pg_temp" in sql

    def test_rls_service_role_only(self, sql):
        assert "ENABLE ROW LEVEL SECURITY" in sql
        assert "auth.role() = 'service_role'" in sql
        assert "GRANT SELECT, INSERT ON TABLE fleet_reconciliation_receipts TO service_role" \
            in sql
        # No UPDATE/DELETE grant (immutability), no PUBLIC.
        assert "REVOKE ALL ON TABLE fleet_reconciliation_receipts FROM PUBLIC" in sql


# ── D3 activation-RPC receipt-binding drift-lock ─────────────────────────────

class TestD3BindMigrationDriftLock:
    @pytest.fixture(scope="class")
    def sql(self):
        return BIND_MIGRATION.read_text(encoding="utf-8")

    def test_signature_unchanged_5_arg(self, sql):
        assert re.search(
            r"CREATE OR REPLACE FUNCTION rpc_shadow_fleet_activate\(\s*"
            r"p_user_id uuid,\s*p_idempotency_key text,\s*"
            r"p_policy_registrations jsonb,\s*p_attestation jsonb,\s*"
            r"p_expected_binding_fingerprint text\s*\)", sql)

    def test_defensive_drop_of_old_4arg_overload(self, sql):
        assert re.search(
            r"DROP FUNCTION IF EXISTS\s+rpc_shadow_fleet_activate\("
            r"uuid, text, jsonb, jsonb\)", sql)

    def test_receipt_bundle_required(self, sql):
        code = _strip_sql_comments(sql)
        assert "p_attestation->'reconciliation_receipts'" in code
        assert "attestation_missing_reconciliation_receipts" in sql
        assert "jsonb_array_elements(v_receipt_ids)" in code

    def test_receipt_existence_predicate(self, sql):
        code = _strip_sql_comments(sql)
        assert re.search(
            r"FROM fleet_reconciliation_receipts r[\s\S]*?"
            r"r\.receipt_id = v_receipt_id[\s\S]*?"
            r"r\.user_id = p_user_id[\s\S]*?"
            r"r\.effective_epoch = v_fleet\.epoch_name[\s\S]*?"
            r"r\.receipt_kind = v_receipt_kind[\s\S]*?"
            r"lower\(r\.content_fingerprint\) = v_receipt_fp", code)
        # provenance predicate present in the existence check.
        assert "r.source_alert_id IS NOT NULL" in code
        assert "receipt_not_found" in sql

    def test_required_kinds_enforced(self, sql):
        code = _strip_sql_comments(sql)
        assert re.search(
            r"FOREACH v_required_kind IN ARRAY ARRAY\['stale_order', 'manual_review'\]",
            code)
        assert "reconciliation_receipt_kind_missing" in sql

    def test_legacy_nonblank_receipt_preserved(self, sql):
        assert "attestation_missing_stale_order_reconciliation_receipt" in sql

    def test_all_prior_gates_preserved(self, sql):
        for clause in (
            "registry_not_exactly_50_approved",
            "binding_fingerprint_mismatch",
            "payload_binding_mismatch",
            'ORDER BY policy_registration_id COLLATE "C" ASC',
            "GET DIAGNOSTICS v_updated = ROW_COUNT",
            "v_updated <> 50",
            "expected_binding_fingerprint_required",
        ):
            assert clause in sql, clause

    def test_shadow_only_never_live_eligible(self, sql):
        code = _strip_sql_comments(sql)
        assert "'shadow_only'" in code
        assert "'live_eligible'" not in code

    def test_no_commit_single_transaction(self, sql):
        code = _strip_sql_comments(sql)
        assert not re.search(r"^\s*COMMIT\s*;", code, re.M)

    def test_legacy_rows_never_rewritten(self, sql):
        code = _strip_sql_comments(sql)
        assert not re.search(r"UPDATE\s+paper_orders", code, re.I)
        assert not re.search(r"DELETE\s+FROM\s+paper_orders", code, re.I)
        assert not re.search(r"UPDATE\s+paper_positions", code, re.I)
        assert not re.search(r"DELETE\s+FROM\s+paper_positions", code, re.I)

    def test_grants_only_service_role(self, sql):
        assert re.search(
            r"REVOKE ALL ON FUNCTION rpc_shadow_fleet_activate\("
            r"uuid, text, jsonb, jsonb, text\)\s+FROM PUBLIC, anon, authenticated",
            sql)
        assert re.search(
            r"GRANT EXECUTE ON FUNCTION rpc_shadow_fleet_activate\("
            r"uuid, text, jsonb, jsonb, text\)\s+TO service_role", sql)

    def test_fixed_search_path(self, sql):
        assert "SET search_path = public, extensions, pg_temp" in sql


# ── D2 backfill artifact: BLOCKED verdict + zero-write contract ──────────────

class TestD2BackfillArtifact:
    @pytest.fixture(scope="class")
    def sql(self):
        return BACKFILL_ARTIFACT.read_text(encoding="utf-8")

    def test_verdict_is_blocked(self, sql):
        assert "BLOCKED_RECEIPT_ID_NOT_DURABLE" in sql

    def test_inserts_only_eligible_and_all_ineligible(self, sql):
        code = _strip_sql_comments(sql)
        # The INSERT selects WHERE eligible; every candidate is eligible=false.
        assert "WHERE c.eligible" in code
        # Every candidate carries the ineligible marker (false); none is true.
        assert code.count("false,") >= 4
        assert "true," not in code
        for fp in ("04317fc1", "5d5cd9fc", "40258ba9", "b780271c"):
            assert fp in code, fp

    def test_idempotent_on_conflict(self, sql):
        assert "ON CONFLICT (receipt_kind, content_fingerprint) DO NOTHING" in sql

    def test_zero_write_integrity_assertions(self, sql):
        assert "inserted % rows on a BLOCKED verdict" in sql
        assert "row count changed" in sql

    def test_rollback_section_present(self, sql):
        assert "ROLLBACK" in sql
        assert "fable_lane_d_backfill_20260720" in sql

    def test_not_under_migrations_dir(self):
        # The backfill is an operator artifact, NOT a migration.
        assert BACKFILL_ARTIFACT.parent.name == "backfills"
        assert not (REPO_ROOT / "supabase" / "migrations"
                    / BACKFILL_ARTIFACT.name).exists()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
