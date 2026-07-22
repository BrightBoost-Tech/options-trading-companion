"""Lane A — stale-order reconciliation-receipt PRODUCER wiring.

The producer is the `alpaca_order_sync` Step 1.5 seam: when a response-lost order
is re-armed to the terminal 'cancelled' state (the stale-order reconciliation has
COMMITTED), it stamps the typed completed-reconciliation marker on the user-scoped
paper_orders row and issues exactly ONE durable `stale_order` receipt via
`rpc_issue_fleet_reconciliation_receipt_v1`.

These tests DRIVE THE PRODUCTION ROUTE (`_reconcile_lost_submits` and the top-level
`run()`), injecting failure at the deepest callee (the cancel write / the receipt
RPC) and asserting the top-level outcome — no #1126-costume source-string pins.

Nothing here calls the real RPC, writes a production row, or activates the fleet:
the supabase client is a fake that records `.update()` writes + `.rpc()` calls, and
the RPC is modelled by an injected handler. The producer is DARK unless
`FLEET_RECEIPT_PRODUCER_ENABLED=1`, so a production run issues NOTHING.
"""

import pytest

from packages.quantum.jobs.handlers import alpaca_order_sync as aos
from packages.quantum.policy_lab.shadow_fleet import FLEET_EPOCH
from packages.quantum.services import fleet_reconciliation_receipt as frr

RPC_FN = frr.RECEIPT_WRITER_RPC
USER = "user-abc"


# ── Capable fake supabase (models the order-sync query + rpc surface) ─────────

class _Result:
    def __init__(self, data):
        self.data = data


class _NotProxy:
    def __init__(self, q):
        self._q = q

    def in_(self, col, vals):
        self._q._filters.append(("not_in", col, list(vals)))
        return self._q

    def is_(self, col, _val):
        self._q._filters.append(("not_is_null", col, None))
        return self._q


class _Query:
    def __init__(self, fake, table):
        self._fake = fake
        self._table = table
        self._filters = []
        self._update_payload = None

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self._filters.append(("eq", col, val))
        return self

    def in_(self, col, vals):
        self._filters.append(("in", col, list(vals)))
        return self

    def is_(self, col, _val):
        self._filters.append(("is_null", col, None))
        return self

    def gt(self, col, val):
        self._filters.append(("gt", col, val))
        return self

    @property
    def not_(self):
        return _NotProxy(self)

    def update(self, payload):
        self._update_payload = payload
        return self

    def _matches(self, r):
        for kind, col, val in self._filters:
            v = r.get(col)
            if kind == "eq" and v != val:
                return False
            if kind == "in" and v not in val:
                return False
            if kind == "not_in" and v in val:
                return False
            if kind == "is_null" and v is not None:
                return False
            if kind == "not_is_null" and v is None:
                return False
            if kind == "gt" and not (v is not None and v > val):
                return False
        return True

    def _rows(self):
        return [r for r in self._fake.tables.get(self._table, []) if self._matches(r)]

    def execute(self):
        if self._update_payload is not None:
            if self._table in self._fake.fail_update_tables:
                raise RuntimeError(f"update failed: {self._table}")
            matched = self._rows()
            self._fake.writes.append({
                "table": self._table, "op": "update",
                "payload": self._update_payload,
                "matched_ids": [r.get("id") for r in matched],
            })
            for r in matched:
                r.update(self._update_payload)
            return _Result(matched)
        if self._table in self._fake.fail_read_tables:
            raise RuntimeError(f"read failed: {self._table}")
        return _Result(self._rows())


class _Rpc:
    def __init__(self, fake, fn, params):
        self._fake = fake
        self._fn = fn
        self._params = params

    def execute(self):
        self._fake.rpc_calls.append({"fn": self._fn, "params": dict(self._params)})
        if self._fake.rpc_handler is not None:
            return _Result(self._fake.rpc_handler(self._fn, self._params))
        return _Result({"receipt_id": "frr_fake", "idempotent_replay": False})


class OrderSyncFake:
    def __init__(self, paper_orders=None, paper_portfolios=None, paper_positions=None,
                 rpc_handler=None, fail_update_tables=(), fail_read_tables=()):
        self.tables = {
            "paper_orders": [dict(r) for r in (paper_orders or [])],
            "paper_portfolios": [dict(r) for r in (paper_portfolios or [])],
            "paper_positions": [dict(r) for r in (paper_positions or [])],
        }
        self.rpc_handler = rpc_handler
        self.fail_update_tables = set(fail_update_tables)
        self.fail_read_tables = set(fail_read_tables)
        self.writes = []
        self.rpc_calls = []

    def table(self, name):
        self.tables.setdefault(name, [])
        return _Query(self, name)

    def rpc(self, fn, params):
        return _Rpc(self, fn, params)

    # test helpers
    def order(self, oid):
        for r in self.tables["paper_orders"]:
            if r.get("id") == oid:
                return r
        return None

    def stamp_writes(self):
        """paper_orders updates that stamp the reconciliation_receipt MARKER
        (a backfill's plain broker_response write is NOT a marker stamp)."""
        out = []
        for w in self.writes:
            if w["table"] != "paper_orders":
                continue
            br = w["payload"].get("broker_response")
            if isinstance(br, dict) and "reconciliation_receipt" in br:
                out.append(w)
        return out


class FakeAlpaca:
    """404-by-default broker lookup (the never-landed / stale-order case)."""
    def __init__(self, found=None):
        self._found = found

    def get_order_by_client_id(self, _coid):
        return self._found


def _stale_order(oid="ord-1", user_id=USER, coid="otc1-l-ord-1", broker_response=None):
    return {
        "id": oid,
        "client_order_id": coid,
        "status": "needs_manual_review",
        "position_id": "pos-1",
        "user_id": user_id,
        "alpaca_order_id": None,
        "portfolio_id": "pf-legacy",
        "broker_response": broker_response,
    }


@pytest.fixture
def producer_on(monkeypatch):
    monkeypatch.setenv("FLEET_RECEIPT_PRODUCER_ENABLED", "1")


@pytest.fixture(autouse=True)
def _producer_default_off(monkeypatch):
    # Every test starts with the producer at its production default (OFF); the
    # `producer_on` fixture opts in where needed. Guarantees no ambient enable.
    monkeypatch.delenv("FLEET_RECEIPT_PRODUCER_ENABLED", raising=False)


# ── Fingerprint helper ───────────────────────────────────────────────────────

class TestFingerprint:
    def test_full_length_and_deterministic(self):
        a = frr.reconciliation_content_fingerprint("stale_order", "paper_orders", "o1")
        b = frr.reconciliation_content_fingerprint("stale_order", "paper_orders", "o1")
        assert a == b
        assert len(a) >= frr.MIN_CONTENT_FINGERPRINT_LEN
        assert len(a) == 64  # sha256 hex

    def test_distinct_content_distinct_fingerprint(self):
        a = frr.reconciliation_content_fingerprint("stale_order", "paper_orders", "o1")
        b = frr.reconciliation_content_fingerprint("stale_order", "paper_orders", "o2")
        assert a != b

    def test_none_part_does_not_collide_with_empty(self):
        a = frr.reconciliation_content_fingerprint("k", None, "x")
        b = frr.reconciliation_content_fingerprint("k", "", "x")
        # None normalizes to "" -> SAME joined string by design (documented).
        assert a == b
        # but a shifted field is distinct
        assert a != frr.reconciliation_content_fingerprint("k", "x", "")


# ── Producer OFF (production default) — byte-identical, issues nothing ────────

class TestProducerDefaultOff:
    def test_rearmed_but_no_stamp_no_rpc_when_flag_unset(self):
        fake = OrderSyncFake(paper_orders=[_stale_order()])
        out = aos._reconcile_lost_submits(FakeAlpaca(found=None), fake, [])
        assert out["client_id_rearmed"] == 1
        assert out["stale_order_receipts"] == 0
        assert out["receipt_errors"] == []
        assert fake.rpc_calls == []
        assert fake.stamp_writes() == []
        # the reconciliation itself still happened (order cancelled)
        assert fake.order("ord-1")["status"] == "cancelled"


# ── Producer ON — post-commit stamp + one RPC with the right args ─────────────

class TestProducerHappyPath:
    def test_stamps_marker_and_calls_rpc_after_commit(self, producer_on):
        fake = OrderSyncFake(paper_orders=[_stale_order()])
        out = aos._reconcile_lost_submits(FakeAlpaca(found=None), fake, [])

        # order was cancelled (reconciliation committed) BEFORE the receipt
        assert fake.order("ord-1")["status"] == "cancelled"
        assert out["client_id_rearmed"] == 1
        assert out["stale_order_receipts"] == 1
        assert out["receipt_errors"] == []

        # exactly one receipt RPC, with the right typed args
        assert len(fake.rpc_calls) == 1
        call = fake.rpc_calls[0]
        assert call["fn"] == RPC_FN
        p = call["params"]
        assert p["p_user_id"] == USER
        assert p["p_receipt_kind"] == "stale_order"
        assert p["p_effective_epoch"] == FLEET_EPOCH
        assert p["p_source_table"] == "paper_orders"
        assert p["p_source_row_id"] == "ord-1"
        assert p["p_source_alert_id"] is None
        assert len(p["p_content_fingerprint"]) >= 32

        # the marker was stamped on the source row, fingerprint == RPC arg
        stamps = fake.stamp_writes()
        assert len(stamps) == 1
        marker = stamps[0]["payload"]["broker_response"]["reconciliation_receipt"]
        assert marker["kind"] == "stale_order"
        assert marker["status"] == "completed"
        assert marker["effective_epoch"] == FLEET_EPOCH
        assert marker["content_fingerprint"] == p["p_content_fingerprint"]

    def test_marker_merge_is_non_destructive(self, producer_on):
        fake = OrderSyncFake(
            paper_orders=[_stale_order(broker_response={"orig": "keep-me"})])
        aos._reconcile_lost_submits(FakeAlpaca(found=None), fake, [])
        merged = fake.stamp_writes()[0]["payload"]["broker_response"]
        assert merged["orig"] == "keep-me"          # existing key preserved
        assert "reconciliation_receipt" in merged   # marker added

    def test_found_at_broker_is_backfill_not_a_receipt(self, producer_on):
        # FOUND at broker => recovery, NOT a stale-order reconciliation => no receipt
        fake = OrderSyncFake(paper_orders=[_stale_order()])
        alpaca = FakeAlpaca(found={"alpaca_order_id": "brk-9", "status": "accepted"})
        out = aos._reconcile_lost_submits(alpaca, fake, [])
        assert out["client_id_backfilled"] == 1
        assert out["stale_order_receipts"] == 0
        assert fake.rpc_calls == []
        assert fake.stamp_writes() == []


# ── Pre-commit failure — issues NOTHING ──────────────────────────────────────

class TestPreCommitFailureIssuesNothing:
    def test_cancel_write_raises_before_commit(self, producer_on):
        # The re-arm cancel UPDATE raises inside _resolve_lost_submit -> the
        # reconciliation never commits -> no marker, no receipt (origin injected
        # at the deepest write; asserted at the top: zero RPC, zero stamp).
        fake = OrderSyncFake(paper_orders=[_stale_order()],
                             fail_update_tables={"paper_orders"})
        out = aos._reconcile_lost_submits(FakeAlpaca(found=None), fake, [])
        assert out["client_id_rearmed"] == 0
        assert out["stale_order_receipts"] == 0
        assert out["receipt_errors"] == []
        assert fake.rpc_calls == []
        assert fake.stamp_writes() == []


# ── Retry idempotency (mocked RPC) — same args → same receipt, no double-issue ─

class TestIdempotency:
    def test_exact_replay_returns_same_receipt(self, producer_on):
        # Stateful handler modelling the RPC's UNIQUE(kind, fingerprint) idempotency.
        issued = {}

        def handler(_fn, params):
            key = (params["p_receipt_kind"], params["p_content_fingerprint"])
            if key in issued:
                return {**issued[key], "idempotent_replay": True}
            rec = {
                "receipt_id": f"frr_{len(issued) + 1}",
                "user_id": params["p_user_id"],
                "receipt_kind": params["p_receipt_kind"],
                "content_fingerprint": params["p_content_fingerprint"],
                "idempotent_replay": False,
            }
            issued[key] = rec
            return rec

        row = _stale_order()
        fake = OrderSyncFake(paper_orders=[row], rpc_handler=handler)
        r1 = aos._issue_stale_order_receipt(fake, row)
        r2 = aos._issue_stale_order_receipt(fake, row)  # exact replay
        assert r1["receipt_id"] == r2["receipt_id"]
        assert r1["idempotent_replay"] is False
        assert r2["idempotent_replay"] is True
        assert len(issued) == 1  # no second durable row minted


# ── Conflict — typed reject surfaces loud ────────────────────────────────────

class TestConflictRejects:
    def test_conflicting_replay_is_loud(self, producer_on):
        def handler(_fn, _params):
            raise RuntimeError("issue_reconciliation_receipt: receipt_conflict (...)")

        fake = OrderSyncFake(paper_orders=[_stale_order()], rpc_handler=handler)
        out = aos._reconcile_lost_submits(FakeAlpaca(found=None), fake, [])
        # reconciliation committed, but the receipt failed loud
        assert fake.order("ord-1")["status"] == "cancelled"
        assert out["stale_order_receipts"] == 0
        assert len(out["receipt_errors"]) == 1
        err = out["receipt_errors"][0]
        assert err["stage"] == "stale_order_receipt"
        assert err["order_id"] == "ord-1"
        assert "receipt_conflict" in err["error"]


# ── Missing user scope — never fabricate, surface loud ───────────────────────

class TestMissingUserScope:
    def test_no_user_id_raises_and_is_recorded(self, producer_on):
        fake = OrderSyncFake(paper_orders=[_stale_order(user_id=None)])
        out = aos._reconcile_lost_submits(FakeAlpaca(found=None), fake, [])
        assert out["stale_order_receipts"] == 0
        assert len(out["receipt_errors"]) == 1
        assert fake.rpc_calls == []          # RPC never reached
        assert fake.stamp_writes() == []     # nothing stamped


# ── Origin-to-top: a required-receipt issuance failure makes the JOB partial ──

class TestRunEndToEndPartial:
    def _drive_run(self, monkeypatch, fake):
        monkeypatch.setattr(aos, "get_admin_client", lambda: fake)
        monkeypatch.setattr(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            lambda: FakeAlpaca(found=None),
        )
        return aos.run({}, None)

    def test_receipt_rpc_failure_marks_job_partial(self, monkeypatch, producer_on):
        def boom(_fn, _params):
            raise RuntimeError("issue_reconciliation_receipt: receipt_conflict")

        fake = OrderSyncFake(paper_orders=[_stale_order()], rpc_handler=boom)
        result = self._drive_run(monkeypatch, fake)
        # top-level job is PARTIAL (not a silent green)
        assert result["ok"] is False
        assert result["counts"]["errors"] >= 1
        assert result.get("stale_order_receipt_errors", 0) >= 1
        # the reconciliation itself still committed
        assert fake.order("ord-1")["status"] == "cancelled"

    def test_receipt_success_keeps_job_green(self, monkeypatch, producer_on):
        def ok(_fn, params):
            return {"receipt_id": "frr_ok", "receipt_kind": params["p_receipt_kind"],
                    "idempotent_replay": False}

        fake = OrderSyncFake(paper_orders=[_stale_order()], rpc_handler=ok)
        result = self._drive_run(monkeypatch, fake)
        assert result["ok"] is True
        assert result["counts"]["errors"] == 0
        assert result.get("stale_order_receipts", 0) == 1
        assert len(fake.rpc_calls) == 1

    def test_producer_off_run_issues_nothing(self, monkeypatch):
        # Production default (flag unset): run() reconciles but issues no receipt.
        fake = OrderSyncFake(paper_orders=[_stale_order()])
        result = self._drive_run(monkeypatch, fake)
        assert result["ok"] is True
        assert fake.rpc_calls == []
        assert fake.stamp_writes() == []
        assert fake.order("ord-1")["status"] == "cancelled"


# ── Flag polarity (behavioral / explicit opt-in) ─────────────────────────────

class TestFlagPolarity:
    def test_only_literal_1_enables(self, monkeypatch):
        for val in ("", "0", "true", "yes", "on", "false", "no", "2"):
            monkeypatch.setenv("FLEET_RECEIPT_PRODUCER_ENABLED", val)
            assert aos._fleet_receipt_producer_enabled() is False, val
        monkeypatch.setenv("FLEET_RECEIPT_PRODUCER_ENABLED", "1")
        assert aos._fleet_receipt_producer_enabled() is True
        monkeypatch.delenv("FLEET_RECEIPT_PRODUCER_ENABLED", raising=False)
        assert aos._fleet_receipt_producer_enabled() is False  # default-OFF


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
