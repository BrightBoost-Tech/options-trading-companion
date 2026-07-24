"""Audit-B — Regime V4 observe seam: capture byte-identity, enqueue gating,
no-leak import boundary, and the migration contract.

Proves the parent-side + isolation contract (C2/C4/C6/C7):
  - ``compute_global_snapshot`` with ``capture_sink=None`` is BYTE-IDENTICAL to a
    call without the param; a provided sink is populated with the inputs V3
    already fetched (no extra provider call);
  - ``REGIME_V4_OBSERVE_ENABLED`` defaults OFF and fails SAFE to no-observation;
  - ``maybe_enqueue`` gates on flag → capture → scheduler-origin, and routes the
    child to the ``background`` queue with the idempotency key;
  - NO-LEAK: importing the live decision path (scanner / orchestrator /
    executor) does NOT pull the V4 SCORER module into the import graph;
  - the migration DDL is additive, service-role RLS, idempotent-unique, with the
    generated ``symbol_key`` the child upserts on.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

from packages.quantum.analytics import regime_v4_shadow_capture as cap
from packages.quantum.analytics.regime_engine_v3 import RegimeEngineV3

_BASKET = ["SPY", "QQQ", "IWM", "TLT", "HYG", "XLF", "XLK", "XLE"]
_MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "supabase" / "migrations"
    / "20260723160000_regime_v4_comparisons.sql"
)


class StubMarketData:
    """Deterministic in-memory market data — daily_bars + snapshot_many only
    (the surface compute_global_snapshot touches). No network."""

    def __init__(self):
        self.daily_calls = 0
        self.snap_calls = 0

    def daily_bars(self, sym, start=None, end=None):
        self.daily_calls += 1
        return [{"close": 100.0 + i * 0.1} for i in range(100)]

    def snapshot_many(self, syms):
        self.snap_calls += 1
        return {s: {"quote": {"bid": 1.0, "ask": 1.02, "mid": 1.01}} for s in syms}


class TestCaptureByteIdentity(unittest.TestCase):
    def _engine(self):
        return RegimeEngineV3(supabase_client=None, market_data=StubMarketData())

    def test_capture_sink_none_is_byte_identical(self):
        as_of = datetime(2026, 7, 23, 16, 0, tzinfo=timezone.utc)
        snap_off = self._engine().compute_global_snapshot(as_of)
        snap_on = self._engine().compute_global_snapshot(as_of, capture_sink={})
        self.assertEqual(snap_off.to_dict(), snap_on.to_dict())

    def test_capture_sink_populated_from_already_fetched(self):
        as_of = datetime(2026, 7, 23, 16, 0, tzinfo=timezone.utc)
        sink = {}
        self._engine().compute_global_snapshot(as_of, capture_sink=sink)
        self.assertEqual(sorted(sink["basket_closes"].keys()), sorted(_BASKET))
        self.assertEqual(len(sink["basket_closes"]["SPY"]), 100)
        self.assertIn("SPY", sink["basket_quotes"])

    def test_capture_makes_no_extra_provider_call(self):
        """Capture is PURE extraction — same number of provider reads with the
        sink on as off (8 daily_bars + 1 snapshot_many either way)."""
        as_of = datetime(2026, 7, 23, 16, 0, tzinfo=timezone.utc)
        md_off = StubMarketData()
        RegimeEngineV3(market_data=md_off).compute_global_snapshot(as_of)
        md_on = StubMarketData()
        RegimeEngineV3(market_data=md_on).compute_global_snapshot(as_of, capture_sink={})
        self.assertEqual(
            (md_off.daily_calls, md_off.snap_calls),
            (md_on.daily_calls, md_on.snap_calls),
        )


class TestFlagPolarity(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get(cap.FLAG_ENV)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop(cap.FLAG_ENV, None)
        else:
            os.environ[cap.FLAG_ENV] = self._saved

    def test_default_off(self):
        os.environ.pop(cap.FLAG_ENV, None)
        self.assertFalse(cap.is_observe_enabled())

    def test_empty_off(self):
        os.environ[cap.FLAG_ENV] = ""
        self.assertFalse(cap.is_observe_enabled())

    def test_truthy_on(self):
        for v in ("1", "true", "yes", "on", "TRUE"):
            os.environ[cap.FLAG_ENV] = v
            self.assertTrue(cap.is_observe_enabled(), v)

    def test_falsy_off(self):
        for v in ("0", "false", "no", "off"):
            os.environ[cap.FLAG_ENV] = v
            self.assertFalse(cap.is_observe_enabled(), v)


class TestBuildEnvelope(unittest.TestCase):
    def _snap(self):
        from packages.quantum.analytics.regime_engine_v3 import GlobalRegimeSnapshot
        from packages.quantum.common_enums import RegimeState
        return GlobalRegimeSnapshot(
            as_of_ts="2026-07-23T16:00:00+00:00", state=RegimeState.NORMAL,
            risk_score=50.0, risk_scaler=1.0, trend_score=0.0, vol_score=0.0,
            corr_score=0.0, breadth_score=0.0, liquidity_score=0.0,
        )

    def test_none_when_no_basket(self):
        env = cap.build_capture_envelope(self._snap(), {}, {"per_symbol": {}}, as_of="x")
        self.assertIsNone(env)

    def test_assembles_from_sinks(self):
        capture_sink = {"basket_closes": {"SPY": [1.0, 2.0]}, "basket_quotes": {"SPY": {}}}
        symbol_sink = {"per_symbol": {"AAPL": {"symbol": "AAPL"}}}
        env = cap.build_capture_envelope(self._snap(), capture_sink, symbol_sink, as_of="x")
        self.assertEqual(env["v3_global"]["state"], "normal")
        self.assertEqual(env["basket_closes"], {"SPY": [1.0, 2.0]})
        self.assertEqual(env["per_symbol"], [{"symbol": "AAPL"}])


class TestEnqueueGating(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get(cap.FLAG_ENV)
        os.environ[cap.FLAG_ENV] = "1"
        self.calls = []

        def _fake_enqueue(**kwargs):
            self.calls.append(kwargs)
            return {"status": "queued", "job_run_id": "jr1", "rq_job_id": "rq1"}

        self._enq = _fake_enqueue
        self._origin = lambda event, **k: {"origin": "event", "event": event}
        self._capture = {"basket_closes": {"SPY": [1.0]}, "per_symbol": []}

    def tearDown(self):
        if self._saved is None:
            os.environ.pop(cap.FLAG_ENV, None)
        else:
            os.environ[cap.FLAG_ENV] = self._saved

    def _call(self, **over):
        kw = dict(
            capture=self._capture, user_id="u1", source_job_run_id="job1",
            source_decision_id="dec1", source_code_sha="shaZ", as_of="t",
            parent_origin="scheduler", enqueue_fn=self._enq, origin_builder=self._origin,
            # Inject the queue name so the hermetic test never imports rq_enqueue
            # (its module load touches the RQ fork context — a local-only failure).
            # Value must equal rq_enqueue.BACKGROUND_QUEUE ('background').
            background_queue="background",
        )
        kw.update(over)
        return cap.maybe_enqueue_regime_v4_shadow_compare(None, **kw)

    def test_flag_off_no_enqueue(self):
        os.environ[cap.FLAG_ENV] = "0"
        r = self._call()
        self.assertEqual(r["status"], "observe_disabled")
        self.assertFalse(r["enqueued"])
        self.assertEqual(self.calls, [])

    def test_no_capture_no_enqueue(self):
        r = self._call(capture=None)
        self.assertEqual(r["status"], "no_capture")
        self.assertEqual(self.calls, [])

    def test_non_scheduler_no_enqueue(self):
        r = self._call(parent_origin="manual")
        self.assertEqual(r["status"], "non_natural_parent")
        self.assertEqual(self.calls, [])

    def test_scheduler_enqueues_to_background_with_idem_key(self):
        r = self._call()
        self.assertTrue(r["enqueued"])
        self.assertEqual(len(self.calls), 1)
        c = self.calls[0]
        self.assertEqual(c["queue_name"], "background")  # == rq_enqueue.BACKGROUND_QUEUE
        self.assertEqual(c["job_name"], "regime_v4_shadow_compare")
        self.assertEqual(c["idempotency_key"], "regime_v4_shadow_compare:dec1:shaZ")
        self.assertEqual(c["payload"]["cycle_id"], "dec1")
        self.assertIn("capture", c["payload"])

    def test_missing_identity_no_enqueue(self):
        r = self._call(source_decision_id=None, source_job_run_id=None)
        self.assertEqual(r["status"], "source_identity_missing")
        self.assertEqual(self.calls, [])


class TestNoLeakImportBoundary(unittest.TestCase):
    """C6(f): the live decision path must not import the V4 SCORER module (which
    references RegimeEngineV4). Run in a FRESH interpreter so a sibling test that
    already imported the scorer cannot mask a real leak."""

    def _assert_not_leaked(self, live_module: str):
        code = (
            "import importlib, sys\n"
            f"importlib.import_module('{live_module}')\n"
            "leaked = 'packages.quantum.analytics.regime_v4_shadow_compare' in sys.modules\n"
            "print('LEAK' if leaked else 'CLEAN')\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parents[3]),
        )
        self.assertIn(
            "CLEAN", proc.stdout,
            f"{live_module} pulled the V4 scorer into the import graph:\n"
            f"STDOUT={proc.stdout}\nSTDERR={proc.stderr[-1500:]}",
        )

    def test_scanner_does_not_import_scorer(self):
        self._assert_not_leaked("packages.quantum.options_scanner")

    def test_orchestrator_does_not_import_scorer(self):
        self._assert_not_leaked("packages.quantum.services.workflow_orchestrator")

    def test_executor_does_not_import_scorer(self):
        self._assert_not_leaked("packages.quantum.services.paper_autopilot_service")


class TestMigrationContract(unittest.TestCase):
    def _sql(self):
        return _MIGRATION.read_text(encoding="utf-8")

    def _sql_no_comments(self):
        # Strip BOTH full-line and trailing inline `--` comments so a doc mention
        # of a table name (e.g. "join to trade_suggestions") is not mistaken for
        # DDL against it.
        out = []
        for ln in self._sql().splitlines():
            code = ln.split("--", 1)[0]
            if code.strip():
                out.append(code)
        return "\n".join(out)

    def test_file_exists(self):
        self.assertTrue(_MIGRATION.is_file(), _MIGRATION)

    def test_creates_table(self):
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS regime_v4_comparisons", self._sql()
        )

    def test_generated_symbol_key_and_unique_index(self):
        sql = self._sql()
        self.assertIsNotNone(
            re.search(
                r"symbol_key\s+text GENERATED ALWAYS AS "
                r"\(COALESCE\(symbol, '__global__'\)\) STORED",
                sql,
            ),
            "generated symbol_key column missing / drifted",
        )
        m = re.search(
            r"CREATE UNIQUE INDEX IF NOT EXISTS idx_rv4_identity\s+"
            r"ON regime_v4_comparisons\s*\(cycle_id, code_sha, scope, symbol_key\)",
            sql,
        )
        self.assertIsNotNone(m, "identity unique index missing / drifted")

    def test_scope_check(self):
        self.assertIn("CHECK (scope IN ('global', 'symbol'))", self._sql())

    def test_service_role_rls(self):
        sql = self._sql()
        self.assertIn(
            "ALTER TABLE regime_v4_comparisons ENABLE ROW LEVEL SECURITY", sql
        )
        self.assertIn("auth.role() = 'service_role'", sql)

    def test_additive_only(self):
        body = self._sql_no_comments()
        for tbl in re.findall(
            r"(?:CREATE TABLE IF NOT EXISTS|ALTER TABLE)\s+(\w+)", body
        ):
            self.assertEqual(tbl, "regime_v4_comparisons")
        for name in ("trade_suggestions", "decision_runs", "job_runs",
                     "paper_positions", "calibration_adjustments"):
            self.assertNotIn(name, body, f"migration must not touch {name}")

    def test_no_foreign_keys(self):
        self.assertNotIn("REFERENCES", self._sql_no_comments())


if __name__ == "__main__":
    unittest.main()
