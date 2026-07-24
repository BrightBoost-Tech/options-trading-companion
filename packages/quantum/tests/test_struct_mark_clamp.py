"""Phase B — structural mark-validity clamp + EXIT_EVAL_DEBUG honesty.

Commit 1 (clamp): an IMPOSSIBLE composed mark must never reach a stop_loss
force-close. The fixture is the real 2026-06-15 13:30Z QQQ condor: 5-wide
wings, 1.61 net credit, max structural loss $339; the monitor force-closed on
a composed mark −7.305 / implied −$569.50 (impossible). The clamp rejects
that (fail-closed: unpriceable this cycle) while a genuine near-max stop
(−$330 < $339) still FIRES — stops are never suppressed.

Commit 2 (debug honesty): the EXIT_EVAL_DEBUG line printed the DEFAULT stop
pct (0.50 → −$80.50) while the cohort check used 0.30 (→ −$48.30) — the
"−54<=−80.5=False but fired" confusion. The decision is stateless (no latch);
the bug was purely the lying print.
"""

import io
import os
import sys
import types
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

from packages.quantum.tests._alpaca_stub import ensure_alpaca as _ensure_alpaca

_ensure_alpaca()

from packages.quantum.risk import mark_validity as mv  # noqa: E402


def _qqq_condor(current_mark, unrealized_pl, quantity=-1.0, entry=1.61):
    """The live QQQ 6798e58f shape: 5-wide call + put verticals, 1.61 credit."""
    return {
        "id": "6798e58f", "symbol": "QQQ", "quantity": quantity,
        "avg_entry_price": entry, "current_mark": current_mark,
        "unrealized_pl": unrealized_pl,
        "legs": [
            {"symbol": "O:QQQ260710C00750000", "type": "call", "strike": 750, "action": "sell"},
            {"symbol": "O:QQQ260710C00755000", "type": "call", "strike": 755, "action": "buy"},
            {"symbol": "O:QQQ260710P00645000", "type": "put", "strike": 645, "action": "sell"},
            {"symbol": "O:QQQ260710P00640000", "type": "put", "strike": 640, "action": "buy"},
        ],
    }


# ── 1. Validator unit tests ─────────────────────────────────────────────────
class TestMarkValidity(unittest.TestCase):
    def test_wing_width_condor(self):
        self.assertEqual(mv.structure_wing_width(_qqq_condor(-2.0, -40)["legs"]), 5.0)

    def test_0615_phantom_rejected(self):
        """The exact 13:30Z phantom: mark −7.305 / implied −$569.50 → REJECT."""
        ok, reason, detail = mv.validate_structure_mark(_qqq_condor(-7.305, -569.5))
        self.assertFalse(ok)
        self.assertEqual(reason, mv.REASON_MARK_EXCEEDS_WING)  # |7.305| > 5.1
        self.assertEqual(detail["wing_width"], 5.0)
        self.assertEqual(detail["max_loss_dollars"], 339.0)  # (5 − 1.61) × 100

    def test_real_recovered_mark_passes(self):
        """The recovered real mark −2.34 / −$73 → PASS (eval proceeds)."""
        ok, reason, _ = mv.validate_structure_mark(_qqq_condor(-2.34, -73.0))
        self.assertTrue(ok)
        self.assertEqual(reason, mv.REASON_OK)

    def test_genuine_near_max_fires(self):
        """−$330 (< max $339) is a REAL stop and must NOT be clamped."""
        ok, reason, _ = mv.validate_structure_mark(_qqq_condor(-4.91, -330.0))
        self.assertTrue(ok, "a real near-max loss must pass so the stop fires")

    def test_exactly_at_max_passes(self):
        """At the structural max ($339, mark −5.0) is a real terminal stop."""
        ok, _, _ = mv.validate_structure_mark(_qqq_condor(-5.0, -339.0))
        self.assertTrue(ok)

    def test_just_beyond_wing_rejected(self):
        ok, reason, _ = mv.validate_structure_mark(_qqq_condor(-5.2, -360.0))
        self.assertFalse(ok)

    def test_loss_branch_independent_of_wing(self):
        """|mark| within wing but implied loss beyond max → reject on loss."""
        pos = _qqq_condor(-4.0, -600.0, entry=0.10)  # max_loss=(5−0.10)×100=490
        ok, reason, _ = mv.validate_structure_mark(pos)
        self.assertFalse(ok)
        self.assertEqual(reason, mv.REASON_LOSS_EXCEEDS_MAX)

    def test_single_leg_not_defined_risk(self):
        pos = {"symbol": "X", "quantity": 1, "avg_entry_price": 2.0,
               "current_mark": -50.0, "unrealized_pl": -5000.0,
               "legs": [{"type": "call", "strike": 100, "action": "buy"}]}
        ok, reason, _ = mv.validate_structure_mark(pos)
        self.assertTrue(ok)
        self.assertEqual(reason, mv.REASON_NOT_DEFINED_RISK)

    def test_malformed_never_raises(self):
        for bad in ({}, {"legs": None}, {"legs": [{"strike": "x"}]},
                    {"legs": [{"type": "call", "strike": 1}], "current_mark": None}):
            ok, _, _ = mv.validate_structure_mark(bad)
            self.assertTrue(ok, f"malformed {bad!r} must not block")

    def test_debit_spread_max_loss_is_debit(self):
        """Long debit vertical: max loss = debit paid; mark beyond wing rejects."""
        pos = {"symbol": "NFLX", "quantity": 1.0, "avg_entry_price": 3.65,
               "current_mark": -9.0, "unrealized_pl": -1265.0,
               "legs": [{"type": "put", "strike": 86, "action": "buy"},
                        {"type": "put", "strike": 79, "action": "sell"}]}
        ok, reason, _ = mv.validate_structure_mark(pos)
        self.assertFalse(ok)  # |9| > wing 7


# ── 2. Monitor clamp wiring (behavioral) ────────────────────────────────────
class TestMonitorClampWiring(unittest.TestCase):
    def _monitor(self):
        from packages.quantum.jobs.handlers.intraday_risk_monitor import IntradayRiskMonitor
        m = IntradayRiskMonitor.__new__(IntradayRiskMonitor)
        m.supabase = MagicMock()
        m.job_run_id = "t"
        m._log_alert = MagicMock()
        return m

    def _collect(self, positions):
        m = self._monitor()
        # stop_loss always "fires" if it reaches evaluate_position_exit
        with patch("packages.quantum.services.paper_exit_evaluator.evaluate_position_exit",
                   return_value="stop_loss"), \
             patch("packages.quantum.policy_lab.config.load_cohort_configs",
                   return_value={}):
            triggers = m._collect_intraday_exit_triggers(positions, "u1")
        return m, triggers

    def test_phantom_mark_not_acted_on(self):
        pos = _qqq_condor(-7.305, -569.5)
        pos["_mark_fresh"] = True
        m, triggers = self._collect([pos])
        ids = [p.get("id") for p, _ in triggers]
        self.assertNotIn("6798e58f", ids, "phantom must NOT produce a force-close")
        self.assertTrue(pos.get("_struct_clamp_rejected"))
        self.assertTrue(any(c.kwargs.get("alert_type") == "struct_clamp_rejected"
                            for c in m._log_alert.call_args_list))

    def test_real_near_max_stop_still_fires(self):
        pos = _qqq_condor(-4.91, -330.0)
        pos["_mark_fresh"] = True
        _, triggers = self._collect([pos])
        ids = [p.get("id") for p, r in triggers if r == "stop_loss"]
        self.assertIn("6798e58f", ids, "a real near-max stop MUST still fire")

    def test_clamp_call_present_before_unpriceable_read(self):
        import inspect
        from packages.quantum.jobs.handlers import intraday_risk_monitor as irm
        src = inspect.getsource(irm.IntradayRiskMonitor._collect_intraday_exit_triggers)
        self.assertIn("validate_structure_mark(pos)", src)
        self.assertLess(src.index("validate_structure_mark(pos)"),
                        src.index('unpriceable = bool(pos.get("_mark_unpriceable"))'))


# ── 3. paper_exit_evaluator clamp wiring (source pin) ───────────────────────
class TestPaperExitClampWiring(unittest.TestCase):
    def test_clamp_before_evaluate(self):
        import inspect
        from packages.quantum.services import paper_exit_evaluator as pe
        src = inspect.getsource(pe.PaperExitEvaluator.evaluate_exits)
        self.assertIn("validate_structure_mark(position)", src)
        self.assertLess(src.index("validate_structure_mark(position)"),
                        src.index("triggered = evaluate_position_exit("))


if __name__ == "__main__":
    unittest.main()
