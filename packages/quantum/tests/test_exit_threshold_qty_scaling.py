"""
Regression test for the exit-eval threshold quantity-scaling fix
(2026-05-28).

Bug: _check_target_profit and _check_stop_loss computed
    entry_cost = abs(max_credit) * 100
where max_credit is the PER-SPREAD net premium. unrealized_pl
(written by paper_mark_to_market as avg_entry × abs(qty) × 100) is
POSITION-scale. So the threshold was per-contract while the value it
gated was per-position — 5× too tight on the live 5-contract F debit
spread (tp $33.60 vs intended $168; stop −$48 vs intended −$240). The
F position sat ~$3 from a false stop at −$48 while its true −50% stop
should have been −$240.

Fix: entry_cost = abs(max_credit) * 100 * abs(quantity), applied in
_check_target_profit, _check_stop_loss, and the EXIT_EVAL_DEBUG log.

These tests would FAIL on the pre-fix code (which fired stop_loss on a
5-contract position at −$48) and PASS on the fixed code. The qty=1 case
pins that the fix reduces to the old per-contract behavior exactly.
"""

import unittest

from packages.quantum.services.paper_exit_evaluator import (
    _check_target_profit,
    _check_stop_loss,
)


def _debit_pos(*, max_credit, qty, upl):
    """F-shaped long-call debit spread fixture."""
    return {
        "id": "test-pos",
        "symbol": "F",
        "strategy": "LONG_CALL_DEBIT_SPREAD",
        "max_credit": max_credit,
        "quantity": qty,
        "unrealized_pl": upl,
        # entry_dte == dte keeps _time_scaled_* at base, but these tests
        # call the check fns with explicit pct so scaling isn't invoked.
        "entry_dte": 29,
        "nearest_expiry": None,
        "legs": [],
    }


class TestMultiContractScaling(unittest.TestCase):
    """F's actual shape: max_credit 0.96, 5 contracts → entry_cost $480.
    tp@35% = $168, stop@50% = −$240."""

    def test_target_profit_fires_at_position_scale_threshold(self):
        # $170 > $168 → fire
        pos = _debit_pos(max_credit=0.96, qty=5, upl=170.0)
        self.assertTrue(_check_target_profit(pos, tp_pct=0.35))

    def test_target_profit_holds_below_position_scale_threshold(self):
        # $160 < $168 → hold. (Pre-fix threshold was $33.60 → would have
        # falsely fired at $160.)
        pos = _debit_pos(max_credit=0.96, qty=5, upl=160.0)
        self.assertFalse(_check_target_profit(pos, tp_pct=0.35))

    def test_stop_loss_fires_at_position_scale_threshold(self):
        # −$250 < −$240 → fire
        pos = _debit_pos(max_credit=0.96, qty=5, upl=-250.0)
        self.assertTrue(_check_stop_loss(pos, sl_pct=0.50))

    def test_stop_loss_holds_at_live_position_loss(self):
        # The live bdbe4d04 case: −$45 on a 5ct position. Correct stop is
        # −$240, so HOLD. Pre-fix stop was −$48 → −$45 held by only $3
        # (one tick from a false stop). Post-fix it holds with $195 margin.
        pos = _debit_pos(max_credit=0.96, qty=5, upl=-45.0)
        self.assertFalse(_check_stop_loss(pos, sl_pct=0.50))

    def test_stop_loss_holds_at_loss_that_pre_fix_would_have_closed(self):
        # −$50 on 5ct: correct stop −$240 → HOLD. Pre-fix stop −$48 →
        # −$50 <= −$48 → would have FALSE-fired. This is the regression.
        pos = _debit_pos(max_credit=0.96, qty=5, upl=-50.0)
        self.assertFalse(_check_stop_loss(pos, sl_pct=0.50))


class TestSingleContractUnchanged(unittest.TestCase):
    """At qty=1 the fix reduces to the old per-contract value exactly:
    entry_cost $96, tp@35% = $33.60, stop@50% = −$48."""

    def test_target_profit_qty1_matches_legacy(self):
        self.assertTrue(_check_target_profit(_debit_pos(max_credit=0.96, qty=1, upl=34.0), tp_pct=0.35))
        self.assertFalse(_check_target_profit(_debit_pos(max_credit=0.96, qty=1, upl=33.0), tp_pct=0.35))

    def test_stop_loss_qty1_matches_legacy(self):
        # −$50 <= −$48 → fire (legacy per-contract behavior preserved at qty=1)
        self.assertTrue(_check_stop_loss(_debit_pos(max_credit=0.96, qty=1, upl=-50.0), sl_pct=0.50))
        # −$45 > −$48 → hold
        self.assertFalse(_check_stop_loss(_debit_pos(max_credit=0.96, qty=1, upl=-45.0), sl_pct=0.50))


class TestNegativeQtyAbsHandling(unittest.TestCase):
    """Short/credit positions store negative quantity. entry_cost must use
    abs(qty) so the threshold scales by contract count, not sign."""

    def _credit_pos(self, *, max_credit, qty, upl):
        # No LONG_/DEBIT in strategy and qty<0 → _is_debit_spread False →
        # credit branch (requires mc > 0).
        return {
            "id": "test-credit",
            "symbol": "XYZ",
            "strategy": "SHORT_PUT_CREDIT_SPREAD",
            "max_credit": max_credit,
            "quantity": qty,
            "unrealized_pl": upl,
            "entry_dte": 29,
            "nearest_expiry": None,
            "legs": [],
        }

    def test_credit_target_profit_uses_abs_qty(self):
        # max_credit 0.96, qty −5 → entry_cost = 0.96×100×5 = $480.
        # tp@35% = $168. upl $170 → fire.
        pos = self._credit_pos(max_credit=0.96, qty=-5, upl=170.0)
        self.assertTrue(_check_target_profit(pos, tp_pct=0.35))
        # $160 < $168 → hold
        pos2 = self._credit_pos(max_credit=0.96, qty=-5, upl=160.0)
        self.assertFalse(_check_target_profit(pos2, tp_pct=0.35))

    def test_credit_stop_loss_uses_abs_qty(self):
        # stop@50% of $480 = −$240. −$250 → fire.
        pos = self._credit_pos(max_credit=0.96, qty=-5, upl=-250.0)
        self.assertTrue(_check_stop_loss(pos, sl_pct=0.50))
        # −$200 > −$240 → hold
        pos2 = self._credit_pos(max_credit=0.96, qty=-5, upl=-200.0)
        self.assertFalse(_check_stop_loss(pos2, sl_pct=0.50))


class TestSourceGuard(unittest.TestCase):
    """Defends against the fix being reverted at any of the 3 sites."""

    def test_all_entry_cost_sites_scale_by_qty(self):
        from pathlib import Path
        src = (
            Path(__file__).resolve().parent.parent
            / "services" / "paper_exit_evaluator.py"
        ).read_text(encoding="utf-8")
        # The pre-fix expression `abs(mc) * 100` (decision sites) and
        # `abs(mc) * 100` w/o qty must NOT exist as a bare threshold.
        # Both decision functions + the debug log must scale by abs(qty).
        self.assertEqual(
            src.count("abs(mc) * 100 * abs(float(pos.get(\"quantity\") or 1))"),
            2,
            "Both _check_target_profit and _check_stop_loss must scale "
            "entry_cost by abs(quantity).",
        )
        self.assertIn(
            "abs(mc) * 100 * abs(float(qty or 1))",
            src,
            "The EXIT_EVAL_DEBUG entry_cost must also scale by abs(qty) "
            "for log/decision consistency.",
        )
        # The bare per-spread form must no longer appear.
        self.assertNotIn(
            "entry_cost = abs(mc) * 100\n",
            src,
            "Bare per-spread entry_cost (no qty) reintroduced — this is "
            "the 2026-05-28 regression.",
        )


if __name__ == "__main__":
    unittest.main()
