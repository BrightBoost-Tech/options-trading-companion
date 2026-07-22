"""Real-Postgres proof of rpc_issue_fleet_reconciliation_receipt_v1 (Lane A) +
the Lane-B privilege hardening, exercised against the ACTUAL migration SQL.

Collected only when a Postgres is reachable (see conftest.collect_ignore); the
always-green CI signal is the pure-python mirror suite one level up. Failures are
injected at the ORIGIN (the source rows / the marker / the grants) and the truth
asserted at the TOP (the RPC's typed RAISE / the durable receipt / the count).
"""

import json
import threading
import time
import uuid

import pytest

EPOCH = "small_tier_v1"
CALL = (
    "SELECT rpc_issue_fleet_reconciliation_receipt_v1("
    "%s,%s,%s,%s,%s,%s,%s,%s)"
)


def _fp() -> str:
    """A fresh, FULL (64-hex) content fingerprint, unique per call."""
    return uuid.uuid4().hex + uuid.uuid4().hex


def _marker(kind, fp, epoch=EPOCH, status="completed"):
    return json.dumps({"reconciliation_receipt": {
        "kind": kind, "status": status,
        "content_fingerprint": fp, "effective_epoch": epoch}})


def _call(cur, user, kind, fp, *, epoch=EPOCH, alert=None, table=None,
          row=None, actor="pg-test"):
    cur.execute(CALL, (user, kind, epoch, fp, alert, table, row, actor))
    return cur.fetchone()[0]


def _new_order(cur, user, marker_json):
    oid = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO paper_orders (id,user_id,broker_response) VALUES (%s,%s,%s)",
        (oid, user, marker_json))
    return oid


def _new_alert(cur, user, marker_json):
    aid = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO risk_alerts (id,user_id,metadata) VALUES (%s,%s,%s)",
        (aid, user, marker_json))
    return aid


def _new_ledger(cur, user, marker_json):
    lid = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO paper_ledger (id,user_id,metadata) VALUES (%s,%s,%s)",
        (lid, user, marker_json))
    return lid


def _receipt_count(cur, fp):
    cur.execute("SELECT count(*) FROM fleet_reconciliation_receipts "
                "WHERE content_fingerprint=%s", (fp,))
    return cur.fetchone()[0]


# ── Happy paths: each kind via a durable, marker-stamped source ──────────────

class TestHappyPaths:
    def test_stale_order_via_paper_orders(self, conn):
        cur = conn.cursor()
        u, fp = str(uuid.uuid4()), _fp()
        oid = _new_order(cur, u, _marker("stale_order", fp))
        out = _call(cur, u, "stale_order", fp, table="paper_orders", row=oid)
        assert out["receipt_kind"] == "stale_order"
        assert out["content_fingerprint"] == fp
        assert out["idempotent_replay"] is False
        assert out["receipt_id"].startswith("frr_")
        assert out["source_table"] == "paper_orders" and out["source_row_id"] == oid
        assert _receipt_count(cur, fp) == 1

    def test_manual_review_via_alert(self, conn):
        cur = conn.cursor()
        u, fp = str(uuid.uuid4()), _fp()
        aid = _new_alert(cur, u, _marker("manual_review", fp))
        out = _call(cur, u, "manual_review", fp, alert=aid)
        assert out["receipt_kind"] == "manual_review"
        assert out["source_alert_id"] == aid
        assert out["source_table"] is None
        assert _receipt_count(cur, fp) == 1

    def test_orphan_run_via_ledger(self, conn):
        cur = conn.cursor()
        u, fp = str(uuid.uuid4()), _fp()
        lid = _new_ledger(cur, u, _marker("orphan_run", fp))
        out = _call(cur, u, "orphan_run", fp, table="paper_ledger", row=lid)
        assert out["receipt_kind"] == "orphan_run"
        assert out["idempotent_replay"] is False

    def test_server_generated_id_not_caller_supplied(self, conn):
        """Two receipts from two sources get DISTINCT server ids; the caller
        never supplies identity (there is no receipt_id argument)."""
        cur = conn.cursor()
        u = str(uuid.uuid4())
        fp1, fp2 = _fp(), _fp()
        o1 = _new_order(cur, u, _marker("stale_order", fp1))
        o2 = _new_order(cur, u, _marker("stale_order", fp2))
        r1 = _call(cur, u, "stale_order", fp1, table="paper_orders", row=o1)
        r2 = _call(cur, u, "stale_order", fp2, table="paper_orders", row=o2)
        assert r1["receipt_id"] != r2["receipt_id"]


# ── Rejects: every validation gate RAISEs at the TOP, zero receipt written ───

class TestRejects:
    def _order(self, cur, u, fp, kind="stale_order"):
        return _new_order(cur, u, _marker(kind, fp))

    def test_wrong_user(self, conn):
        cur = conn.cursor()
        u, other, fp = str(uuid.uuid4()), str(uuid.uuid4()), _fp()
        oid = self._order(cur, u, fp)
        with pytest.raises(Exception, match="source_user_mismatch"):
            _call(cur, other, "stale_order", fp, table="paper_orders", row=oid)
        assert _receipt_count(cur, fp) == 0

    def test_wrong_kind(self, conn):
        cur = conn.cursor()
        u, fp = str(uuid.uuid4()), _fp()
        oid = self._order(cur, u, fp, kind="stale_order")
        with pytest.raises(Exception, match="source_kind_mismatch"):
            _call(cur, u, "manual_review", fp, table="paper_orders", row=oid)
        assert _receipt_count(cur, fp) == 0

    def test_wrong_epoch(self, conn):
        cur = conn.cursor()
        u, fp = str(uuid.uuid4()), _fp()
        oid = self._order(cur, u, fp)
        with pytest.raises(Exception, match="source_epoch_mismatch"):
            _call(cur, u, "stale_order", fp, epoch="other_epoch",
                  table="paper_orders", row=oid)

    def test_wrong_fingerprint(self, conn):
        cur = conn.cursor()
        u, fp = str(uuid.uuid4()), _fp()
        oid = self._order(cur, u, fp)
        other_fp = _fp()
        with pytest.raises(Exception, match="content_fingerprint_mismatch"):
            _call(cur, u, "stale_order", other_fp, table="paper_orders", row=oid)

    def test_truncated_fingerprint(self, conn):
        cur = conn.cursor()
        u, fp = str(uuid.uuid4()), _fp()
        oid = self._order(cur, u, fp)
        with pytest.raises(Exception, match="content_fingerprint_not_full"):
            _call(cur, u, "stale_order", fp[:8], table="paper_orders", row=oid)

    def test_nonexistent_source(self, conn):
        cur = conn.cursor()
        u, fp = str(uuid.uuid4()), _fp()
        with pytest.raises(Exception, match="source_not_found"):
            _call(cur, u, "stale_order", fp, table="paper_orders",
                  row=str(uuid.uuid4()))

    def test_prose_only_source_rejected(self, conn):
        """A row with a PROSE stamp but no typed marker (the historical class)
        cannot mint a receipt."""
        cur = conn.cursor()
        u, fp = str(uuid.uuid4()), _fp()
        oid = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO paper_orders (id,user_id,broker_response,cancelled_reason) "
            "VALUES (%s,%s,%s,%s)",
            (oid, u, json.dumps({"note": f"reconciled fp {fp[:12]}"}),
             f"stale (fp {fp[:12]})"))
        with pytest.raises(Exception,
                           match="source_not_a_completed_reconciliation"):
            _call(cur, u, "stale_order", fp, table="paper_orders", row=oid)

    def test_not_completed_state_rejected(self, conn):
        cur = conn.cursor()
        u, fp = str(uuid.uuid4()), _fp()
        oid = _new_order(cur, u, _marker("stale_order", fp, status="in_progress"))
        with pytest.raises(Exception, match="reconciliation_not_completed"):
            _call(cur, u, "stale_order", fp, table="paper_orders", row=oid)

    def test_job_runs_source_rejected(self, conn):
        cur = conn.cursor()
        u, fp = str(uuid.uuid4()), _fp()
        with pytest.raises(Exception, match="source_user_scope_unavailable"):
            _call(cur, u, "orphan_run", fp, table="job_runs", row=str(uuid.uuid4()))

    def test_unsupported_source_table_rejected(self, conn):
        cur = conn.cursor()
        u, fp = str(uuid.uuid4()), _fp()
        with pytest.raises(Exception, match="source_table_unsupported"):
            _call(cur, u, "stale_order", fp, table="paper_positions",
                  row=str(uuid.uuid4()))

    def test_bad_kind_arg_rejected(self, conn):
        cur = conn.cursor()
        u, fp = str(uuid.uuid4()), _fp()
        with pytest.raises(Exception, match="receipt_kind_invalid"):
            _call(cur, u, "not_a_kind", fp, table="paper_orders",
                  row=str(uuid.uuid4()))

    def test_provenance_ambiguous_rejected(self, conn):
        cur = conn.cursor()
        u, fp = str(uuid.uuid4()), _fp()
        oid = self._order(cur, u, fp)
        aid = _new_alert(cur, u, _marker("stale_order", fp))
        with pytest.raises(Exception, match="provenance_ambiguous"):
            _call(cur, u, "stale_order", fp, alert=aid, table="paper_orders",
                  row=oid)

    def test_provenance_missing_rejected(self, conn):
        cur = conn.cursor()
        u, fp = str(uuid.uuid4()), _fp()
        with pytest.raises(Exception, match="provenance_missing"):
            _call(cur, u, "stale_order", fp)


# ── Idempotency + conflict ───────────────────────────────────────────────────

class TestIdempotencyAndConflict:
    def test_exact_replay_same_receipt_zero_writes(self, conn):
        cur = conn.cursor()
        u, fp = str(uuid.uuid4()), _fp()
        oid = _new_order(cur, u, _marker("stale_order", fp))
        r1 = _call(cur, u, "stale_order", fp, table="paper_orders", row=oid)
        before = _receipt_count(cur, fp)
        r2 = _call(cur, u, "stale_order", fp, table="paper_orders", row=oid)
        assert r1["receipt_id"] == r2["receipt_id"]
        assert r2["idempotent_replay"] is True
        assert _receipt_count(cur, fp) == before == 1

    def test_conflicting_replay_different_user_rejected(self, conn):
        cur = conn.cursor()
        u, other, fp = str(uuid.uuid4()), str(uuid.uuid4()), _fp()
        o1 = _new_order(cur, u, _marker("stale_order", fp))
        _call(cur, u, "stale_order", fp, table="paper_orders", row=o1)
        # A second, differently-owned source row carries the SAME fingerprint.
        o2 = _new_order(cur, other, _marker("stale_order", fp))
        with pytest.raises(Exception, match="receipt_conflict"):
            _call(cur, other, "stale_order", fp, table="paper_orders", row=o2)
        assert _receipt_count(cur, fp) == 1

    def test_source_alert_single_use(self, conn):
        """One alert row can back at most ONE receipt (partial unique index +
        typed pre-check). Re-stamping the alert with a NEW reconciliation and
        re-issuing is blocked — an alert is a single completed reconciliation."""
        cur = conn.cursor()
        u, fp1, fp2 = str(uuid.uuid4()), _fp(), _fp()
        aid = _new_alert(cur, u, _marker("manual_review", fp1))
        _call(cur, u, "manual_review", fp1, alert=aid)
        # Operator re-stamps the same alert with a different reconciliation and
        # tries to mint a second receipt from it -> single-use guard fires.
        cur.execute("UPDATE risk_alerts SET metadata=%s WHERE id=%s",
                    (_marker("manual_review", fp2), aid))
        with pytest.raises(Exception, match="source_alert_already_receipted"):
            _call(cur, u, "manual_review", fp2, alert=aid)


# ── Concurrency: exactly one receipt under a real race ───────────────────────

class TestConcurrency:
    def test_concurrent_duplicates_yield_one_receipt(self, conn, receipt_pg_schema):
        import pg8000.dbapi as db
        from packages.quantum.tests.pg.receipt.conftest import _DSN

        cur = conn.cursor()
        u, fp = str(uuid.uuid4()), _fp()
        oid = _new_order(cur, u, _marker("stale_order", fp))

        a = db.connect(**_DSN); a.autocommit = False
        b = db.connect(**_DSN); b.autocommit = False
        ca, cb = a.cursor(), b.cursor()
        ca.execute(CALL, (u, "stale_order", EPOCH, fp, None, "paper_orders", oid, "A"))
        ra = ca.fetchone()[0]  # A holds FOR UPDATE + inserted (uncommitted)

        res = {}

        def run_b():
            cb.execute(CALL, (u, "stale_order", EPOCH, fp, None, "paper_orders", oid, "B"))
            res["b"] = cb.fetchone()[0]

        t = threading.Thread(target=run_b)
        t.start()
        time.sleep(0.8)  # B blocks on A's row lock
        a.commit()
        t.join(timeout=10)
        b.commit()
        rb = res["b"]

        assert ra["receipt_id"] == rb["receipt_id"]
        assert ra["idempotent_replay"] is False
        assert rb["idempotent_replay"] is True
        assert _receipt_count(cur, fp) == 1
        a.close(); b.close()


# ── Immutability + privilege hardening (Lane B) ──────────────────────────────

class TestImmutabilityAndPrivileges:
    def test_update_delete_truncate_blocked_for_owner(self, conn):
        """The append-only triggers block row + statement mutation for ALL roles
        (the connection here is the table owner)."""
        cur = conn.cursor()
        u, fp = str(uuid.uuid4()), _fp()
        oid = _new_order(cur, u, _marker("stale_order", fp))
        _call(cur, u, "stale_order", fp, table="paper_orders", row=oid)
        for sql, tok in (
            ("UPDATE fleet_reconciliation_receipts SET created_by='x'", "append-only"),
            ("DELETE FROM fleet_reconciliation_receipts", "append-only"),
            ("TRUNCATE fleet_reconciliation_receipts", "append-only"),
        ):
            with pytest.raises(Exception, match=tok):
                cur.execute(sql)
        assert _receipt_count(cur, fp) == 1

    def test_service_role_grants_are_select_insert_only(self, conn):
        cur = conn.cursor()
        cur.execute(
            "SELECT string_agg(privilege_type, ',' ORDER BY privilege_type) "
            "FROM information_schema.role_table_grants "
            "WHERE table_schema='public' "
            "AND table_name='fleet_reconciliation_receipts' "
            "AND grantee='service_role'")
        assert cur.fetchone()[0] == "INSERT,SELECT"

    def test_service_role_can_issue_receipt_after_hardening(self, conn):
        """The definitive 'does hardening break the writer?' proof: run the whole
        writer RPC AS service_role (post Lane-B revoke) — it still mints a receipt
        (SELECT + INSERT survive; the RPC's SELECT ... FOR UPDATE on the SOURCE
        table is unaffected — Lane B only touched the receipt table's grants)."""
        cur = conn.cursor()
        u, fp = str(uuid.uuid4()), _fp()
        # Mirror production: the service_role key sets the JWT role claim, so the
        # D1 RLS policy (auth.role() = 'service_role') passes. (Our ephemeral
        # auth.role() stub reads this claim GUC.)
        cur.execute("SELECT set_config('request.jwt.claim.role','service_role',false)")
        cur.fetchone()
        cur.execute("SET ROLE service_role")
        try:
            oid = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO paper_orders (id,user_id,broker_response) "
                "VALUES (%s,%s,%s)", (oid, u, _marker("stale_order", fp)))
            out = _call(cur, u, "stale_order", fp, table="paper_orders", row=oid)
            assert out["receipt_id"].startswith("frr_")
            assert out["idempotent_replay"] is False
        finally:
            cur.execute("RESET ROLE")
            cur.execute("SELECT set_config('request.jwt.claim.role','',false)")
            cur.fetchone()
        assert _receipt_count(cur, fp) == 1

    def test_service_role_cannot_update_delete_truncate(self, conn):
        """SET ROLE service_role: SELECT works, mutation is permission-denied
        (the grants are gone — before the trigger even fires)."""
        cur = conn.cursor()
        cur.execute("SET ROLE service_role")
        try:
            cur.execute("SELECT count(*) FROM fleet_reconciliation_receipts")
            cur.fetchone()
            for sql in (
                "UPDATE fleet_reconciliation_receipts SET created_by='x'",
                "DELETE FROM fleet_reconciliation_receipts",
                "TRUNCATE fleet_reconciliation_receipts",
            ):
                with pytest.raises(Exception, match="permission denied"):
                    cur.execute(sql)
        finally:
            cur.execute("RESET ROLE")


# ── MAINTAIN revoke (Lane-B follow-up, migration 20260721011000) ─────────────
# Lane B revoked TRUNCATE/UPDATE/DELETE/REFERENCES/TRIGGER but left PG17's
# MAINTAIN, because the schema-wide default ACL granted service_role ALL
# (arwdDxtm — INCLUDING m) at CREATE-TABLE time. The follow-up migration drops
# that residual so service_role holds EXACTLY {SELECT, INSERT}. These checks use
# has_table_privilege + aclexplode(relacl) — information_schema.role_table_grants
# is MAINTAIN-BLIND (it reports "INSERT,SELECT" even while relacl is 'arm', which
# is exactly why the Lane-B information_schema grant test could not catch this).

_ALL_TABLE_PRIVS = (
    "SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES",
    "TRIGGER", "MAINTAIN",
)


def _effective_privs(cur, role):
    """The set of table privileges ``role`` effectively holds (MAINTAIN-aware)."""
    held = set()
    for p in _ALL_TABLE_PRIVS:
        cur.execute(
            "SELECT has_table_privilege(%s, "
            "'public.fleet_reconciliation_receipts', %s)", (role, p))
        if cur.fetchone()[0]:
            held.add(p)
    return held


def _relacl_privs(cur, role):
    """Privileges granted to ``role`` per pg_class.relacl (aclexplode; MAINTAIN-
    aware, unlike information_schema which omits MAINTAIN)."""
    cur.execute(
        "SELECT coalesce(string_agg(ae.privilege_type, ',' "
        "ORDER BY ae.privilege_type), '') "
        "FROM pg_class c "
        "CROSS JOIN LATERAL aclexplode(c.relacl) ae "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname='public' "
        "AND c.relname='fleet_reconciliation_receipts' "
        "AND ae.grantee = %s::regrole", (role,))
    row = cur.fetchone()[0]
    return {p for p in row.split(",") if p}


def _table_owner(cur):
    cur.execute("SELECT tableowner FROM pg_tables WHERE schemaname='public' "
                "AND tablename='fleet_reconciliation_receipts'")
    return cur.fetchone()[0]


class TestMaintainRevoke:
    def test_service_role_has_no_maintain(self, conn):
        cur = conn.cursor()
        cur.execute("SELECT has_table_privilege('service_role', "
                    "'public.fleet_reconciliation_receipts', 'MAINTAIN')")
        assert cur.fetchone()[0] is False

    def test_service_role_effective_privs_exactly_select_insert(self, conn):
        """MAINTAIN-aware equivalent of the information_schema grant test: the
        FULL effective set is exactly {SELECT, INSERT} — no MAINTAIN residual."""
        cur = conn.cursor()
        assert _effective_privs(cur, "service_role") == {"SELECT", "INSERT"}

    def test_service_role_relacl_is_exactly_select_insert(self, conn):
        """Same fact from pg_class.relacl (the raw ACL the adjudication read):
        service_role's aclitem is exactly {SELECT, INSERT}, no 'm'."""
        cur = conn.cursor()
        assert _relacl_privs(cur, "service_role") == {"SELECT", "INSERT"}

    def test_owner_retains_full_privileges(self, conn):
        """Only service_role loses MAINTAIN; the table OWNER keeps EVERYTHING
        (incl. MAINTAIN), so migrations / autovacuum / maintenance are
        unaffected. Owner resolved dynamically (postgres in prod, the connecting
        role in the harness)."""
        cur = conn.cursor()
        owner = _table_owner(cur)
        assert _effective_privs(cur, owner) == set(_ALL_TABLE_PRIVS)

    def test_writer_still_inserts_and_selects_as_service_role(self, conn):
        """The definitive 'does REVOKE MAINTAIN break the writer?' proof: run the
        writer RPC AS service_role (post-revoke). INSERT + the idempotency SELECT
        both survive; a second call is an idempotent replay (SELECT-only path)."""
        cur = conn.cursor()
        u, fp = str(uuid.uuid4()), _fp()
        cur.execute("SELECT set_config('request.jwt.claim.role','service_role',false)")
        cur.fetchone()
        cur.execute("SET ROLE service_role")
        try:
            oid = str(uuid.uuid4())
            cur.execute("INSERT INTO paper_orders (id,user_id,broker_response) "
                        "VALUES (%s,%s,%s)", (oid, u, _marker("stale_order", fp)))
            first = _call(cur, u, "stale_order", fp, table="paper_orders", row=oid)
            assert first["idempotent_replay"] is False   # INSERT path survives
            replay = _call(cur, u, "stale_order", fp, table="paper_orders", row=oid)
            assert replay["idempotent_replay"] is True    # SELECT-only path survives
            assert replay["receipt_id"] == first["receipt_id"]
        finally:
            cur.execute("RESET ROLE")
            cur.execute("SELECT set_config('request.jwt.claim.role','',false)")
            cur.fetchone()
        assert _receipt_count(cur, fp) == 1

    def test_activation_existence_select_works_as_service_role(self, conn):
        """The activation RPC binds by SELECT count(*) FROM the receipt table.
        That existence SELECT still works as service_role after the revoke.
        Mirror production: the service_role key sets the JWT role claim so the D1
        RLS policy (auth.role() = 'service_role') passes — otherwise RLS filters
        the rows (this is the RLS layer, orthogonal to the MAINTAIN grant)."""
        cur = conn.cursor()
        u, fp = str(uuid.uuid4()), _fp()
        oid = _new_order(cur, u, _marker("stale_order", fp))
        r = _call(cur, u, "stale_order", fp, table="paper_orders", row=oid)
        cur.execute("SELECT set_config('request.jwt.claim.role','service_role',false)")
        cur.fetchone()
        cur.execute("SET ROLE service_role")
        try:
            cur.execute(
                "SELECT count(*) FROM fleet_reconciliation_receipts "
                "WHERE receipt_id=%s AND user_id=%s AND receipt_kind=%s "
                "AND content_fingerprint=%s",
                (r["receipt_id"], u, "stale_order", fp))
            assert cur.fetchone()[0] == 1
        finally:
            cur.execute("RESET ROLE")
            cur.execute("SELECT set_config('request.jwt.claim.role','',false)")
            cur.fetchone()

    def test_update_delete_truncate_still_blocked_as_service_role(self, conn):
        """The MAINTAIN revoke does not weaken immutability: UPDATE/DELETE/TRUNCATE
        remain permission-denied for service_role (grant gone) and, even if a
        grant existed, the append-only triggers still fire (owner-side trigger
        coverage lives in TestImmutabilityAndPrivileges)."""
        cur = conn.cursor()
        cur.execute("SET ROLE service_role")
        try:
            for sql in (
                "UPDATE fleet_reconciliation_receipts SET created_by='x'",
                "DELETE FROM fleet_reconciliation_receipts",
                "TRUNCATE fleet_reconciliation_receipts",
            ):
                with pytest.raises(Exception, match="permission denied"):
                    cur.execute(sql)
        finally:
            cur.execute("RESET ROLE")


# ── No fleet/policy mutation ─────────────────────────────────────────────────

def test_writer_touches_only_receipt_table(conn):
    """Issuing a receipt writes exactly one fleet_reconciliation_receipts row
    and nothing to any fleet/policy table (those tables are not even in this
    ephemeral schema — a stray write would error)."""
    cur = conn.cursor()
    u, fp = str(uuid.uuid4()), _fp()
    oid = _new_order(cur, u, _marker("stale_order", fp))
    _call(cur, u, "stale_order", fp, table="paper_orders", row=oid)
    cur.execute("SELECT count(*) FROM fleet_reconciliation_receipts")
    assert cur.fetchone()[0] >= 1
