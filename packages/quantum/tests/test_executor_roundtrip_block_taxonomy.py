"""Executor typed terminal handling for EXPECTED ev_below_roundtrip_cost blocks.

The #1101 round-trip cost gate raises ``EntryRoundtripCostExceedsEV``
pre-broker-submit when a candidate's gross EV does not survive the executable
round-trip cross vs the $15 floor. Before this lane, ``_execute_per_cohort`` had
NO dedicated handler: the exception fell into the generic ``except Exception``,
which appended to ``all_errors`` AND fired a spurious
``paper_autopilot_cohort_per_suggestion_failed`` WARNING — a routine economic
block mislabeled as an execution failure (07-23 runs ``acddb64e`` / ``681d6270``
showed errors=1 for an EXPECTED block, and the blocked aggressive SPY suggestion
stayed retryable ``status='pending'``).

These tests drive the REAL ``_execute_per_cohort`` route (model:
test_candidate_lifecycle_milestones / test_e7_viability_rewire_executor_route),
injecting the gate exception at the deepest callee the executor calls
(``_stage_order_internal``, where ``_apply_entry_roundtrip_gate`` raises at
paper_endpoints:1776) and asserting the top-level result:

  * expected block  -> blocked_count=1, error_count=0, status='ok', NO
                       cohort-failure warning, and the suggestion transitioned
                       to the canonical terminal NOT_EXECUTABLE state;
  * terminal-persist failure (DB write throws) -> a REAL error: error_count=1,
                       status='partial' (never silently green);
  * mixed run       -> executed=1, blocked=1, errors=0, status='ok';
  * unexpected exc  -> still error + partial (generic handler unchanged);
  * no broker call on the blocked path (no order processed for the block);
  * the $15-floor gate arithmetic is byte-identical (untouched by this lane).
"""

import os
import sys
import types
import unittest
import uuid
from datetime import datetime, timezone
from unittest import mock

# Stub alpaca-py so transitive imports resolve in the test venv.
sys.modules.setdefault("alpaca", types.ModuleType("alpaca"))
sys.modules.setdefault("alpaca.trading", types.ModuleType("alpaca.trading"))
sys.modules.setdefault(
    "alpaca.trading.requests", types.ModuleType("alpaca.trading.requests")
)

from packages.quantum.tests.test_prerejection_fork_e19 import FakeSupabase  # noqa: E402

UID = "user-1"
_TODAY = datetime.now(timezone.utc).date().isoformat()

AGG_SID = "1e8a0f9c-0000-4000-8000-0000000000a9"
NEU_SID = "1e8a0f9c-0000-4000-8000-0000000000b7"

FUNNEL_FLAG = "FUNNEL_STATUS_TRUTHFUL_ENABLED"
GATE_FLAG = "ENTRY_ROUNDTRIP_COST_GATE_ENABLED"


def _sugg(sid, cohort):
    return {
        "id": sid, "user_id": UID, "ticker": "SPY", "symbol": "SPY",
        "cohort_name": cohort, "status": "pending", "cycle_date": _TODAY,
        "strategy": "IRON_CONDOR",
        "ev": 21.935, "ev_raw": 43.87, "risk_adjusted_ev": 0.05,
        "max_loss_total": 346, "capital_required": 500,
        "legs_fingerprint": f"fp-{cohort}",
    }


def _roundtrip_exc():
    # str() == "ev_below_roundtrip_cost: gross_ev=21.93 round_trip=9.00 net=12.94"
    from packages.quantum.paper_endpoints import EntryRoundtripCostExceedsEV
    return EntryRoundtripCostExceedsEV(21.935, 9.00, 12.935)


def _row(client, sid):
    for r in client.tables.get("trade_suggestions", []):
        if r.get("id") == sid:
            return r
    return None


def _warned_cohort_failure(alert_mock):
    return any(
        c.kwargs.get("alert_type") == "paper_autopilot_cohort_per_suggestion_failed"
        for c in alert_mock.call_args_list
    )


def _run_executor(client, *, configs, portfolios, stage_side_effect,
                  exec_mode, processed=1):
    """Drive the REAL PaperAutopilotService._execute_per_cohort.

    Only the deepest execution callees are mocked (_stage_order_internal is the
    seam that raises the gate exception; _process_orders_for_user is the
    broker/internal fill router). The block taxonomy, terminal transition, and
    result classification are all real production code. Returns
    (result, process_mock, alert_mock).
    """
    from packages.quantum.services.paper_autopilot_service import (
        PaperAutopilotService,
    )

    svc = PaperAutopilotService.__new__(PaperAutopilotService)
    svc.client = client
    svc.get_open_positions = lambda uid: []
    svc.get_already_executed_suggestion_ids_today = lambda uid: set()
    svc._stamp_blocked_reason = lambda *a, **k: None
    svc._estimate_equity = lambda *a, **k: 2000.0

    process_mock = mock.MagicMock(return_value={"processed": processed})
    alert_mock = mock.MagicMock()

    with mock.patch.dict(os.environ, {FUNNEL_FLAG: "1"}), \
         mock.patch("packages.quantum.services.reentry_cooldown.is_enabled",
                    return_value=False), \
         mock.patch("packages.quantum.risk.utilization_gate.is_enabled",
                    return_value=False), \
         mock.patch("packages.quantum.policy_lab.config.load_cohort_configs",
                    return_value=configs), \
         mock.patch("packages.quantum.policy_lab.fork._get_cohort_portfolios",
                    return_value=portfolios), \
         mock.patch("packages.quantum.paper_endpoints.get_analytics_service",
                    return_value=mock.MagicMock()), \
         mock.patch("packages.quantum.paper_endpoints._suggestion_to_ticket",
                    side_effect=lambda s: {"sid": s["id"]}), \
         mock.patch("packages.quantum.paper_endpoints._process_orders_for_user",
                    process_mock), \
         mock.patch("packages.quantum.brokers.execution_router.get_execution_mode",
                    return_value=exec_mode), \
         mock.patch("packages.quantum.paper_endpoints._stage_order_internal",
                    side_effect=stage_side_effect), \
         mock.patch("packages.quantum.services.paper_autopilot_service.alert",
                    alert_mock), \
         mock.patch(
             "packages.quantum.services.paper_autopilot_service._get_admin_supabase",
             return_value=mock.MagicMock()):
        result = svc._execute_per_cohort(UID)
    return result, process_mock, alert_mock


def _one_agg_client():
    client = FakeSupabase()
    client.tables["trade_suggestions"] = [_sugg(AGG_SID, "aggressive")]
    return client


_AGG_ONLY_CONFIGS = {"aggressive": types.SimpleNamespace(max_suggestions_per_day=5)}
_AGG_ONLY_PORTFOLIOS = {"aggressive": "port-agg"}


class TestExpectedBlock(unittest.TestCase):
    def _stage(self, *a, **k):
        # the gate raises out of _stage_order_internal for the aggressive sid
        raise _roundtrip_exc()

    def test_block_is_not_an_error_and_transitions_to_terminal(self):
        from packages.quantum.brokers.execution_router import ExecutionMode
        client = _one_agg_client()
        result, _process, alert_mock = _run_executor(
            client, configs=_AGG_ONLY_CONFIGS, portfolios=_AGG_ONLY_PORTFOLIOS,
            stage_side_effect=self._stage, exec_mode=ExecutionMode.INTERNAL_PAPER,
        )
        # taxonomy: block, not error
        self.assertEqual(result["blocked_count"], 1)
        self.assertEqual(result["blocked_by_reason"],
                         {"ev_below_roundtrip_cost": 1})
        self.assertEqual(result["error_count"], 0)
        self.assertEqual(result["executed_count"], 0)
        self.assertEqual(result["status"], "ok")
        self.assertIsNone(result["errors"])
        # NO cohort-failure warning for a routine economic block
        self.assertFalse(_warned_cohort_failure(alert_mock))
        # terminal honesty: pending -> canonical NOT_EXECUTABLE + reason/detail
        row = _row(client, AGG_SID)
        self.assertEqual(row["status"], "NOT_EXECUTABLE")
        self.assertEqual(row["blocked_reason"], "ev_below_roundtrip_cost")
        self.assertIn("gross_ev", row["blocked_detail"])
        self.assertIn("net", row["blocked_detail"])

    def test_no_broker_call_on_blocked_path(self):
        from packages.quantum.brokers.execution_router import ExecutionMode
        client = _one_agg_client()
        result, process_mock, _alert = _run_executor(
            client, configs=_AGG_ONLY_CONFIGS, portfolios=_AGG_ONLY_PORTFOLIOS,
            stage_side_effect=self._stage, exec_mode=ExecutionMode.INTERNAL_PAPER,
        )
        self.assertEqual(result["executed_count"], 0)
        # the per-ORDER processing call (target_order_id=...) is what submits a
        # staged order; a blocked candidate must never reach it. The only
        # allowed _process_orders_for_user call is the end-of-run sweep, which
        # carries NO target_order_id.
        per_order_calls = [
            c for c in process_mock.call_args_list
            if "target_order_id" in c.kwargs
        ]
        self.assertEqual(per_order_calls, [])


class TestTerminalPersistFailureIsRealError(unittest.TestCase):
    def _stage(self, *a, **k):
        raise _roundtrip_exc()

    def test_persist_failure_flips_job_partial(self):
        from packages.quantum.brokers.execution_router import ExecutionMode
        client = _one_agg_client()
        # deepest callee of the terminal transition: the durable status write
        client.raise_when("trade_suggestions", "update")
        result, _process, alert_mock = _run_executor(
            client, configs=_AGG_ONLY_CONFIGS, portfolios=_AGG_ONLY_PORTFOLIOS,
            stage_side_effect=self._stage, exec_mode=ExecutionMode.INTERNAL_PAPER,
        )
        # a terminal-persist failure is a REAL error — never silently green
        self.assertEqual(result["error_count"], 1)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["errors"][0]["suggestion_id"], AGG_SID)
        self.assertIn("terminal_status_persist_failed",
                      result["errors"][0]["error"])
        # the block was still counted (it did happen); the failure is on top
        self.assertEqual(result["blocked_count"], 1)
        # a genuine DB write failure DOES surface the cohort-failure alert
        self.assertTrue(_warned_cohort_failure(alert_mock))
        # the failed write left the row un-transitioned (still pending)
        self.assertEqual(_row(client, AGG_SID)["status"], "pending")


class TestMixedRun(unittest.TestCase):
    def _stage(self, *a, **k):
        if k.get("suggestion_id_override") == AGG_SID:
            raise _roundtrip_exc()
        return "ord-neu"

    def test_executed_one_blocked_one_errors_zero(self):
        from packages.quantum.brokers.execution_router import ExecutionMode
        client = FakeSupabase()
        client.tables["trade_suggestions"] = [
            _sugg(AGG_SID, "aggressive"), _sugg(NEU_SID, "neutral"),
        ]
        configs = {
            "aggressive": types.SimpleNamespace(max_suggestions_per_day=5),
            "neutral": types.SimpleNamespace(max_suggestions_per_day=5),
        }
        portfolios = {"aggressive": "port-agg", "neutral": "port-neu"}
        result, process_mock, alert_mock = _run_executor(
            client, configs=configs, portfolios=portfolios,
            stage_side_effect=self._stage, exec_mode=ExecutionMode.INTERNAL_PAPER,
        )
        self.assertEqual(result["executed_count"], 1)
        self.assertEqual(result["blocked_count"], 1)
        self.assertEqual(result["error_count"], 0)
        self.assertEqual(result["status"], "ok")
        self.assertFalse(_warned_cohort_failure(alert_mock))
        # aggressive terminally blocked; neutral executed (its order processed)
        self.assertEqual(_row(client, AGG_SID)["status"], "NOT_EXECUTABLE")
        self.assertEqual(result["executed"][0]["suggestion_id"], NEU_SID)
        per_order_calls = [
            c for c in process_mock.call_args_list
            if c.kwargs.get("target_order_id") == "ord-neu"
        ]
        self.assertEqual(len(per_order_calls), 1)


class TestUnexpectedExceptionStillErrors(unittest.TestCase):
    def _stage(self, *a, **k):
        raise RuntimeError("boom — genuine staging failure")

    def test_generic_exception_is_still_error_and_partial(self):
        from packages.quantum.brokers.execution_router import ExecutionMode
        client = _one_agg_client()
        result, _process, alert_mock = _run_executor(
            client, configs=_AGG_ONLY_CONFIGS, portfolios=_AGG_ONLY_PORTFOLIOS,
            stage_side_effect=self._stage, exec_mode=ExecutionMode.INTERNAL_PAPER,
        )
        self.assertEqual(result["error_count"], 1)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["blocked_count"], 0)
        self.assertEqual(result["blocked_by_reason"], {})
        # a genuine failure still fires the cohort-failure alert
        self.assertTrue(_warned_cohort_failure(alert_mock))


class TestGateFloorArithmeticByteIdentical(unittest.TestCase):
    """The executor lane changes ZERO gate math. This characterizes the REAL
    _apply_entry_roundtrip_gate: the SOFI below-floor fixture rejects with the
    same numbers, and a tight-spread above-floor trade is allowed — the $15
    floor decision is unchanged."""

    SOFI_LONG = "O:SOFI260807C00017000"
    SOFI_SHORT = "O:SOFI260807C00020500"
    SOFI_QUOTES = {
        SOFI_LONG: {"bid": 1.93, "ask": 2.16},
        SOFI_SHORT: {"bid": 0.67, "ask": 0.71},
    }

    def setUp(self):
        self._saved = os.environ.get(GATE_FLAG)
        os.environ.pop(GATE_FLAG, None)  # default ON

    def tearDown(self):
        os.environ.pop(GATE_FLAG, None)
        if self._saved is not None:
            os.environ[GATE_FLAG] = self._saved

    def _ticket(self, *, expected_value, legs, quantity):
        leg_objs = [
            types.SimpleNamespace(symbol=occ, action=act, quantity=q, strike=None)
            for (occ, act, q) in legs
        ]
        return types.SimpleNamespace(
            expected_value=expected_value, legs=leg_objs, quantity=quantity,
        )

    def test_below_floor_rejects_with_same_numbers(self):
        from packages.quantum.paper_endpoints import (
            _apply_entry_roundtrip_gate, EntryRoundtripCostExceedsEV,
        )
        ticket = self._ticket(
            expected_value=30.628,
            legs=[(self.SOFI_LONG, "buy", 5), (self.SOFI_SHORT, "sell", 5)],
            quantity=5,
        )
        with self.assertRaises(EntryRoundtripCostExceedsEV) as ctx:
            _apply_entry_roundtrip_gate(
                FakeSupabase(), ticket, position_id=None,
                entry_leg_quotes=self.SOFI_QUOTES, suggestion_id="sofi-sid",
            )
        exc = ctx.exception
        self.assertAlmostEqual(exc.gross_ev, 30.628, places=4)
        self.assertAlmostEqual(exc.round_trip, 135.0, places=4)
        self.assertLess(exc.net, 15.0)

    def test_tight_spread_above_floor_allows(self):
        from packages.quantum.paper_endpoints import _apply_entry_roundtrip_gate
        long_occ = "O:XYZ260807C00050000"   # cross 0.02
        short_occ = "O:XYZ260807C00055000"  # cross 0.01
        quotes = {
            long_occ: {"bid": 2.00, "ask": 2.02},
            short_occ: {"bid": 1.00, "ask": 1.01},
        }
        ticket = self._ticket(
            expected_value=25.0,
            legs=[(long_occ, "buy", 1), (short_occ, "sell", 1)],
            quantity=1,
        )
        # round-trip = (0.02 + 0.01) × 1 × 100 = $3 -> net = $22 ≥ $15 -> allow
        _apply_entry_roundtrip_gate(  # must NOT raise
            FakeSupabase(), ticket, position_id=None,
            entry_leg_quotes=quotes, suggestion_id="xyz-sid",
        )


if __name__ == "__main__":
    unittest.main()
