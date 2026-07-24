"""Tests for intraday_risk_monitor acting on target_profit (15-min profit capture).

Profit-side mirror of the existing stop_loss handling. Behind
INTRADAY_TARGET_PROFIT_ENABLED (default OFF). Reuses the shared per-cohort
_check_target_profit (via build_exit_conditions) + the validated _close_position
path. These verify: flag gating, the qty-scaled per-cohort decision, the
regression against the old double-count, correct close_reason attribution
(target_profit_hit, NOT envelope_force_close), stop_loss unchanged, and
double-exit coordination is inherited.
"""

import sys
import types
import unittest
from unittest.mock import patch

# Stub alpaca-py so imports resolve in the test venv (mirrors test_force_close_path).
from packages.quantum.tests._alpaca_stub import ensure_alpaca as _ensure_alpaca

_ensure_alpaca()

from packages.quantum.jobs.handlers import intraday_risk_monitor as irm  # noqa: E402
from packages.quantum.services.paper_exit_evaluator import (  # noqa: E402
    _map_close_reason,
    build_exit_conditions,
)
from packages.quantum.policy_lab.config import PolicyConfig  # noqa: E402


def _f_position(unrealized_pl, quantity=5.0, avg_entry=0.96):
    """F-shape debit call spread (full-count legs=5), far DTE so dte/expiry
    don't fire. max_credit (per-spread) 0.96 → entry_cost = 0.96×5×100 = $480."""
    return {
        "id": "pos-f", "user_id": "u1", "symbol": "F", "quantity": quantity,
        "avg_entry_price": avg_entry, "max_credit": avg_entry,
        "current_mark": 1.02, "unrealized_pl": unrealized_pl,
        "strategy_key": "F_long_call_debit_spread",
        "cohort_id": "cohort-1",
        # 06-12 stale-mark guard: declare the fresh-mark provenance the real
        # _refresh_marks pass sets — the guard (correctly) refuses to fire
        # mark-derived exits on an unprovenanced value.
        "_mark_fresh": True,
        "nearest_expiry": "2099-06-26",  # far → dte/expiration never fire
        "legs": [
            {"type": "call", "action": "buy", "strike": 15.5, "symbol": "O:F260626C00015500", "quantity": 5},
            {"type": "call", "action": "sell", "strike": 17.5, "symbol": "O:F260626C00017500", "quantity": 5},
        ],
    }


def _monitor():
    m = irm.IntradayRiskMonitor.__new__(irm.IntradayRiskMonitor)
    m.supabase = object()  # not used when cohort load + _resolve are patched
    return m


class TestCloseReasonAttribution(unittest.TestCase):
    """The reason WHY target_profit needs the override path."""

    def test_target_profit_maps_to_target_profit_hit(self):
        self.assertEqual(_map_close_reason("target_profit"), "target_profit_hit")

    def test_risk_envelope_prefix_maps_to_envelope_force_close(self):
        # This is why routing target_profit through the default prefix is wrong.
        self.assertEqual(
            _map_close_reason("risk_envelope:intraday_target_profit"),
            "envelope_force_close",
        )


class TestPerCohortDecision(unittest.TestCase):
    """The shared per-cohort _check_target_profit (via build_exit_conditions)."""

    def test_fires_at_target_holds_below(self):
        conds = build_exit_conditions(target_profit_pct=0.35, stop_loss_pct=2.0, min_dte_to_exit=7)
        check = conds["target_profit"]["check"]
        # entry_cost 480; 35% threshold = $168.
        self.assertTrue(check(_f_position(170.0)))    # +$170 ≥ 168 → fire
        self.assertFalse(check(_f_position(30.0)))     # +$30 → hold

    def test_regression_unified_mark_30_does_not_fire(self):
        # With the post-#3 unified mark (+$30), target_profit does NOT fire.
        # The old ×qty double-count (~+$2,070) would have falsely fired here.
        conds = build_exit_conditions(target_profit_pct=0.35, stop_loss_pct=2.0, min_dte_to_exit=7)
        self.assertFalse(conds["target_profit"]["check"](_f_position(30.0)))
        self.assertTrue(conds["target_profit"]["check"](_f_position(2070.0)))  # the old fake value


class TestCollectIntradayExitTriggers(unittest.TestCase):
    def _run(self, position, flag_on, cohort_tp_pct=0.35):
        # stop_loss_pct pinned to the global default (0.50) so this file's
        # stop assertions keep their original arithmetic now that the
        # monitor evaluates stops COHORT-aware (INTRADAY_COHORT_STOP_ENABLED,
        # audit Area 7). Cohort-stop behavior itself is pinned in
        # test_intraday_cohort_stops.py.
        cfg = PolicyConfig(target_profit_pct=cohort_tp_pct, stop_loss_pct=0.50)
        with patch.object(irm, "_INTRADAY_TARGET_PROFIT_ENABLED", flag_on), patch(
            "packages.quantum.policy_lab.config.load_cohort_configs",
            return_value={"aggressive": cfg},
        ), patch(
            "packages.quantum.services.paper_exit_evaluator.PaperExitEvaluator._resolve_position_cohort",
            return_value="aggressive",
        ):
            return _monitor()._collect_intraday_exit_triggers([position], "u1")

    def test_flag_off_no_target_profit(self):
        # +$300 is over target, but flag OFF → no target_profit trigger.
        out = self._run(_f_position(300.0), flag_on=False)
        self.assertEqual(out, [])

    def test_flag_on_fires_target_profit(self):
        out = self._run(_f_position(300.0), flag_on=True)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][1], "target_profit")

    def test_flag_on_below_target_holds(self):
        # +$30 unified mark → no trigger even with flag on (regression guard).
        out = self._run(_f_position(30.0), flag_on=True)
        self.assertEqual(out, [])

    def test_per_cohort_threshold_used(self):
        # cohort target_profit_pct=0.75 → threshold 480×0.75=$360; +$300 holds.
        out = self._run(_f_position(300.0), flag_on=True, cohort_tp_pct=0.75)
        self.assertEqual(out, [])
        # …but +$400 (≥360) fires under the same cohort threshold.
        out2 = self._run(_f_position(400.0), flag_on=True, cohort_tp_pct=0.75)
        self.assertEqual(len(out2), 1)
        self.assertEqual(out2[0][1], "target_profit")

    def test_stop_loss_unchanged_and_takes_priority(self):
        # A position at a big loss fires stop_loss (cohort sl pinned = the
        # 0.50 default above), regardless of the TP flag — priority and
        # threshold arithmetic preserved from the pre-Area-7 behavior.
        loss_pos = _f_position(-300.0)
        out_on = self._run(loss_pos, flag_on=True)
        out_off = self._run(loss_pos, flag_on=False)
        self.assertEqual(out_on, [(loss_pos, "stop_loss")])
        self.assertEqual(out_off, [(loss_pos, "stop_loss")])


class _NoExistingOrderSupabase:
    """Stub: idempotency pre-check finds no existing close order → proceed."""
    class _Q:
        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def in_(self, *a, **k): return self
        def execute(self):
            return types.SimpleNamespace(data=[])
    def table(self, *a, **k): return self._Q()


class TestExecuteForceCloseAttribution(unittest.TestCase):
    """End-to-end: the override routes the correct reason to the SHARED
    _close_position so target_profit records target_profit_hit, while
    stop_loss/envelope keep the risk_envelope: (→ envelope_force_close) form."""

    def _capture_reason(self, mapped_close_reason, incoming_reason="intraday_target_profit"):
        captured = {}

        def _fake_close(self_eval, user_id, position_id, reason,
                        exit_price_override=None, reason_detail=None):
            # exit_price_override added by the fresh-mark close-staging fix
            # (the monitor now passes its decision mark through); reason_detail
            # added by F-A3-1 Part B (the granular thesis close-reason) —
            # accepted here so the attribution capture keeps working.
            captured["reason"] = reason
            captured["reason_detail"] = reason_detail
            return {"routed_to": "submitted", "position_id": position_id}

        m = _monitor()
        m.supabase = _NoExistingOrderSupabase()
        pos = _f_position(300.0)
        with patch(
            "packages.quantum.services.paper_exit_evaluator.PaperExitEvaluator._close_position",
            _fake_close,
        ):
            m._execute_force_close(pos, incoming_reason, "u1", mapped_close_reason=mapped_close_reason)
        return captured.get("reason")

    def test_target_profit_override_passes_bare_reason(self):
        reason = self._capture_reason(mapped_close_reason="target_profit")
        self.assertEqual(reason, "target_profit")
        self.assertEqual(_map_close_reason(reason), "target_profit_hit")

    def test_no_override_keeps_risk_envelope_prefix(self):
        reason = self._capture_reason(
            mapped_close_reason=None, incoming_reason="intraday_stop_loss"
        )
        self.assertEqual(reason, "risk_envelope:intraday_stop_loss")
        self.assertEqual(_map_close_reason(reason), "envelope_force_close")


if __name__ == "__main__":
    unittest.main()
