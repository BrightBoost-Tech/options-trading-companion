"""Regression tests for the 2026-05-18 stop-loss time-scaling audit.

See docs/audit_hold_period_asymmetry.md for the empirical basis.

Three invariants under test:

1. Flag OFF (default) — flat 0.50 threshold; iron_condor and debit_spread
   both behave identically to pre-audit code.
2. Flag ON — debit_spread stops compute via _time_scaled_stop_loss_pct
   (sqrt-decay with 0.30 floor).
3. Flag ON — iron_condor / credit / other ALWAYS bypass the time-scaling
   (Q2 guardrail: AMZN/GOOGL iron_condor recoveries from <-50% loss).
"""
from __future__ import annotations

import importlib
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch


def _reload_module():
    """Reload the evaluator module so env changes pick up at import time."""
    import packages.quantum.services.paper_exit_evaluator as pee
    return importlib.reload(pee)


def _mk_debit_pos(max_credit=5.0, upl=-100.0, dte=20, entry_dte=35):
    """Synthetic debit-spread position. max_credit positive convention =
    premium paid (per-contract dollars). Entry cost = max_credit*100."""
    exp = (datetime.now(timezone.utc) + timedelta(days=dte)).date().isoformat()
    return {
        "strategy_key": "TEST_long_call_debit_spread",
        "max_credit": max_credit,
        "unrealized_pl": upl,
        "nearest_expiry": exp,
        "entry_dte": entry_dte,
        "quantity": 1,
    }


def _mk_iron_condor_pos(max_credit=5.0, upl=-500.0, dte=20, entry_dte=35):
    """Synthetic iron-condor position. Credit-collect convention."""
    exp = (datetime.now(timezone.utc) + timedelta(days=dte)).date().isoformat()
    return {
        "strategy_key": "TEST_iron_condor",
        "max_credit": max_credit,
        "unrealized_pl": upl,
        "nearest_expiry": exp,
        "entry_dte": entry_dte,
        "quantity": 1,
    }


class TestStopLossTimeScalingFlagOff(unittest.TestCase):
    """When flag is OFF (default), behavior MUST be identical to pre-audit."""

    @patch.dict(os.environ, {"EXIT_STOP_LOSS_TIME_SCALING_ENABLED": "0"})
    def test_debit_spread_uses_flat_threshold(self):
        pee = _reload_module()
        # entry_cost = 5*100 = $500; flat 0.50 → trigger at -$250
        pos_249 = _mk_debit_pos(max_credit=5.0, upl=-249.0, dte=10, entry_dte=35)
        pos_251 = _mk_debit_pos(max_credit=5.0, upl=-251.0, dte=10, entry_dte=35)
        self.assertFalse(pee._check_stop_loss(pos_249, 0.50))
        self.assertTrue(pee._check_stop_loss(pos_251, 0.50))

    @patch.dict(os.environ, {"EXIT_STOP_LOSS_TIME_SCALING_ENABLED": "0"})
    def test_low_dte_does_not_tighten_when_flag_off(self):
        """Even at dte_ratio=0.14 (would scale to 0.30 floor if flag on),
        flag-off stays at 0.50 flat."""
        pee = _reload_module()
        pos = _mk_debit_pos(max_credit=5.0, upl=-200.0, dte=5, entry_dte=35)
        # 0.50 of $500 = $250 trigger; -$200 should NOT fire
        self.assertFalse(pee._check_stop_loss(pos, 0.50))

    @patch.dict(os.environ, {"EXIT_STOP_LOSS_TIME_SCALING_ENABLED": "0"})
    def test_iron_condor_flat_unchanged(self):
        pee = _reload_module()
        pos = _mk_iron_condor_pos(max_credit=5.0, upl=-249.0, dte=10, entry_dte=35)
        self.assertFalse(pee._check_stop_loss(pos, 0.50))
        pos2 = _mk_iron_condor_pos(max_credit=5.0, upl=-251.0, dte=10, entry_dte=35)
        self.assertTrue(pee._check_stop_loss(pos2, 0.50))


class TestStopLossTimeScalingFlagOn(unittest.TestCase):
    """When flag is ON, debit spreads tighten with DTE per sqrt-decay."""

    @patch.dict(os.environ, {"EXIT_STOP_LOSS_TIME_SCALING_ENABLED": "1"})
    def test_at_entry_unchanged(self):
        """dte/entry_dte = 1.0 → sl = base (0.50). Identical to flag-off
        at the exact moment of entry."""
        pee = _reload_module()
        # dte=35, entry_dte=35 → ratio=1.0 → sl=0.50
        pos_249 = _mk_debit_pos(max_credit=5.0, upl=-249.0, dte=35, entry_dte=35)
        pos_251 = _mk_debit_pos(max_credit=5.0, upl=-251.0, dte=35, entry_dte=35)
        self.assertFalse(pee._check_stop_loss(pos_249, 0.50))
        self.assertTrue(pee._check_stop_loss(pos_251, 0.50))

    @patch.dict(os.environ, {"EXIT_STOP_LOSS_TIME_SCALING_ENABLED": "1"})
    def test_midlife_tightens(self):
        """dte_ratio ≈ 0.5 → sl ≈ 0.50 * sqrt(0.5) ≈ 0.354. Entry cost
        $500 → trigger at ≈ -$177 (not -$250)."""
        pee = _reload_module()
        # dte≈17, entry_dte=35 → ratio≈0.486 → sl ≈ 0.349
        pos_below = _mk_debit_pos(max_credit=5.0, upl=-170.0, dte=17, entry_dte=35)
        pos_above = _mk_debit_pos(max_credit=5.0, upl=-180.0, dte=17, entry_dte=35)
        self.assertFalse(pee._check_stop_loss(pos_below, 0.50))
        self.assertTrue(pee._check_stop_loss(pos_above, 0.50))

    @patch.dict(os.environ, {"EXIT_STOP_LOSS_TIME_SCALING_ENABLED": "1"})
    def test_floor_applies_near_expiry(self):
        """dte=5, entry_dte=35 → ratio=0.143 → raw sl ≈ 0.189 → clamped
        to 0.30 floor. Trigger at -$150 on $500 entry."""
        pee = _reload_module()
        pos_below = _mk_debit_pos(max_credit=5.0, upl=-149.0, dte=5, entry_dte=35)
        pos_above = _mk_debit_pos(max_credit=5.0, upl=-151.0, dte=5, entry_dte=35)
        self.assertFalse(pee._check_stop_loss(pos_below, 0.50))
        self.assertTrue(pee._check_stop_loss(pos_above, 0.50))

    @patch.dict(os.environ, {"EXIT_STOP_LOSS_TIME_SCALING_ENABLED": "1"})
    def test_iron_condor_bypasses_time_scaling(self):
        """Critical guardrail: iron_condor stays on flat threshold even
        with flag on. Q2 evidence (AMZN/GOOGL recovered from <-50%)."""
        pee = _reload_module()
        # If time-scaling applied, dte=5 → sl=0.30 → trigger at -$150.
        # With bypass, sl stays flat 0.50 → trigger at -$250.
        pos = _mk_iron_condor_pos(max_credit=5.0, upl=-200.0, dte=5, entry_dte=35)
        self.assertFalse(pee._check_stop_loss(pos, 0.50))
        # Confirms -$200 does NOT fire (flat 0.50 threshold of $250).

    @patch.dict(os.environ, {"EXIT_STOP_LOSS_TIME_SCALING_ENABLED": "1"})
    def test_missing_dte_falls_back_to_flat(self):
        """If DTE data is missing, time-scaling can't compute → return
        the unscaled base_sl_pct (no surprise tightening)."""
        pee = _reload_module()
        pos = _mk_debit_pos(max_credit=5.0, upl=-200.0, dte=10, entry_dte=35)
        pos["entry_dte"] = None  # truly missing
        pos.pop("nearest_expiry", None)  # remove DTE source → days_to_expiry=999
        # _time_scaled_stop_loss_pct returns base (0.50) → trigger at -$250
        self.assertFalse(pee._check_stop_loss(pos, 0.50))
        pos["unrealized_pl"] = -260.0
        self.assertTrue(pee._check_stop_loss(pos, 0.50))


class TestStopLossTimeScalingFormula(unittest.TestCase):
    """Direct unit tests of _time_scaled_stop_loss_pct shape."""

    @patch.dict(os.environ, {"EXIT_STOP_LOSS_TIME_SCALING_ENABLED": "1"})
    def test_formula_at_entry(self):
        pee = _reload_module()
        pos = _mk_debit_pos(dte=35, entry_dte=35)
        self.assertAlmostEqual(
            pee._time_scaled_stop_loss_pct(pos, 0.50), 0.50, places=3
        )

    @patch.dict(os.environ, {"EXIT_STOP_LOSS_TIME_SCALING_ENABLED": "1"})
    def test_formula_midlife(self):
        pee = _reload_module()
        pos = _mk_debit_pos(dte=17, entry_dte=35)
        # 0.50 * sqrt(17/35) = 0.50 * sqrt(0.4857) ≈ 0.3485
        self.assertAlmostEqual(
            pee._time_scaled_stop_loss_pct(pos, 0.50), 0.3485, places=2
        )

    @patch.dict(os.environ, {"EXIT_STOP_LOSS_TIME_SCALING_ENABLED": "1"})
    def test_formula_floor_clamps(self):
        pee = _reload_module()
        pos = _mk_debit_pos(dte=1, entry_dte=35)
        # raw = 0.50 * sqrt(1/35) ≈ 0.0845 → clamped to floor 0.30
        self.assertEqual(
            pee._time_scaled_stop_loss_pct(pos, 0.50), 0.30
        )

    @patch.dict(
        os.environ,
        {
            "EXIT_STOP_LOSS_TIME_SCALING_ENABLED": "1",
            "EXIT_STOP_LOSS_FLOOR_PCT": "0.25",
        },
    )
    def test_floor_env_overridable(self):
        pee = _reload_module()
        pos = _mk_debit_pos(dte=1, entry_dte=35)
        self.assertEqual(
            pee._time_scaled_stop_loss_pct(pos, 0.50), 0.25
        )


if __name__ == "__main__":
    unittest.main()
