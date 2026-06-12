"""Tests for cohort-aware STOPS on the 15-min intraday path (audit Area 7).

Before this change the monitor loaded cohort configs only inside the
target_profit flag gate and consumed them only for TP — stop_loss was
evaluated against the global default (flat 0.50 of entry_cost), so the
binding cohort stops (0.15/0.20/0.30) were checked only by the 2-3x/day
scheduled sweeps. The 06-08 shadow NFLX stops closed $211.80 past their
configured thresholds at the Monday 13:00Z pre-open sweep.

Pins:
- a position past its COHORT stop but above the default 0.50 fires
  stop_loss on a 15-min pass when INTRADAY_COHORT_STOP_ENABLED (default ON)
- explicit flag off -> legacy default-conditions stop (fires later, never
  differently)
- cohort load failure / cohort resolution failure -> default conditions
  (fail-safe = looser stop, today's behavior)
- the #1035 unpriceable-mark asymmetry is untouched: a cohort-stop breach
  on an unpriceable mark still defers with stop_loss_protection_degraded
- flag parse: empty/unset -> ON; only explicit 0/false/no/off disables
"""

import sys
import types
import unittest
from unittest.mock import patch

# Stub alpaca-py so imports resolve in the test venv (mirrors test_force_close_path).
sys.modules.setdefault("alpaca", types.ModuleType("alpaca"))
sys.modules.setdefault("alpaca.trading", types.ModuleType("alpaca.trading"))
sys.modules.setdefault("alpaca.trading.requests", types.ModuleType("alpaca.trading.requests"))

from packages.quantum.jobs.handlers import intraday_risk_monitor as irm  # noqa: E402
from packages.quantum.policy_lab.config import PolicyConfig  # noqa: E402


def _f_position(unrealized_pl, quantity=5.0, avg_entry=0.96, unpriceable=False):
    """F-shape debit call spread; entry_cost = 0.96 x 5 x 100 = $480.
    Default stop threshold (0.50) = -$240; a 0.20 cohort stop = -$96."""
    pos = {
        "id": "pos-f", "user_id": "u1", "symbol": "F", "quantity": quantity,
        "avg_entry_price": avg_entry, "max_credit": avg_entry,
        "current_mark": 1.02, "unrealized_pl": unrealized_pl,
        "strategy_key": "F_long_call_debit_spread",
        "cohort_id": "cohort-1",
        "nearest_expiry": "2099-06-26",
        # 06-12 stale-mark guard: these fixtures model positions whose marks
        # were just recomputed by _refresh_marks — declare the provenance the
        # real pass would set, or the guard (correctly) refuses to fire
        # mark-derived exits on an unprovenanced value.
        "_mark_fresh": True,
        "legs": [
            {"type": "call", "action": "buy", "strike": 15.5, "symbol": "O:F260626C00015500", "quantity": 5},
            {"type": "call", "action": "sell", "strike": 17.5, "symbol": "O:F260626C00017500", "quantity": 5},
        ],
    }
    if unpriceable:
        pos["_mark_unpriceable"] = True
    return pos


def _monitor():
    m = irm.IntradayRiskMonitor.__new__(irm.IntradayRiskMonitor)
    m.supabase = object()
    m._log_alert_calls = []
    m._log_alert = lambda **kw: m._log_alert_calls.append(kw)
    return m


class TestFlagParse(unittest.TestCase):
    def test_unset_is_on(self):
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("INTRADAY_COHORT_STOP_ENABLED", None)
            self.assertTrue(irm._intraday_cohort_stop_enabled())

    def test_empty_is_on(self):
        with patch.dict("os.environ", {"INTRADAY_COHORT_STOP_ENABLED": ""}):
            self.assertTrue(irm._intraday_cohort_stop_enabled())

    def test_explicit_off(self):
        for off in ("0", "false", "no", "off", " FALSE "):
            with patch.dict("os.environ", {"INTRADAY_COHORT_STOP_ENABLED": off}):
                self.assertFalse(irm._intraday_cohort_stop_enabled())

    def test_one_is_on(self):
        with patch.dict("os.environ", {"INTRADAY_COHORT_STOP_ENABLED": "1"}):
            self.assertTrue(irm._intraday_cohort_stop_enabled())


class TestCohortAwareStops(unittest.TestCase):
    def _run(self, position, *, cohort_sl_pct=0.20, stop_flag_env=None,
             tp_flag=False, cohort_load_raises=False, resolve_raises=False):
        cfg = PolicyConfig(target_profit_pct=0.50, stop_loss_pct=cohort_sl_pct)
        env = {}
        if stop_flag_env is not None:
            env["INTRADAY_COHORT_STOP_ENABLED"] = stop_flag_env

        def _load(*a, **k):
            if cohort_load_raises:
                raise RuntimeError("cohort config table unavailable")
            return {"aggressive": cfg}

        def _resolve(self_eval, pos):
            if resolve_raises:
                raise RuntimeError("cohort resolution failed")
            return "aggressive"

        m = _monitor()
        with patch.dict("os.environ", env), patch.object(
            irm, "_INTRADAY_TARGET_PROFIT_ENABLED", tp_flag,
        ), patch(
            "packages.quantum.policy_lab.config.load_cohort_configs",
            side_effect=_load,
        ), patch(
            "packages.quantum.services.paper_exit_evaluator.PaperExitEvaluator.__init__",
            return_value=None,
        ), patch(
            "packages.quantum.services.paper_exit_evaluator.PaperExitEvaluator._resolve_position_cohort",
            _resolve,
        ):
            return m._collect_intraday_exit_triggers([position], "u1"), m

    def test_cohort_stop_fires_in_the_previously_blind_band(self):
        # -$150: past the 0.20 cohort stop (-$96), above the default -$240.
        # Pre-fix: NO intraday trigger (rode until the next scheduled sweep).
        out, _ = self._run(_f_position(-150.0))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][1], "stop_loss")

    def test_above_cohort_stop_holds(self):
        out, _ = self._run(_f_position(-50.0))  # above -$96
        self.assertEqual(out, [])

    def test_explicit_flag_off_restores_legacy_default_stop(self):
        # Same -$150 with the kill switch off -> default 0.50 (-$240) -> hold.
        out, _ = self._run(_f_position(-150.0), stop_flag_env="0")
        self.assertEqual(out, [])
        # ...and a true default-stop breach still fires under legacy.
        out2, _ = self._run(_f_position(-300.0), stop_flag_env="0")
        self.assertEqual(out2, [(out2[0][0], "stop_loss")])

    def test_cohort_load_failure_falls_back_to_default_conditions(self):
        out, _ = self._run(_f_position(-150.0), cohort_load_raises=True)
        self.assertEqual(out, [])  # default -$240 not breached -> hold
        out2, _ = self._run(_f_position(-300.0), cohort_load_raises=True)
        self.assertEqual(len(out2), 1)
        self.assertEqual(out2[0][1], "stop_loss")

    def test_cohort_resolution_failure_falls_back_to_default_conditions(self):
        out, _ = self._run(_f_position(-150.0), resolve_raises=True)
        self.assertEqual(out, [])

    def test_unpriceable_mark_still_defers_with_degraded_alert(self):
        # The #1035 asymmetry is untouched: a cohort-stop breach on an
        # unpriceable mark must NOT act, and must alert loudly.
        out, m = self._run(_f_position(-150.0, unpriceable=True))
        self.assertEqual(out, [])
        kinds = [c.get("alert_type") for c in m._log_alert_calls]
        self.assertIn("stop_loss_protection_degraded", kinds)

    def test_tp_still_cohort_resolved_when_stop_flag_off(self):
        # TP branch keeps using cohort conditions independent of the stop flag.
        out, _ = self._run(
            _f_position(300.0), stop_flag_env="0", tp_flag=True,
        )
        # cohort tp 0.50 -> threshold $240; +$300 fires target_profit.
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][1], "target_profit")

    def test_stop_takes_priority_over_tp(self):
        # A breached cohort stop wins over any profit check ordering.
        out, _ = self._run(_f_position(-150.0), tp_flag=True)
        self.assertEqual(out[0][1], "stop_loss")


if __name__ == "__main__":
    unittest.main()
