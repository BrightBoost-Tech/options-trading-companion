"""Tests for the entries-only break-glass halt (ops_control.entries_paused).

The only live no-deploy halt before this was ``ops_control.paused``, read in
``enqueue_job_run`` — it gates EVERY job with no exemption, so flipping it ALSO
halts the intraday risk monitor + exit/close jobs that ARE the loss-protection.

This adds an entries-ONLY brake that blocks NEW position entry at the autopilot
entry seam (``execute_top_suggestions`` → ``_execute_per_cohort`` →
``_stage_order_internal``) while LEAVING the monitor + exit enqueue path
untouched. The DB row is the operator interface (flippable with NO deploy).

Three guarantees are pinned here:
  1. entries_paused=True → the entry path returns 'entries_paused' and stages
     NOTHING (``_execute_per_cohort`` is never reached).
  2. entries_paused=True does NOT gate the monitor/exit ENQUEUE path — the
     load-bearing fail-safe: loss-protection keeps running while entries halt.
  3. Defensive read: column/row absent OR read raises → NOT halted (entries
     allowed), no crash, exactly one degraded-read log.
"""
import inspect
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# Stub alpaca-py per the repo convention so a transitive equity_state import
# (lazy in the autopilot entry path) never dirties collection on this machine.
_alpaca_pkg = types.ModuleType("alpaca")
_alpaca_trading = types.ModuleType("alpaca.trading")
_alpaca_trading_requests = types.ModuleType("alpaca.trading.requests")


class _StubPortfolioHistoryRequest:
    def __init__(self, period=None, timeframe=None, **_):
        self.period = period
        self.timeframe = timeframe


_alpaca_trading_requests.GetPortfolioHistoryRequest = _StubPortfolioHistoryRequest
sys.modules.setdefault("alpaca", _alpaca_pkg)
sys.modules.setdefault("alpaca.trading", _alpaca_trading)
sys.modules.setdefault("alpaca.trading.requests", _alpaca_trading_requests)

# ``public_tasks`` (the enqueue gate under test) imports ``rq`` transitively,
# and ``rq`` fails to import on Windows (multiprocessing 'fork' context). Only
# when the REAL module can't be imported do we install a thin stub, so CI
# (where rq imports cleanly) is never polluted and other suites keep the real
# module. ``enqueue_idempotent`` is patched per-test regardless.
try:  # pragma: no cover - import-path branch
    import packages.quantum.jobs.rq_enqueue  # noqa: F401
except Exception:  # pragma: no cover - Windows fork-context path
    _rq_stub = types.ModuleType("packages.quantum.jobs.rq_enqueue")
    _rq_stub.enqueue_idempotent = lambda *a, **k: {"job_id": "stub"}
    _rq_stub.BACKGROUND_QUEUE = "background"
    sys.modules["packages.quantum.jobs.rq_enqueue"] = _rq_stub

import packages.quantum.ops_endpoints as ops
from packages.quantum.services.paper_autopilot_service import PaperAutopilotService


class TestEntriesOnlyHaltEntryPathBlocks(unittest.TestCase):
    """Guarantee 1: the entry seam blocks while monitor/exits are untouched."""

    def test_entries_paused_blocks_entry_and_stages_nothing(self):
        """entries_paused=True → 'entries_paused', executed_count 0, NO staging.

        Asserts ``_execute_per_cohort`` (the delegate that reaches
        ``_stage_order_internal``) is never called — i.e. no order is staged.
        """
        service = PaperAutopilotService(MagicMock())
        service._execute_per_cohort = MagicMock(name="_execute_per_cohort")

        with patch.object(ops, "is_trading_paused", return_value=(False, None)), \
             patch.object(ops, "are_entries_paused",
                          return_value=(True, "operator break-glass")):
            result = service.execute_top_suggestions("user-1")

        self.assertEqual(result["status"], "entries_paused")
        self.assertEqual(result["executed_count"], 0)
        self.assertEqual(result["reason"], "operator break-glass")
        service._execute_per_cohort.assert_not_called()

    def test_global_pause_still_wins_entries_gate_does_not_bypass_it(self):
        """The entries gate must NEVER bypass the global ``paused`` gate."""
        service = PaperAutopilotService(MagicMock())
        service._execute_per_cohort = MagicMock(name="_execute_per_cohort")

        with patch.object(ops, "is_trading_paused",
                          return_value=(True, "global halt")), \
             patch.object(ops, "are_entries_paused", return_value=(False, None)):
            result = service.execute_top_suggestions("user-1")

        self.assertEqual(result["status"], "paused")
        self.assertEqual(result["reason"], "global halt")
        service._execute_per_cohort.assert_not_called()


class TestEntriesOnlyHaltMonitorExitUngated(unittest.TestCase):
    """Guarantee 2 (load-bearing fail-safe): the monitor/exit enqueue path is
    NOT routed through the entries-only gate — loss-protection keeps running."""

    def test_monitor_and_exit_enqueue_proceeds_while_entries_paused(self):
        import packages.quantum.public_tasks as pt

        fake_run = {"id": "jr-123", "status": "queued"}
        fake_store = MagicMock()
        fake_store.create_or_get_cancelled = MagicMock(name="create_or_get_cancelled")

        # are_entries_paused returns HALTED — and must be PROVABLY never
        # consulted by the enqueue path (it lives only at the entry seam).
        entries_mock = MagicMock(return_value=(True, "operator break-glass"))

        for job_name in ("intraday_risk_monitor", "paper_exit_evaluator"):
            fake_store.create_or_get.return_value = dict(fake_run)
            with patch.object(pt, "JobRunStore", return_value=fake_store), \
                 patch.object(pt, "enqueue_idempotent",
                              return_value={"job_id": f"rq-{job_name}"}) as enq, \
                 patch.object(pt, "_job_requires_live_privileges",
                              return_value=False), \
                 patch("packages.quantum.ops_endpoints.is_trading_paused",
                       return_value=(False, None)), \
                 patch("packages.quantum.ops_endpoints.are_entries_paused",
                       entries_mock):
                result = pt.enqueue_job_run(job_name, f"key-{job_name}",
                                            {"user_id": "u1"})

            # The monitor/exit job ENQUEUED (proceeded) — not cancelled.
            self.assertEqual(result["status"], "queued")
            self.assertEqual(result["rq_job_id"], f"rq-{job_name}")
            self.assertIsNone(result.get("cancelled_reason"))
            enq.assert_called_once()
            fake_store.create_or_get_cancelled.assert_not_called()

        # The entries brake is structurally outside the enqueue path.
        entries_mock.assert_not_called()

    def test_enqueue_source_has_no_entries_gate(self):
        """Structural proof: the enqueue gate references the global pause ONLY,
        never the entries-only flag — so monitor/exit jobs can't be entries-gated."""
        import packages.quantum.public_tasks as pt
        src = inspect.getsource(pt.enqueue_job_run)
        self.assertIn("is_trading_paused", src)       # global pause IS gated here
        self.assertNotIn("are_entries_paused", src)   # entries brake is NOT
        self.assertNotIn("entries_paused", src)


class TestEntriesOnlyHaltDefensiveRead(unittest.TestCase):
    """Guarantee 3: the runtime read is defensive and fails OPEN."""

    def setUp(self):
        ops._entries_paused_degraded_logged = False

    def tearDown(self):
        ops._entries_paused_degraded_logged = False

    def test_column_absent_not_halted_and_logs_once(self):
        """Column absent (migration not applied) → NOT halted, exactly one log."""
        legacy_row = {"key": "global", "mode": "paper",
                      "paused": False, "pause_reason": None}
        with patch.object(ops, "get_global_ops_control", return_value=legacy_row):
            with self.assertLogs(ops.logger, level="INFO") as cm:
                halted1, reason1 = ops.are_entries_paused()
                halted2, reason2 = ops.are_entries_paused()  # 2nd call: no new log

        self.assertFalse(halted1)
        self.assertIsNone(reason1)
        self.assertFalse(halted2)
        absent_logs = [m for m in cm.output if "entries_paused absent" in m]
        self.assertEqual(len(absent_logs), 1)  # logged once across both calls

    def test_read_raises_not_halted_and_logs_once(self):
        """Read raises → NOT halted (fail-open), no crash, exactly one log."""
        with patch.object(ops, "get_global_ops_control",
                          side_effect=RuntimeError("db down")):
            with self.assertLogs(ops.logger, level="WARNING") as cm:
                halted, reason = ops.are_entries_paused()

        self.assertFalse(halted)
        self.assertIsNone(reason)
        warn_logs = [m for m in cm.output if "ops_control read failed" in m]
        self.assertEqual(len(warn_logs), 1)

    def test_column_present_true_halts_with_reason(self):
        """Positive control: column present + True → halted with reason."""
        row = {"key": "global", "paused": False,
               "entries_paused": True, "entries_pause_reason": "manual halt"}
        with patch.object(ops, "get_global_ops_control", return_value=row):
            halted, reason = ops.are_entries_paused()
        self.assertTrue(halted)
        self.assertEqual(reason, "manual halt")

    def test_column_present_false_allows_entries(self):
        """Positive control: column present + False → entries allowed."""
        row = {"key": "global", "paused": False,
               "entries_paused": False, "entries_pause_reason": None}
        with patch.object(ops, "get_global_ops_control", return_value=row):
            halted, reason = ops.are_entries_paused()
        self.assertFalse(halted)
        self.assertIsNone(reason)


if __name__ == "__main__":
    unittest.main()
