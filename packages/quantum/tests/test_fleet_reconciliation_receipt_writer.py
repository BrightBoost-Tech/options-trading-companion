"""Lane A/B — durable reconciliation-receipt WRITER RPC + privilege hardening.

Always-green CI signal (no ephemeral Postgres required). Three mirrors meet here
(the #1291 SQL-mirror parity pattern; the real-Postgres proof lives in
packages/quantum/tests/pg/receipt/ and is collect-ignored without a DB):

  A. THE WRITER-RPC CLAUSES. A faithful Python mirror of
     rpc_issue_fleet_reconciliation_receipt_v1
     (20260721010000_rpc_issue_fleet_reconciliation_receipt_v1.sql) — the exact
     clauses a DIRECT service-role call would hit (the SQL is the FINAL
     authority). Failure injected at the ORIGIN (the source row / the marker /
     the existing receipts), truth asserted at the TOP (typed RAISE / durable
     receipt / conflict).

  B. THE REAL SERVICE WRAPPER. fleet_reconciliation_receipt.issue_reconciliation_
     receipt validates the call STRUCTURE and threads ONE supabase.rpc call; a
     structurally-invalid call raises before any RPC (zero writes).

  C. MIGRATION DRIFT-LOCKS pinning the Lane-A writer RPC + the Lane-B privilege
     hardening against the file TEXT, so a contract change breaks the build.

Nothing here calls the production RPC, writes a production row, or activates the
fleet.
"""

import re
from pathlib import Path

import pytest

from packages.quantum.services import fleet_reconciliation_receipt as frr
from packages.quantum.services import shadow_fleet_activation as sfa
from packages.quantum.tests.test_shadow_fleet_activation import FakeSupabase

REPO_ROOT = Path(__file__).resolve().parents[3]
WRITER_MIGRATION = (
    REPO_ROOT / "supabase" / "migrations"
    / "20260721010000_rpc_issue_fleet_reconciliation_receipt_v1.sql"
)
HARDEN_MIGRATION = (
    REPO_ROOT / "supabase" / "migrations"
    / "20260721010500_harden_fleet_receipt_privileges.sql"
)

USER = "user-1"
OTHER = "user-2"
EPOCH = "small_tier_v1"
FP_A = "04317fc1" + "a" * 56   # 64-char full token
FP_B = "5d5cd9fc" + "b" * 56


def _strip_sql_comments(sql: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def _marker(kind, fp=FP_A, epoch=EPOCH, status="completed"):
    return {"reconciliation_receipt": {
        "kind": kind, "status": status,
        "content_fingerprint": fp, "effective_epoch": epoch}}


# ── A. Faithful Python mirror of the writer-RPC clauses ──────────────────────

class WriterRpcRaise(Exception):
    """A modelled RAISE from the writer RPC (the SQL is the final authority)."""

    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


_SOURCE_COL = {"risk_alerts": "metadata",
               "paper_orders": "broker_response",
               "paper_ledger": "metadata"}
_KINDS = {"stale_order", "manual_review", "orphan_run"}


def _writer_rpc_mirror(sources, receipts, *, user, kind, epoch, fingerprint,
                       alert=None, table=None, row=None, actor="tester"):
    """Reproduce rpc_issue_fleet_reconciliation_receipt_v1. ``sources`` is
    {table: {id: {"user_id":.., "<col>": <marker jsonb>}}}; ``receipts`` is a
    mutable list acting as fleet_reconciliation_receipts (idempotency key =
    (receipt_kind, lower(content_fingerprint))). Returns the receipt dict;
    RAISEs WriterRpcRaise exactly where the SQL RAISEs."""
    # 1. args
    if not user:
        raise WriterRpcRaise("user_id_required")
    k = (kind or "").strip()
    if k not in _KINDS:
        raise WriterRpcRaise("receipt_kind_invalid")
    ep = (epoch or "").strip()
    if not ep:
        raise WriterRpcRaise("effective_epoch_required")
    fp = (fingerprint or "").strip().lower()
    if len(fp) < 32:
        raise WriterRpcRaise("content_fingerprint_not_full")
    created_by = (actor or "").strip() or "reconciliation_receipt_writer_v1"

    # 2. provenance form
    has_alert = bool(alert)
    tbl = (table or "").strip()
    rw = (row or "").strip()
    has_ref = bool(tbl and rw)
    if has_alert and (tbl or rw):
        raise WriterRpcRaise("provenance_ambiguous")
    if not has_alert and not has_ref:
        raise WriterRpcRaise("provenance_missing")
    if has_alert:
        src_table, src_id = "risk_alerts", alert
        ins_alert, ins_table, ins_row = alert, None, None
    else:
        if tbl == "job_runs":
            raise WriterRpcRaise("source_user_scope_unavailable")
        if tbl not in _SOURCE_COL:
            raise WriterRpcRaise("source_table_unsupported")
        src_table, src_id = tbl, rw
        ins_alert, ins_table, ins_row = None, tbl, rw

    # 3. source lock + exists
    srow = sources.get(src_table, {}).get(src_id)
    if srow is None:
        raise WriterRpcRaise("source_not_found")

    # 4a. user scope
    if not srow.get("user_id") or srow.get("user_id") != user:
        raise WriterRpcRaise("source_user_mismatch")

    # 4b. typed marker
    marker = (srow.get(_SOURCE_COL[src_table]) or {}).get("reconciliation_receipt")
    if not isinstance(marker, dict):
        raise WriterRpcRaise("source_not_a_completed_reconciliation")
    if (marker.get("status") or "").strip() != "completed":
        raise WriterRpcRaise("reconciliation_not_completed")
    if (marker.get("kind") or "").strip() != k:
        raise WriterRpcRaise("source_kind_mismatch")
    if (marker.get("effective_epoch") or "").strip() != ep:
        raise WriterRpcRaise("source_epoch_mismatch")
    m_fp = (marker.get("content_fingerprint") or "").strip().lower()
    if len(m_fp) < 32:
        raise WriterRpcRaise("source_fingerprint_not_full")
    if m_fp != fp:
        raise WriterRpcRaise("content_fingerprint_mismatch")

    def _json(r, replay):
        return {**r, "idempotent_replay": replay}

    # 6A. source-alert single use
    if has_alert:
        for r in receipts:
            if r.get("source_alert_id") == alert:
                if (r["receipt_kind"] == k and r["content_fingerprint"] == fp
                        and r["user_id"] == user and r["effective_epoch"] == ep):
                    return _json(r, True)
                raise WriterRpcRaise("source_alert_already_receipted")

    # 6B. natural key (kind, fp)
    for r in receipts:
        if r["receipt_kind"] == k and r["content_fingerprint"] == fp:
            if (r["user_id"] == user and r["effective_epoch"] == ep
                    and r.get("source_alert_id") == ins_alert
                    and (r.get("source_table") or "") == (ins_table or "")
                    and (r.get("source_row_id") or "") == (ins_row or "")):
                return _json(r, True)
            raise WriterRpcRaise("receipt_conflict")

    # 6C. insert
    new = {
        "receipt_id": "frr_" + str(len(receipts) + 1),
        "user_id": user, "receipt_kind": k, "content_fingerprint": fp,
        "effective_epoch": ep, "source_alert_id": ins_alert,
        "source_table": ins_table, "source_row_id": ins_row,
        "source_fingerprint": fp, "created_by": created_by,
    }
    receipts.append(new)
    return _json(new, False)


def _sources():
    return {
        "paper_orders": {
            "o1": {"user_id": USER, "broker_response": _marker("stale_order", FP_A)},
        },
        "risk_alerts": {
            "a1": {"user_id": USER, "metadata": _marker("manual_review", FP_B)},
        },
        "paper_ledger": {
            "l1": {"user_id": USER, "metadata": _marker("orphan_run", FP_A)},
        },
    }


class TestWriterMirrorIsFinalAuthority:
    def test_stale_order_happy_via_paper_orders(self):
        out = _writer_rpc_mirror(_sources(), [], user=USER, kind="stale_order",
                                 epoch=EPOCH, fingerprint=FP_A,
                                 table="paper_orders", row="o1")
        assert out["receipt_kind"] == "stale_order"
        assert out["idempotent_replay"] is False
        assert out["source_table"] == "paper_orders"

    def test_manual_review_happy_via_alert(self):
        out = _writer_rpc_mirror(_sources(), [], user=USER, kind="manual_review",
                                 epoch=EPOCH, fingerprint=FP_B, alert="a1")
        assert out["source_alert_id"] == "a1"
        assert out["source_table"] is None

    def test_orphan_run_happy_via_ledger(self):
        out = _writer_rpc_mirror(_sources(), [], user=USER, kind="orphan_run",
                                 epoch=EPOCH, fingerprint=FP_A,
                                 table="paper_ledger", row="l1")
        assert out["receipt_kind"] == "orphan_run"

    def test_wrong_user_rejected(self):
        with pytest.raises(WriterRpcRaise) as e:
            _writer_rpc_mirror(_sources(), [], user=OTHER, kind="stale_order",
                               epoch=EPOCH, fingerprint=FP_A,
                               table="paper_orders", row="o1")
        assert e.value.reason == "source_user_mismatch"

    def test_wrong_kind_rejected(self):
        with pytest.raises(WriterRpcRaise) as e:
            _writer_rpc_mirror(_sources(), [], user=USER, kind="manual_review",
                               epoch=EPOCH, fingerprint=FP_A,
                               table="paper_orders", row="o1")
        assert e.value.reason == "source_kind_mismatch"

    def test_wrong_epoch_rejected(self):
        with pytest.raises(WriterRpcRaise) as e:
            _writer_rpc_mirror(_sources(), [], user=USER, kind="stale_order",
                               epoch="other", fingerprint=FP_A,
                               table="paper_orders", row="o1")
        assert e.value.reason == "source_epoch_mismatch"

    def test_wrong_fingerprint_rejected(self):
        with pytest.raises(WriterRpcRaise) as e:
            _writer_rpc_mirror(_sources(), [], user=USER, kind="stale_order",
                               epoch=EPOCH, fingerprint="7" * 64,
                               table="paper_orders", row="o1")
        assert e.value.reason == "content_fingerprint_mismatch"

    def test_truncated_fingerprint_rejected(self):
        with pytest.raises(WriterRpcRaise) as e:
            _writer_rpc_mirror(_sources(), [], user=USER, kind="stale_order",
                               epoch=EPOCH, fingerprint="04317fc1",
                               table="paper_orders", row="o1")
        assert e.value.reason == "content_fingerprint_not_full"

    def test_nonexistent_source_rejected(self):
        with pytest.raises(WriterRpcRaise) as e:
            _writer_rpc_mirror(_sources(), [], user=USER, kind="stale_order",
                               epoch=EPOCH, fingerprint=FP_A,
                               table="paper_orders", row="missing")
        assert e.value.reason == "source_not_found"

    def test_prose_only_source_rejected(self):
        src = {"paper_orders": {"p": {"user_id": USER,
                                      "broker_response": {"note": "fp 04317fc1"}}}}
        with pytest.raises(WriterRpcRaise) as e:
            _writer_rpc_mirror(src, [], user=USER, kind="stale_order",
                               epoch=EPOCH, fingerprint=FP_A,
                               table="paper_orders", row="p")
        assert e.value.reason == "source_not_a_completed_reconciliation"

    def test_not_completed_state_rejected(self):
        src = {"paper_orders": {"o": {"user_id": USER,
               "broker_response": _marker("stale_order", FP_A, status="pending")}}}
        with pytest.raises(WriterRpcRaise) as e:
            _writer_rpc_mirror(src, [], user=USER, kind="stale_order",
                               epoch=EPOCH, fingerprint=FP_A,
                               table="paper_orders", row="o")
        assert e.value.reason == "reconciliation_not_completed"

    def test_job_runs_source_rejected(self):
        with pytest.raises(WriterRpcRaise) as e:
            _writer_rpc_mirror(_sources(), [], user=USER, kind="orphan_run",
                               epoch=EPOCH, fingerprint=FP_A,
                               table="job_runs", row="j1")
        assert e.value.reason == "source_user_scope_unavailable"

    def test_unsupported_table_rejected(self):
        with pytest.raises(WriterRpcRaise) as e:
            _writer_rpc_mirror(_sources(), [], user=USER, kind="stale_order",
                               epoch=EPOCH, fingerprint=FP_A,
                               table="paper_positions", row="x")
        assert e.value.reason == "source_table_unsupported"

    def test_provenance_ambiguous_rejected(self):
        with pytest.raises(WriterRpcRaise) as e:
            _writer_rpc_mirror(_sources(), [], user=USER, kind="stale_order",
                               epoch=EPOCH, fingerprint=FP_A,
                               alert="a1", table="paper_orders", row="o1")
        assert e.value.reason == "provenance_ambiguous"

    def test_provenance_missing_rejected(self):
        with pytest.raises(WriterRpcRaise) as e:
            _writer_rpc_mirror(_sources(), [], user=USER, kind="stale_order",
                               epoch=EPOCH, fingerprint=FP_A)
        assert e.value.reason == "provenance_missing"

    def test_bad_kind_arg_rejected(self):
        with pytest.raises(WriterRpcRaise) as e:
            _writer_rpc_mirror(_sources(), [], user=USER, kind="nope",
                               epoch=EPOCH, fingerprint=FP_A,
                               table="paper_orders", row="o1")
        assert e.value.reason == "receipt_kind_invalid"

    def test_exact_replay_returns_same_receipt_zero_new_rows(self):
        receipts = []
        r1 = _writer_rpc_mirror(_sources(), receipts, user=USER,
                                kind="stale_order", epoch=EPOCH, fingerprint=FP_A,
                                table="paper_orders", row="o1")
        assert len(receipts) == 1
        r2 = _writer_rpc_mirror(_sources(), receipts, user=USER,
                                kind="stale_order", epoch=EPOCH, fingerprint=FP_A,
                                table="paper_orders", row="o1")
        assert r2["receipt_id"] == r1["receipt_id"]
        assert r2["idempotent_replay"] is True
        assert len(receipts) == 1   # no new row

    def test_conflicting_replay_different_user_rejected(self):
        receipts = []
        _writer_rpc_mirror(_sources(), receipts, user=USER, kind="stale_order",
                           epoch=EPOCH, fingerprint=FP_A,
                           table="paper_orders", row="o1")
        # Another user's source row carries the same fingerprint.
        src2 = {"paper_orders": {"o2": {"user_id": OTHER,
                "broker_response": _marker("stale_order", FP_A)}}}
        with pytest.raises(WriterRpcRaise) as e:
            _writer_rpc_mirror(src2, receipts, user=OTHER, kind="stale_order",
                               epoch=EPOCH, fingerprint=FP_A,
                               table="paper_orders", row="o2")
        assert e.value.reason == "receipt_conflict"
        assert len(receipts) == 1


# ── B. Real service wrapper (structure validated; RPC threads the call) ──────

def _receipt_reply(fn, params):
    """rpc_handler: echo a durable receipt as the RPC would."""
    return {
        "receipt_id": "frr_srv_1",
        "user_id": params["p_user_id"],
        "receipt_kind": params["p_receipt_kind"],
        "content_fingerprint": params["p_content_fingerprint"],
        "effective_epoch": params["p_effective_epoch"],
        "source_alert_id": params["p_source_alert_id"],
        "source_table": params["p_source_table"],
        "source_row_id": params["p_source_row_id"],
        "source_fingerprint": params["p_content_fingerprint"],
        "created_by": params["p_actor_class"],
        "idempotent_replay": False,
    }


class TestServiceWrapper:
    def _fake(self):
        return FakeSupabase(rpc_handler=_receipt_reply)

    def test_valid_domain_call_threads_single_rpc(self):
        fake = self._fake()
        out = frr.issue_reconciliation_receipt(
            fake, user_id=USER, receipt_kind="stale_order", effective_epoch=EPOCH,
            content_fingerprint=FP_A, actor_class="op",
            source_table="paper_orders", source_row_id="o1")
        assert len(fake.rpc_calls) == 1
        call = fake.rpc_calls[0]
        assert call["fn"] == frr.RECEIPT_WRITER_RPC
        p = call["params"]
        assert p["p_user_id"] == USER and p["p_receipt_kind"] == "stale_order"
        assert p["p_content_fingerprint"] == FP_A
        assert p["p_source_alert_id"] is None
        assert p["p_source_table"] == "paper_orders" and p["p_source_row_id"] == "o1"
        assert out["receipt_id"] == "frr_srv_1"
        assert fake.writes == []

    def test_valid_alert_call_threads_single_rpc(self):
        fake = self._fake()
        frr.issue_reconciliation_receipt(
            fake, user_id=USER, receipt_kind="manual_review",
            effective_epoch=EPOCH, content_fingerprint=FP_B, actor_class="op",
            source_alert_id="a1")
        p = fake.rpc_calls[0]["params"]
        assert p["p_source_alert_id"] == "a1"
        assert p["p_source_table"] is None and p["p_source_row_id"] is None

    def test_fingerprint_normalized_lower(self):
        fake = self._fake()
        frr.issue_reconciliation_receipt(
            fake, user_id=USER, receipt_kind="stale_order", effective_epoch=EPOCH,
            content_fingerprint=FP_A.upper(), actor_class="op",
            source_table="paper_orders", source_row_id="o1")
        assert fake.rpc_calls[0]["params"]["p_content_fingerprint"] == FP_A

    @pytest.mark.parametrize("kw,exc_token", [
        (dict(receipt_kind="not_a_kind"), "receipt_kind_invalid"),
        (dict(content_fingerprint="04317fc1"), "content_fingerprint_not_full"),
        (dict(effective_epoch="  "), "effective_epoch_required"),
        (dict(actor_class="  "), "actor_class_required"),
        (dict(source_table="job_runs", source_row_id="j"), "source_user_scope_unavailable"),
        (dict(source_table="paper_positions", source_row_id="x"), "source_table_unsupported"),
    ])
    def test_structural_reject_zero_rpc(self, kw, exc_token):
        fake = self._fake()
        base = dict(user_id=USER, receipt_kind="stale_order", effective_epoch=EPOCH,
                    content_fingerprint=FP_A, actor_class="op",
                    source_table="paper_orders", source_row_id="o1")
        base.update(kw)
        with pytest.raises(frr.ReceiptStructureInvalid) as e:
            frr.issue_reconciliation_receipt(fake, **base)
        assert exc_token in str(e.value)
        assert fake.rpc_calls == [] and fake.writes == []

    def test_provenance_ambiguous_zero_rpc(self):
        fake = self._fake()
        with pytest.raises(frr.ReceiptStructureInvalid) as e:
            frr.issue_reconciliation_receipt(
                fake, user_id=USER, receipt_kind="stale_order",
                effective_epoch=EPOCH, content_fingerprint=FP_A, actor_class="op",
                source_alert_id="a1", source_table="paper_orders", source_row_id="o1")
        assert "provenance_ambiguous" in str(e.value)
        assert fake.rpc_calls == []

    def test_provenance_missing_zero_rpc(self):
        fake = self._fake()
        with pytest.raises(frr.ReceiptStructureInvalid) as e:
            frr.issue_reconciliation_receipt(
                fake, user_id=USER, receipt_kind="stale_order",
                effective_epoch=EPOCH, content_fingerprint=FP_A, actor_class="op")
        assert "provenance_missing" in str(e.value)
        assert fake.rpc_calls == []


class TestMarkerBuilder:
    def test_marker_shape_matches_rpc_contract(self):
        m = frr.build_reconciliation_marker(
            receipt_kind="stale_order", content_fingerprint=FP_A,
            effective_epoch=EPOCH)
        assert set(m) == {"reconciliation_receipt"}
        inner = m["reconciliation_receipt"]
        assert inner == {"kind": "stale_order", "status": "completed",
                         "content_fingerprint": FP_A, "effective_epoch": EPOCH}
        # The mirror accepts a source stamped with exactly this marker.
        src = {"paper_orders": {"o": {"user_id": USER, "broker_response": m}}}
        out = _writer_rpc_mirror(src, [], user=USER, kind="stale_order",
                                 epoch=EPOCH, fingerprint=FP_A,
                                 table="paper_orders", row="o")
        assert out["idempotent_replay"] is False

    def test_marker_rejects_bad_kind_and_short_fp(self):
        with pytest.raises(frr.ReceiptStructureInvalid):
            frr.build_reconciliation_marker(receipt_kind="nope",
                                            content_fingerprint=FP_A, effective_epoch=EPOCH)
        with pytest.raises(frr.ReceiptStructureInvalid):
            frr.build_reconciliation_marker(receipt_kind="stale_order",
                                            content_fingerprint="04317fc1", effective_epoch=EPOCH)


def test_constants_shared_with_activation_side():
    assert frr.RECONCILIATION_RECEIPT_KINDS is sfa.RECONCILIATION_RECEIPT_KINDS
    assert frr.MIN_CONTENT_FINGERPRINT_LEN == sfa.MIN_CONTENT_FINGERPRINT_LEN == 32
    assert frr.RECEIPT_SOURCE_TABLES == {"risk_alerts", "paper_orders", "paper_ledger"}
    assert "job_runs" not in frr.RECEIPT_SOURCE_TABLES


# ── C. Lane-A writer migration drift-lock ────────────────────────────────────

class TestWriterMigrationDriftLock:
    @pytest.fixture(scope="class")
    def sql(self):
        return WRITER_MIGRATION.read_text(encoding="utf-8")

    def test_function_signature(self, sql):
        assert re.search(
            r"CREATE OR REPLACE FUNCTION rpc_issue_fleet_reconciliation_receipt_v1\(\s*"
            r"p_user_id\s+uuid,\s*p_receipt_kind\s+text,\s*p_effective_epoch\s+text,\s*"
            r"p_content_fingerprint\s+text,\s*p_source_alert_id\s+uuid,\s*"
            r"p_source_table\s+text,\s*p_source_row_id\s+text,\s*p_actor_class\s+text\s*\)",
            sql)

    def test_server_generated_id_never_caller_supplied(self, sql):
        code = _strip_sql_comments(sql)
        # id is generated, never an argument.
        assert "gen_random_uuid()" in code
        assert "'frr_' || replace(gen_random_uuid()::text" in code
        assert "p_receipt_id" not in code

    def test_source_locked_for_update(self, sql):
        code = _strip_sql_comments(sql)
        assert code.count("FOR UPDATE") >= 3  # one per source-table branch
        for t in ("risk_alerts", "paper_orders", "paper_ledger"):
            assert re.search(rf"FROM {t}\b[\s\S]*?FOR UPDATE", code), t

    def test_source_must_exist_and_belong_to_user(self, sql):
        assert "source_not_found" in sql
        assert "source_user_mismatch" in sql

    def test_completed_marker_required(self, sql):
        code = _strip_sql_comments(sql)
        assert "'reconciliation_receipt'" in code
        assert "source_not_a_completed_reconciliation" in sql
        assert "reconciliation_not_completed" in sql
        assert "source_kind_mismatch" in sql
        assert "source_epoch_mismatch" in sql

    def test_full_fingerprint_match(self, sql):
        code = _strip_sql_comments(sql)
        assert "content_fingerprint_not_full" in sql
        assert "content_fingerprint_mismatch" in sql
        assert "char_length(v_fp) < 32" in code

    def test_job_runs_source_rejected(self, sql):
        code = _strip_sql_comments(sql)
        assert "source_user_scope_unavailable" in sql
        assert re.search(r"v_src_table\s*=\s*'job_runs'", code)

    def test_idempotent_and_conflict(self, sql):
        code = _strip_sql_comments(sql)
        assert "ON CONFLICT (receipt_kind, content_fingerprint) DO NOTHING" in code
        assert "receipt_conflict" in sql
        assert "idempotent_replay" in sql
        assert "source_alert_already_receipted" in sql

    def test_no_update_or_delete_of_receipts(self, sql):
        code = _strip_sql_comments(sql)
        assert not re.search(r"UPDATE\s+fleet_reconciliation_receipts", code, re.I)
        assert not re.search(r"DELETE\s+FROM\s+fleet_reconciliation_receipts", code, re.I)

    def test_no_fleet_or_policy_mutation(self, sql):
        code = _strip_sql_comments(sql)
        for t in ("shadow_fleets", "shadow_micro_accounts", "policy_registrations"):
            assert t not in code, t
        assert "rpc_shadow_fleet_activate" not in code

    def test_fixed_search_path(self, sql):
        assert "SET search_path = public, extensions, pg_temp" in sql

    def test_grants_service_role_only(self, sql):
        assert re.search(
            r"REVOKE ALL ON FUNCTION rpc_issue_fleet_reconciliation_receipt_v1\([^)]*\)\s*"
            r"FROM PUBLIC, anon, authenticated", sql)
        assert re.search(
            r"GRANT EXECUTE ON FUNCTION rpc_issue_fleet_reconciliation_receipt_v1\([^)]*\)\s*"
            r"TO service_role", sql)


# ── C. Lane-B privilege-hardening migration drift-lock ───────────────────────

class TestHardenMigrationDriftLock:
    @pytest.fixture(scope="class")
    def sql(self):
        return HARDEN_MIGRATION.read_text(encoding="utf-8")

    def test_revokes_mutation_grants_from_service_role(self, sql):
        assert re.search(
            r"REVOKE TRUNCATE, UPDATE, DELETE, REFERENCES, TRIGGER\s*"
            r"ON TABLE fleet_reconciliation_receipts FROM service_role", sql)

    def test_defensive_revoke_from_public_roles(self, sql):
        assert re.search(
            r"REVOKE ALL ON TABLE fleet_reconciliation_receipts "
            r"FROM PUBLIC, anon, authenticated", sql)

    def test_preserves_select_insert(self, sql):
        assert re.search(
            r"GRANT SELECT, INSERT ON TABLE fleet_reconciliation_receipts "
            r"TO service_role", sql)

    def test_truncate_guard_trigger(self, sql):
        code = _strip_sql_comments(sql)
        assert "fleet_reconciliation_receipts_no_truncate" in code
        assert re.search(
            r"CREATE TRIGGER\s+trg_fleet_recon_receipts_no_truncate\s+"
            r"BEFORE TRUNCATE ON fleet_reconciliation_receipts\s+"
            r"FOR EACH STATEMENT", code)
        assert "append-only" in sql

    def test_no_default_privilege_side_effect(self, sql):
        # Must NOT change schema-wide default privileges (out of scope + risky).
        assert "ALTER DEFAULT PRIVILEGES" not in _strip_sql_comments(sql)

    def test_additive_only_no_data_change(self, sql):
        # No DML statements (privilege change only). "UPDATE"/"DELETE" appear as
        # REVOKE privilege NAMES and in COMMENT prose — match real DML shapes.
        code = _strip_sql_comments(sql)
        assert not re.search(r"\bINSERT\s+INTO\b", code, re.I)
        assert not re.search(r"\bUPDATE\s+\w+\s+SET\b", code, re.I)
        assert not re.search(r"\bDELETE\s+FROM\b", code, re.I)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
