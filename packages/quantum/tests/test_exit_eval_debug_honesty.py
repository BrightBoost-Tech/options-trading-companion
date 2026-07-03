"""Phase B Commit 2 — EXIT_EVAL_DEBUG honesty + decision statelessness.

The 06-15 13:30→14:15 QQQ saga exposed the §8 EXIT_EVAL_DEBUG known-liar: the
debug line computed its stop threshold from _DEFAULT_STOP_LOSS_PCT (0.50 →
−$80.50 on the 1.61cr/qty1 condor) while the actual cohort check used 0.30
(→ −$48.30). So the line printed "−54 <= −80.50 = False" while the decision
(−54 <= −48.30) correctly fired True — read in the morning as a "latched
trigger". There is NO latch: evaluate_position_exit is a stateless pure
function recomputed each cycle. The fix makes the printed threshold equal the
one the decision actually uses; these pins prove both.
"""

import io
import sys
import types
import unittest
from contextlib import redirect_stdout
from datetime import date, timedelta

sys.modules.setdefault("alpaca", types.ModuleType("alpaca"))
sys.modules.setdefault("alpaca.trading", types.ModuleType("alpaca.trading"))
sys.modules.setdefault("alpaca.trading.requests", types.ModuleType("alpaca.trading.requests"))

from packages.quantum.services.paper_exit_evaluator import (  # noqa: E402
    evaluate_position_exit, build_exit_conditions,
)


def _pos(upl):
    """QQQ 1.61cr condor, qty 1 → entry_cost 161; cohort stop 0.30 → −48.30.

    nearest_expiry is RELATIVE (today+45d), not the historical 2026-07-10:
    these pins test stop-threshold honesty and statelessness, NOT dte —
    the hardcoded date rotted on 2026-07-03 UTC when its dte entered the
    dte_threshold window (0 < dte <= 7) and 'no trigger' became
    'dte_threshold' for every CI run until expiry. Keep the expiry far
    outside min_dte so only the condition under test can fire.
    """
    far_expiry = (date.today() + timedelta(days=45)).isoformat()
    return {"id": "6798e58f", "symbol": "QQQ", "quantity": -1.0,
            "max_credit": 1.61, "avg_entry_price": 1.61, "unrealized_pl": upl,
            "nearest_expiry": far_expiry, "strategy": "IRON_CONDOR",
            "legs": [{"type": "call", "strike": 750, "action": "sell"},
                     {"type": "call", "strike": 755, "action": "buy"},
                     {"type": "put", "strike": 645, "action": "sell"},
                     {"type": "put", "strike": 640, "action": "buy"}]}


class TestExitEvalDebugHonesty(unittest.TestCase):
    def setUp(self):
        self.conds = build_exit_conditions(
            target_profit_pct=0.50, stop_loss_pct=0.30, min_dte_to_exit=7
        )

    def test_debug_prints_cohort_threshold_not_default(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            evaluate_position_exit(_pos(-54.0), conditions=self.conds)
        out = buf.getvalue()
        self.assertIn("-48.3", out)        # cohort 0.30 × 161
        self.assertNotIn("-80.5", out)     # the old default-0.50 lie

    def test_decision_matches_honest_debug(self):
        # −54 is past −48.30 → fires; the honest debug now prints True too.
        self.assertEqual(evaluate_position_exit(_pos(-54.0), conditions=self.conds), "stop_loss")

    def test_stateless_no_cross_cycle_latch(self):
        """Phantom-trigger one cycle, recover the next → NO latched re-trigger."""
        self.assertEqual(evaluate_position_exit(_pos(-54.0), conditions=self.conds), "stop_loss")
        self.assertIsNone(evaluate_position_exit(_pos(-20.0), conditions=self.conds))

    def test_build_exit_conditions_exposes_pct(self):
        self.assertEqual(self.conds["stop_loss"]["pct"], 0.30)
        self.assertEqual(self.conds["target_profit"]["pct"], 0.50)
        self.assertEqual(self.conds["dte_threshold"]["min_dte"], 7)


if __name__ == "__main__":
    unittest.main()
