"""Lane J — event-driven model review on new scorable close (OBSERVE-ONLY).

Route-driven contract pins (inject at the DEEPEST callee — a fake supabase
client feeding the tables the fetch reads — and assert at the TOP: the detector
return / the enqueue call / the handler result). Covers:

- ingest tail with a synthetic SCORABLE close → exactly ONE enqueue, background
  queue, origin event/new_scorable_close (driven end-to-end through
  paper_learning_ingest.run);
- repeated ingest (same scorable set already reviewed) → SUPPRESSED, no enqueue;
- a NON-scorable close (no ⑤ capture markers) → no enqueue;
- the review handler on synthetic rows → result truth, live vs shadow cohorts
  SEPARATE, ZERO mutations on the client (observe-only);
- sample-boundary crossing stamped in the result;
- the scheduler watchdog does NOT expect the event-driven job.
"""

import sys
import types
from unittest.mock import patch

import pytest

from packages.quantum.analytics import model_review as mr

LONG_SYM = "O:XYZ260417C00090000"
SHORT_SYM = "O:XYZ260417C00100000"


# ── fake supabase client (routes .table() by name; records writes) ──────────
class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    """Ignores filter args (the fetch does its own Python-side join by id) and
    returns the table's canned rows. Records any write verb so a test can assert
    observe-only (zero mutations)."""

    def __init__(self, name, data, writes):
        self._name = name
        self._data = data
        self._writes = writes

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def not_(self, *a, **k):
        return self

    def is_(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return _Resp(list(self._data))

    # write verbs — should NEVER be called by the observe-only review paths
    def update(self, payload):
        self._writes.append((self._name, "update", payload))
        return self

    def insert(self, payload):
        self._writes.append((self._name, "insert", payload))
        return self

    def upsert(self, payload, **k):
        self._writes.append((self._name, "upsert", payload))
        return self

    def delete(self):
        self._writes.append((self._name, "delete", None))
        return self


class _FakeClient:
    def __init__(self, tables):
        self._tables = tables
        self.writes = []

    def table(self, name):
        return _Query(name, self._tables.get(name, []), self.writes)


# ── synthetic scorable rows (⑤ stage-seam capture present) ──────────────────
def _captured_leg(sym, action, iv, delta):
    return {"action": action, "symbol": sym, "quantity": 1,
            "iv": iv, "iv_status": "populated_at_stage", "iv_source": "alpaca",
            "greeks": {"delta": delta, "gamma": 0.02, "theta": -0.03, "vega": 0.10},
            "greeks_status": "populated_at_stage"}


def _scorable_tables(sid, *, is_paper=False, pnl=40.0, with_markers=True,
                     job_runs=None, extra_v3=None, extra_ts=None, extra_po=None):
    """Build the four source tables for ONE scorable (or, with_markers=False,
    NON-scorable) closed outcome, plus optional extra rows for multi-row cases."""
    v3 = [{
        "suggestion_id": sid, "is_paper": is_paper,
        "strategy": "LONG_CALL_DEBIT_SPREAD", "regime": "normal",
        "entry_ts": "2026-03-19T15:19:13Z", "closed_at": "2026-03-25T20:00:00Z",
        "pnl_realized": pnl, "pop_predicted": 0.55, "ev_predicted": 42.0,
    }] + list(extra_v3 or [])
    ts = [{
        "id": sid, "created_at": "2026-03-19T15:19:13Z",
        "order_json": {
            "legs": [
                {"side": "buy", "symbol": LONG_SYM, "quantity": 1},
                {"side": "sell", "symbol": SHORT_SYM, "quantity": 1},
            ],
            "limit_price": 4.55, "contracts": 1,
        },
    }] + list(extra_ts or [])
    po = list(extra_po or [])
    if with_markers:
        po = [{
            "suggestion_id": sid, "staged_at": "2026-03-19T15:19:10Z",
            "order_json": {
                "legs": [
                    _captured_leg(LONG_SYM, "buy", 0.20, 0.60),
                    _captured_leg(SHORT_SYM, "sell", 0.18, 0.45),
                ],
                "entry_underlying_spot": {"value": 95.0, "status": "populated_at_stage"},
            },
        }] + po
    return {
        "learning_trade_outcomes_v3": v3,
        "trade_suggestions": ts,
        "paper_orders": po,
        "learning_feedback_loops": [],
        "job_runs": list(job_runs or []),
    }


def _many_scorable_tables(n, *, is_paper=False, job_runs=None):
    """n scorable live outcomes with distinct suggestion ids (same geometry)."""
    base = _scorable_tables("s-0", is_paper=is_paper, job_runs=job_runs)
    for i in range(1, n):
        sid = f"s-{i}"
        base["learning_trade_outcomes_v3"].append({
            "suggestion_id": sid, "is_paper": is_paper,
            "strategy": "LONG_CALL_DEBIT_SPREAD", "regime": "normal",
            "entry_ts": "2026-03-19T15:19:13Z", "closed_at": f"2026-03-2{i}T20:00:00Z",
            "pnl_realized": 10.0 * (1 if i % 2 else -1), "pop_predicted": 0.55,
            "ev_predicted": 42.0,
        })
        base["trade_suggestions"].append({
            "id": sid, "created_at": "2026-03-19T15:19:13Z",
            "order_json": {"legs": [
                {"side": "buy", "symbol": LONG_SYM, "quantity": 1},
                {"side": "sell", "symbol": SHORT_SYM, "quantity": 1}],
                "limit_price": 4.55, "contracts": 1},
        })
        base["paper_orders"].append({
            "suggestion_id": sid, "staged_at": "2026-03-19T15:19:10Z",
            "order_json": {"legs": [
                _captured_leg(LONG_SYM, "buy", 0.20, 0.60),
                _captured_leg(SHORT_SYM, "sell", 0.18, 0.45)],
                "entry_underlying_spot": {"value": 95.0, "status": "populated_at_stage"}},
        })
    return base


# ── enqueue recorder: stub public_tasks so no heavy import + capture the call ─
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
    # rq_enqueue is light (BACKGROUND_QUEUE constant) but pulls redis/rq/fastapi;
    # stub it too for a fully hermetic test.
    rq_stub = types.ModuleType("packages.quantum.jobs.rq_enqueue")
    rq_stub.BACKGROUND_QUEUE = "background"
    monkeypatch.setitem(sys.modules, "packages.quantum.jobs.rq_enqueue", rq_stub)
    return rec


# ── scorability predicate (reuses the study's marker-gated mapper) ──────────
class TestScorability:
    def test_marker_populated_row_is_scorable(self):
        t = _scorable_tables("s-1", with_markers=True)
        rows = mr.fetch_study_rows(_FakeClient(t))
        assert mr.scorable_record_ids(rows) == ["s-1"]

    def test_no_capture_markers_not_scorable(self):
        t = _scorable_tables("s-1", with_markers=False)
        rows = mr.fetch_study_rows(_FakeClient(t))
        assert mr.scorable_record_ids(rows) == []

    def test_dark_spot_marker_not_scorable(self):
        t = _scorable_tables("s-1", with_markers=True)
        # typed-unavailable spot → challenger cannot price → not scorable (H9)
        t["paper_orders"][0]["order_json"]["entry_underlying_spot"] = {
            "value": None, "status": "unavailable_at_stage"}
        rows = mr.fetch_study_rows(_FakeClient(t))
        assert mr.scorable_record_ids(rows) == []


class TestFingerprint:
    def test_stable_and_set_sensitive(self):
        v = "td-test@1"
        a = mr.scorable_fingerprint(["b", "a"], v)
        assert a == mr.scorable_fingerprint(["a", "b"], v)  # order-insensitive
        assert a != mr.scorable_fingerprint(["a"], v)        # set-sensitive
        assert a != mr.scorable_fingerprint(["a", "b"], "td-test@2")  # version-sensitive


# ── DETECTOR (learning-ingest tail entrypoint) ──────────────────────────────
class TestDetector:
    def test_scorable_close_enqueues_once_with_event_provenance(self, stub_enqueue):
        client = _FakeClient(_scorable_tables("s-live-1"))
        out = mr.evaluate_and_maybe_enqueue_review(client)

        assert out["enqueued"] is True
        assert out["scorable_count"] == 1
        assert len(stub_enqueue.calls) == 1  # exactly one enqueue, no storm
        call = stub_enqueue.calls[0]
        assert call["job_name"] == "model_review_event"
        assert call["queue_name"] == "background"
        assert call["origin"]["origin"] == "event"
        assert call["origin"]["trigger_actor_class"] == "new_scorable_close"
        # fingerprint is the durable dedup key + rides the payload
        assert call["idempotency_key"] == f"model_review-{out['fingerprint']}"
        assert call["payload"]["scorable_record_ids"] == ["s-live-1"]

    def test_non_scorable_close_does_not_enqueue(self, stub_enqueue):
        client = _FakeClient(_scorable_tables("s-1", with_markers=False))
        out = mr.evaluate_and_maybe_enqueue_review(client)
        assert out["enqueued"] is False
        assert out["status"] == "no_scorable_closes"
        assert stub_enqueue.calls == []

    def test_same_fingerprint_prior_review_suppresses(self, stub_enqueue):
        # Pre-compute the fingerprint the detector will produce, seed a prior
        # completed review with it in job_runs.result → suppressed.
        fp = mr.scorable_fingerprint(["s-1"], mr._model_set_version())
        t = _scorable_tables("s-1", job_runs=[
            {"payload": {"fingerprint": "other"},
             "result": {"fingerprint": fp, "scorable_count": 1},
             "status": "succeeded"}])
        out = mr.evaluate_and_maybe_enqueue_review(_FakeClient(t))
        assert out["status"] == "suppressed_duplicate"
        assert out["enqueued"] is False
        assert stub_enqueue.calls == []

    def test_pending_review_in_payload_also_suppresses(self, stub_enqueue):
        # A still-pending prior review (result null, fingerprint only in payload)
        # must also suppress — no double-enqueue while the first is in flight.
        fp = mr.scorable_fingerprint(["s-1"], mr._model_set_version())
        t = _scorable_tables("s-1", job_runs=[
            {"payload": {"fingerprint": fp}, "result": None, "status": "queued"}])
        out = mr.evaluate_and_maybe_enqueue_review(_FakeClient(t))
        assert out["status"] == "suppressed_duplicate"
        assert stub_enqueue.calls == []

    def test_sample_boundary_crossing_stamped(self, stub_enqueue):
        # 8 scorable closes, prior review saw 7 (different set) → crosses 8.
        t = _many_scorable_tables(8, job_runs=[
            {"result": {"fingerprint": "old", "scorable_count": 7},
             "payload": {}, "status": "succeeded"}])
        out = mr.evaluate_and_maybe_enqueue_review(_FakeClient(t))
        assert out["enqueued"] is True
        assert out["scorable_count"] == 8
        assert 8 in out["boundary_crossed"]
        assert stub_enqueue.calls[0]["payload"]["boundary_crossed"] == out["boundary_crossed"]

    def test_detector_never_raises_on_broken_client(self, stub_enqueue):
        class _Boom:
            def table(self, name):
                raise RuntimeError("db down")
        out = mr.evaluate_and_maybe_enqueue_review(_Boom())
        assert out["enqueued"] is False
        assert out["status"] in ("error", "no_scorable_closes")
        assert stub_enqueue.calls == []


# ── REVIEW HANDLER (job entrypoint) ─────────────────────────────────────────
class TestReviewHandler:
    def test_handler_result_truth_cohorts_separate_zero_mutations(self):
        # one live + one shadow scorable outcome
        t = _scorable_tables("s-live", is_paper=False, pnl=40.0)
        shadow = _scorable_tables("s-shadow", is_paper=True, pnl=500.0)
        for k in t:
            t[k] = t[k] + shadow[k]
        client = _FakeClient(t)

        from packages.quantum.jobs.handlers import model_review_event as handler
        with patch.object(handler, "get_admin_client", return_value=client):
            result = handler.run({
                "fingerprint": "fp-test",
                "model_version": mr._model_set_version(),
                "scorable_record_ids": ["s-live", "s-shadow"],
                "boundary_crossed": [],
            })

        assert result["ok"] is True
        assert result["observe_only"] is True
        assert result["scorable_count"] == 2
        # live vs shadow cohorts SEPARATE
        cohorts = {c["cohort"]: c for c in result["cohorts"]}
        assert set(cohorts) == {"live", "shadow"}
        assert cohorts["live"]["is_paper"] is False
        assert cohorts["shadow"]["is_paper"] is True
        # both the frozen adapter (needs delta) and lognormal challenger (needs
        # spot+iv) score the captured live row
        assert cohorts["live"]["models"]["frozen_adapter"]["scored"] == 1
        assert cohorts["live"]["models"]["lognormal_challenger"]["scored"] == 1
        # OBSERVE-ONLY: the handler wrote NOTHING to any table
        assert client.writes == []

    def test_handler_fetch_error_marks_partial_not_raise(self):
        class _Boom:
            def table(self, name):
                raise RuntimeError("db down")
        from packages.quantum.jobs.handlers import model_review_event as handler
        with patch.object(handler, "get_admin_client", return_value=_Boom()):
            result = handler.run({"fingerprint": "fp", "scorable_record_ids": ["x"]})
        assert result["ok"] is False
        assert result["counts"]["errors"] == 1  # runner classifies 'partial'


# ── ingest-tail wiring (drive paper_learning_ingest.run end-to-end) ─────────
class TestIngestTailWiring:
    def test_ingest_tail_enqueues_review_on_scorable_close(self, stub_enqueue):
        from packages.quantum.jobs.handlers import paper_learning_ingest as pli
        client = _FakeClient(_scorable_tables("s-live-1"))

        with patch.object(pli, "get_admin_client", return_value=client), \
             patch.object(pli, "get_active_user_ids", return_value=[]), \
             patch("packages.quantum.risk.streak_breaker.evaluate_and_trip",
                   return_value={"tripped": False}):
            out = pli.run({"date": "2026-03-25", "lookback_days": 7})

        assert out["ok"] is True
        assert out["model_review"]["enqueued"] is True
        assert len(stub_enqueue.calls) == 1
        assert stub_enqueue.calls[0]["origin"]["origin"] == "event"


# ── watchdog non-expectation ────────────────────────────────────────────────
class TestWatchdogDoesNotExpectIt:
    def test_watchdog_does_not_expect_it(self):
        from packages.quantum.services.ops_health_service import EXPECTED_JOBS
        names = {j for j, _ in EXPECTED_JOBS}
        assert "model_review_event" not in names
