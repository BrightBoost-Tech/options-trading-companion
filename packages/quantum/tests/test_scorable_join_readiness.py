"""Lane D ⑤ — scorable-outcome JOIN READINESS: end-to-end producer→consumer contract.

Pins the COMPLETE join a NEXT naturally-closed position traverses to become
scorable, driving the REAL production capture PRODUCERS (never a hand-rolled
marker shape that could drift from what staging actually writes):

    options_scanner.build_scan_spot_capture          (scan-time underlying spot)
      → paper_endpoints._populate_stage_leg_greeks    (per-leg iv + greeks.delta)
      → paper_endpoints._populate_stage_entry_spot     (entry_underlying_spot marker)
      → model_review.fetch_study_rows / is_scorable_row  (the detector predicate)
      → model_review.evaluate_and_maybe_enqueue_review    (enqueue-exactly-once)

WHY THIS EXISTS beside test_model_review_event: that suite hand-rolls a
SIMPLIFIED spot marker ({value, status}) with NO ``source`` field. The row a
Monday first-close actually carries is the FULL stage-seam shape with
``source='scan_time'`` (the 07-18 scan-spot upgrade, PRs #1274). This contract
proves the detector predicate ACCEPTS that scan_time-sourced marker end-to-end —
a predicate/capture mismatch (e.g. a future ``_entry_spot`` that SOURCE-gates
instead of STATUS-gates) would silently make every Monday close non-scorable
while the simplified-marker tests stayed green. It drives the entrypoint through
the deepest real producers and asserts the top-level outcome (scorable →
exactly-one enqueue, event provenance), then pins enqueue-once across ingests
(dedup) and a fresh review on a NEW scorable close (edge-triggered fingerprint).

OBSERVE-ONLY charter unchanged: the capture producers only stamp order_json, and
the detector only reads + enqueues; no selector/ranker/gate/calibration mutation.
"""

import sys
import types

import pytest

# alpaca is import-guarded exactly like test_stage_seam_spot_iv_capture (the
# production submit branch's lazy imports resolve against these stubs).
from packages.quantum.tests._alpaca_stub import ensure_alpaca as _ensure_alpaca

_ensure_alpaca()

from packages.quantum import paper_endpoints as pe  # noqa: E402
from packages.quantum.options_scanner import (  # noqa: E402
    build_scan_spot_capture,
    _SCAN_SPOT_SOURCE,
)
from packages.quantum.analytics import model_review as mr  # noqa: E402

# A debit CALL vertical: buy the 90 call (long), sell the 100 call (short).
LONG_SYM = "O:XYZ260417C00090000"
SHORT_SYM = "O:XYZ260417C00100000"


# ── the REAL stage-time snapshot the truth layer would return (injected at the
#    deepest callee of _populate_stage_leg_greeks) ───────────────────────────
def _snap(iv, delta):
    return {
        "quote": {"bid": 1.0, "ask": 1.2, "mid": 1.1, "last": 1.1},
        "source": "alpaca",
        "retrieved_ts": "2026-07-18T00:00:00",
        "iv": iv,
        "greeks": {"delta": delta, "gamma": 0.02, "theta": -0.03, "vega": 0.10},
    }


def _future_open_order_json(spot=95.0):
    """Build the FUTURE-shaped OPEN order_json exactly as production staging
    would: run the real per-leg greeks/iv populate AND the real entry-spot
    populate (fed the scanner's real scan-time spot capture). Returns the
    order_json whose ``entry_underlying_spot`` carries ``source='scan_time'``."""
    order_json = {
        "legs": [
            {"action": "buy", "symbol": LONG_SYM, "quantity": 1},
            {"action": "sell", "symbol": SHORT_SYM, "quantity": 1},
        ],
        "limit_price": 4.55,
        "contracts": 1,
    }
    snaps = {LONG_SYM: _snap(0.20, 0.60), SHORT_SYM: _snap(0.18, 0.45)}
    # OPEN path: position_id=None → capture runs.
    pe._populate_stage_leg_greeks(
        order_json["legs"], position_id=None, snapshot_fetch=lambda s: snaps[s]
    )
    scan_cap = build_scan_spot_capture(spot, provider_ts_ms=1784548800000)
    pe._populate_stage_entry_spot(order_json, position_id=None, scan_spot=scan_cap)
    return order_json


def _suggestion_order_json():
    """The DECISION-record suggestion legs (geometry authority) — clean legs
    with side/symbol, NO captured market inputs (those live on the OPEN order)."""
    return {
        "legs": [
            {"side": "buy", "symbol": LONG_SYM, "quantity": 1},
            {"side": "sell", "symbol": SHORT_SYM, "quantity": 1},
        ],
        "limit_price": 4.55,
        "contracts": 1,
    }


def _closed_outcome(sid, *, is_paper=False, pnl=40.0):
    return {
        "suggestion_id": sid, "is_paper": is_paper,
        "strategy": "LONG_CALL_DEBIT_SPREAD", "regime": "normal",
        "entry_ts": "2026-03-19T15:19:13Z", "closed_at": "2026-03-25T20:00:00Z",
        "pnl_realized": pnl, "pop_predicted": 0.55, "ev_predicted": 42.0,
    }


def _tables(*sids, is_paper=False, open_order_json=None, job_runs=None):
    """Four source tables for one naturally-closed scorable outcome per sid.
    The OPEN order carries the real future-shaped capture; override via
    ``open_order_json`` (a callable sid->order_json) for the dark-spot case."""
    make_open = open_order_json or (lambda _sid: _future_open_order_json())
    v3, ts, po = [], [], []
    for i, sid in enumerate(sids):
        v3.append(_closed_outcome(sid, is_paper=is_paper, pnl=40.0 + i))
        ts.append({"id": sid, "created_at": "2026-03-19T15:19:13Z",
                   "order_json": _suggestion_order_json()})
        po.append({"suggestion_id": sid, "staged_at": "2026-03-19T15:19:10Z",
                   "order_json": make_open(sid)})
    return {
        "learning_trade_outcomes_v3": v3,
        "trade_suggestions": ts,
        "paper_orders": po,
        "learning_feedback_loops": [],
        "job_runs": list(job_runs or []),
    }


# ── fake supabase client (routes .table() by name; records write verbs) ─────
class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, name, data, writes):
        self._name, self._data, self._writes = name, data, writes

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return _Resp(list(self._data))

    def update(self, p):
        self._writes.append((self._name, "update")); return self

    def insert(self, p):
        self._writes.append((self._name, "insert")); return self

    def upsert(self, p, **k):
        self._writes.append((self._name, "upsert")); return self

    def delete(self):
        self._writes.append((self._name, "delete")); return self


class _FakeClient:
    def __init__(self, tables):
        self._tables = tables
        self.writes = []

    def table(self, name):
        return _Query(name, self._tables.get(name, []), self.writes)


# ── enqueue recorder: stub public_tasks + rq_enqueue so no heavy import ──────
class _EnqueueRecorder:
    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "queued", "job_run_id": "jr-fake-1",
                "job_name": kwargs.get("job_name")}


@pytest.fixture
def stub_enqueue(monkeypatch):
    rec = _EnqueueRecorder()
    stub = types.ModuleType("packages.quantum.public_tasks")
    stub.enqueue_job_run = rec
    monkeypatch.setitem(sys.modules, "packages.quantum.public_tasks", stub)
    rq_stub = types.ModuleType("packages.quantum.jobs.rq_enqueue")
    rq_stub.BACKGROUND_QUEUE = "background"
    monkeypatch.setitem(sys.modules, "packages.quantum.jobs.rq_enqueue", rq_stub)
    return rec


# ── 1. PRODUCER shape: the real capture stamps a scan_time-sourced marker ────
class TestCaptureProducerShape:
    def test_open_order_carries_scan_time_populated_spot(self):
        oj = _future_open_order_json(spot=95.0)
        marker = oj["entry_underlying_spot"]
        # This IS the Monday-first-close shape. The scanner CARRIER labels its
        # own source 'scanner_underlying_quote_mid'; the STAGE SEAM re-stamps the
        # persisted marker source to 'scan_time' (pe._SPOT_SOURCE_SCAN_TIME) —
        # the label the detector predicate must accept.
        assert _SCAN_SPOT_SOURCE == "scanner_underlying_quote_mid"  # carrier label
        assert marker["source"] == pe._SPOT_SOURCE_SCAN_TIME == "scan_time"
        assert marker["status"] == "populated_at_stage"
        assert marker["value"] == 95.0
        # per-leg iv + greeks.delta landed from the real greeks populate
        for leg in oj["legs"]:
            assert leg["iv_status"] == "populated_at_stage"
            assert leg["iv"] is not None
            assert leg["greeks"]["delta"] is not None
        # the marker key is the OPEN gate the detector/study LATERAL keys on
        assert "entry_underlying_spot" in oj


# ── 2. PREDICATE/CAPTURE match: scan_time-sourced marker IS scorable ─────────
class TestPredicateAcceptsScanTimeSource:
    def test_scan_time_marker_row_is_scorable(self):
        rows = mr.fetch_study_rows(_FakeClient(_tables("s-1")))
        # the mapped row's spot marker carries the production scan_time source
        assert rows["s-1"]["entry_underlying_spot"]["source"] == "scan_time"
        # …and the detector predicate accepts it (status-gated, not source-gated)
        assert mr.is_scorable_row(rows["s-1"]) is True
        assert mr.scorable_record_ids(rows) == ["s-1"]

    def test_typed_unavailable_scan_marker_is_not_scorable(self):
        # A scan carrier whose value was non-positive → typed-unavailable marker
        # (H9). Same PRODUCER, dark output → challenger can't price → NOT scorable.
        def dark_open(_sid):
            oj = _suggestion_order_json()
            pe._populate_stage_leg_greeks(
                oj["legs"], position_id=None,
                snapshot_fetch=lambda s: _snap(0.20, 0.60))
            pe._populate_stage_entry_spot(
                oj, position_id=None,
                scan_spot=build_scan_spot_capture(0.0))  # non-positive → unavailable
            assert oj["entry_underlying_spot"]["status"] == "unavailable_at_stage"
            return oj

        rows = mr.fetch_study_rows(_FakeClient(_tables("s-1", open_order_json=dark_open)))
        assert mr.is_scorable_row(rows["s-1"]) is False
        assert mr.scorable_record_ids(rows) == []


# ── 3. END-TO-END: scorable close → exactly-one enqueue, event provenance ────
class TestEnqueueExactlyOnce:
    def test_future_close_enqueues_once_with_event_provenance(self, stub_enqueue):
        out = mr.evaluate_and_maybe_enqueue_review(_FakeClient(_tables("s-live-1")))

        assert out["enqueued"] is True
        assert out["scorable_count"] == 1
        assert len(stub_enqueue.calls) == 1  # exactly one — no storm
        call = stub_enqueue.calls[0]
        assert call["job_name"] == "model_review_event"
        assert call["queue_name"] == "background"
        assert call["origin"]["origin"] == "event"
        assert call["origin"]["trigger_actor_class"] == "new_scorable_close"
        assert call["idempotency_key"] == f"model_review-{out['fingerprint']}"
        assert call["payload"]["scorable_record_ids"] == ["s-live-1"]

    def test_same_set_second_ingest_suppressed(self, stub_enqueue):
        # enqueue-ONCE ACROSS INGESTS: seed the fingerprint the detector will
        # compute into a prior review → a repeat ingest (no new close) suppresses.
        fp = mr.scorable_fingerprint(["s-1"], mr._model_set_version())
        tables = _tables("s-1", job_runs=[
            {"payload": {"fingerprint": fp}, "result": None, "status": "queued"}])
        out = mr.evaluate_and_maybe_enqueue_review(_FakeClient(tables))
        assert out["status"] == "suppressed_duplicate"
        assert out["enqueued"] is False
        assert stub_enqueue.calls == []

    def test_new_scorable_close_triggers_fresh_review(self, stub_enqueue):
        # First close → fingerprint A.
        out_a = mr.evaluate_and_maybe_enqueue_review(_FakeClient(_tables("s-1")))
        assert out_a["enqueued"] is True
        fp_a = out_a["fingerprint"]

        # A NEW scorable close arrives; the prior review (fp_a) already ran.
        tables_b = _tables("s-1", "s-2", job_runs=[
            {"payload": {"fingerprint": fp_a}, "result": {"fingerprint": fp_a,
             "scorable_count": 1}, "status": "succeeded"}])
        out_b = mr.evaluate_and_maybe_enqueue_review(_FakeClient(tables_b))

        # edge-triggered: new set → new fingerprint → fresh enqueue (not suppressed)
        assert out_b["enqueued"] is True
        assert out_b["scorable_count"] == 2
        assert out_b["fingerprint"] != fp_a
        assert len(stub_enqueue.calls) == 2  # A then B, once each


# ── 4. COHORTS SEPARATE end-to-end (live vs shadow never co-mingled) ─────────
class TestCohortsSeparate:
    def test_live_and_shadow_close_scored_in_separate_cohorts(self):
        # one live + one shadow future-shaped close, run the full review body
        tables = _tables("s-live", is_paper=False)
        shadow = _tables("s-shadow", is_paper=True)
        for k in tables:
            tables[k] = tables[k] + shadow[k]
        client = _FakeClient(tables)

        result = mr.run_review(client, {
            "fingerprint": "fp-test",
            "model_version": mr._model_set_version(),
            "scorable_record_ids": ["s-live", "s-shadow"],
            "boundary_crossed": [],
        })

        assert result["ok"] is True
        assert result["observe_only"] is True
        assert result["scorable_count"] == 2
        cohorts = {c["cohort"]: c for c in result["cohorts"]}
        assert set(cohorts) == {"live", "shadow"}
        assert cohorts["live"]["is_paper"] is False
        assert cohorts["shadow"]["is_paper"] is True
        # BOTH models score the captured rows (adapter needs delta; challenger
        # needs spot+iv) — proving the scan_time capture is consumable end-to-end
        assert cohorts["live"]["models"]["frozen_adapter"]["scored"] == 1
        assert cohorts["live"]["models"]["lognormal_challenger"]["scored"] == 1
        assert cohorts["shadow"]["models"]["lognormal_challenger"]["scored"] == 1
        # OBSERVE-ONLY: the review wrote NOTHING to any table
        assert client.writes == []
