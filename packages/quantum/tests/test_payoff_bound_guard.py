"""Tests for the convention-agnostic payoff-bound guard (Task 1, 2026-05-28).

The guard bounds an already-computed ``unrealized_pl`` to a debit spread's
physical payoff envelope and surfaces impossible marks loudly. It is NOT a
mark fix — it does not make F read −$45; it clamps the F-style +$1,695
corruption to the payoff bound (+$520) and alerts. It must be:

  * convention-agnostic — the bound comes from pos.quantity + strikes +
    avg_entry, never legs.quantity, so it neither misfires on the per-spread
    shape (legs.quantity=1, pos.quantity=4) nor misses the full-count
    corruption (legs.quantity=5);
  * inert on correctly-marked positions (in-bounds values pass untouched);
  * a pure add-on — it changes no mark math, so the pre-existing
    TestRefreshMarksScale and exit/risk suites still pass.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from packages.quantum.risk.payoff_bounds import (
    evaluate_payoff_bound,
    payoff_bound_alert_fields,
    ALERT_TYPE,
)
from packages.quantum.jobs.handlers.intraday_risk_monitor import IntradayRiskMonitor
from packages.quantum.services.cache_key_builder import normalize_symbol


# ── F's real geometry, parameterised by leg-quantity convention ──────────

def _f_position(pos_qty, leg_qty):
    """F debit call spread: long 15.5C / short 17.5C, entry 0.96, width 2.0.
    `leg_qty` lets a test choose the persistence convention independently of
    `pos_qty` (the whole point: the guard must not depend on it)."""
    return {
        "id": "bdbe4d04-5d89-42e6-b9f1-cf3ed82aeaba",
        "user_id": "u1",
        "symbol": "F",
        "quantity": pos_qty,
        "avg_entry_price": 0.96,
        "legs": [
            {"type": "call", "action": "buy", "strike": 15.5,
             "symbol": "O:F260626C00015500", "quantity": leg_qty},
            {"type": "call", "action": "sell", "strike": 17.5,
             "symbol": "O:F260626C00017500", "quantity": leg_qty},
        ],
    }


# ════════════════════════════════════════════════════════════════════════
# Pure-function unit tests
# ════════════════════════════════════════════════════════════════════════

class TestEvaluatePayoffBound(unittest.TestCase):

    def test_f_corruption_above_max_profit_clamps(self):
        # entry_value = 0.96*5*100 = 480 ; width 2.0 ; max_profit = 520.
        res = evaluate_payoff_bound(_f_position(5, 5), 1695.0)
        self.assertTrue(res.applicable)
        self.assertFalse(res.in_bounds)
        self.assertEqual(res.violated_side, "above_max_profit")
        self.assertAlmostEqual(res.max_loss, -480.0, places=2)
        self.assertAlmostEqual(res.max_profit, 520.0, places=2)
        self.assertAlmostEqual(res.clamped_value, 520.0, places=2)
        self.assertAlmostEqual(res.raw_value, 1695.0, places=2)

    def test_f_correct_value_in_bounds_untouched(self):
        res = evaluate_payoff_bound(_f_position(5, 5), -45.0)
        self.assertTrue(res.applicable)
        self.assertTrue(res.in_bounds)
        self.assertIsNone(res.violated_side)
        self.assertAlmostEqual(res.clamped_value, -45.0, places=2)

    def test_per_spread_convention_same_bound(self):
        """Convention-agnostic: F stored as legs.quantity=1 (per-spread) with
        pos.quantity=5 must yield the IDENTICAL bound, because the bound never
        reads legs.quantity."""
        full = evaluate_payoff_bound(_f_position(5, 5), -45.0)
        per_spread = evaluate_payoff_bound(_f_position(5, 1), -45.0)
        self.assertEqual(per_spread.max_loss, full.max_loss)
        self.assertEqual(per_spread.max_profit, full.max_profit)
        self.assertTrue(per_spread.in_bounds)

    def test_below_max_loss_clamps(self):
        res = evaluate_payoff_bound(_f_position(5, 5), -2000.0)
        self.assertFalse(res.in_bounds)
        self.assertEqual(res.violated_side, "below_max_loss")
        self.assertAlmostEqual(res.clamped_value, -480.0, places=2)

    def test_csx_per_spread_correct_loss_in_bounds(self):
        """CSX-shaped per-spread position: pos.quantity=4, entry 2.50, width
        4.5 → bound [-1000, 800]. The correct −$120 is in-bounds → untouched.
        Proves the guard does not misfire on the per-spread shape."""
        pos = {
            "id": "csx", "user_id": "u1", "symbol": "CSX", "quantity": 4,
            "avg_entry_price": 2.50,
            "legs": [
                {"action": "buy", "strike": 44.0, "quantity": 1},
                {"action": "sell", "strike": 48.5, "quantity": 1},
            ],
        }
        res = evaluate_payoff_bound(pos, -120.0)
        self.assertTrue(res.applicable)
        self.assertTrue(res.in_bounds)
        self.assertAlmostEqual(res.max_loss, -1000.0, places=2)
        self.assertAlmostEqual(res.max_profit, 800.0, places=2)

    # ── Non-applicable shapes (returned untouched, never alerted) ────────

    def test_credit_spread_not_applicable(self):
        pos = {
            "id": "c", "quantity": -4, "avg_entry_price": 0.50,
            "legs": [
                {"action": "sell", "strike": 50.0, "quantity": 4},
                {"action": "buy", "strike": 52.0, "quantity": 4},
            ],
        }
        res = evaluate_payoff_bound(pos, -1080.0)
        self.assertFalse(res.applicable)
        self.assertEqual(res.clamped_value, -1080.0)

    def test_single_leg_not_applicable(self):
        pos = {"id": "s", "quantity": 3, "avg_entry_price": 1.5, "legs": [
            {"action": "buy", "strike": 100.0, "quantity": 3}]}
        self.assertFalse(evaluate_payoff_bound(pos, 9999.0).applicable)

    def test_calendar_zero_width_not_applicable(self):
        pos = {"id": "cal", "quantity": 2, "avg_entry_price": 1.0, "legs": [
            {"action": "buy", "strike": 100.0, "quantity": 2},
            {"action": "sell", "strike": 100.0, "quantity": 2}]}
        self.assertFalse(evaluate_payoff_bound(pos, 9999.0).applicable)

    def test_straddle_two_buys_not_applicable(self):
        pos = {"id": "str", "quantity": 2, "avg_entry_price": 3.0, "legs": [
            {"action": "buy", "strike": 100.0, "quantity": 2},
            {"action": "buy", "strike": 105.0, "quantity": 2}]}
        self.assertFalse(evaluate_payoff_bound(pos, 9999.0).applicable)

    def test_alert_fields_shape(self):
        res = evaluate_payoff_bound(_f_position(5, 5), 1695.0)
        fields = payoff_bound_alert_fields(_f_position(5, 5), res, "src")
        self.assertEqual(fields["alert_type"], ALERT_TYPE)
        self.assertEqual(fields["severity"], "critical")
        for k in ("raw_unrealized_pl", "clamped_unrealized_pl", "max_loss",
                  "max_profit", "violated_side", "source"):
            self.assertIn(k, fields["metadata"])
        self.assertEqual(fields["metadata"]["raw_unrealized_pl"], 1695.0)


# ════════════════════════════════════════════════════════════════════════
# Integration through the real intraday_risk_monitor._refresh_marks
# (proves the guard fires on the corrupted path and is inert on the
#  per-spread path — without altering any mark math)
# ════════════════════════════════════════════════════════════════════════

class _RecordingTable:
    def __init__(self, store, name):
        self._store, self._name = store, name

    def insert(self, row):
        self._store.append((self._name, row))
        return self

    def execute(self):
        return SimpleNamespace(data=[{}])


class _RecordingSupabase:
    def __init__(self):
        self.inserts = []

    def table(self, name):
        return _RecordingTable(self.inserts, name)


def _make_monitor():
    m = IntradayRiskMonitor.__new__(IntradayRiskMonitor)
    m.supabase = _RecordingSupabase()
    return m


def _refresh_with_prices(monitor, positions, prices):
    def fake_snapshot_many(symbols):
        return {
            normalize_symbol(s): {"quote": {"bid": prices[s], "ask": prices[s]}}
            for s in symbols if s in prices
        }
    with patch(
        "packages.quantum.services.market_data_truth_layer.MarketDataTruthLayer"
    ) as MTL:
        MTL.return_value.snapshot_many.side_effect = fake_snapshot_many
        return monitor._refresh_marks(positions)


def _violation_alerts(supabase):
    return [r for (t, r) in supabase.inserts
            if t == "risk_alerts" and r.get("alert_type") == ALERT_TYPE]


_F_PRICES = {"O:F260626C00015500": 1.44, "O:F260626C00017500": 0.57}


class TestGuardInRefreshMarks(unittest.TestCase):

    def test_full_count_f_computes_correctly_and_guard_quiet(self):
        """POST-#3: F stored full-count (legs=5) now computes the CORRECT value
        through the unified mark math — current=(1.44-0.57)*100*5=435,
        entry=0.96*5*100=480 → -$45, in bounds. The pre-#3 +$1,695 double-count
        is GONE, so the guard stays QUIET. This is the DB-side proof that #2 is
        resolved and the source of the deferred alert-quieting runtime signal."""
        monitor = _make_monitor()
        out = _refresh_with_prices(monitor, [_f_position(5, 5)], _F_PRICES)[0]
        self.assertAlmostEqual(out["unrealized_pl"], -45.0, places=2)
        self.assertEqual(_violation_alerts(monitor.supabase), [])

    def test_per_spread_row_wrong_but_in_bounds_guard_quiet(self):
        """POST-#3: the reader assumes full-count. A per-spread row (legs=1,
        pos=4) — now prevented at the fill seam — would compute the WRONG value
        (leg-sum at per-1 = 220, finalized vs per-4 entry 1000 → -$780). -$780 is
        still in-bounds [-1000, 800], so the guard does NOT catch this under-count
        direction. That is precisely why the fill-seam coercion (prevention), not
        the guard, is the load-bearing protection for per-spread rows."""
        monitor = _make_monitor()
        pos = {
            "id": "csx", "user_id": "u1", "symbol": "CSX", "quantity": 4,
            "avg_entry_price": 2.50,
            "legs": [
                {"type": "call", "action": "buy", "strike": 44.0,
                 "symbol": "O:CSX260618C00044000", "quantity": 1},
                {"type": "call", "action": "sell", "strike": 48.5,
                 "symbol": "O:CSX260618C00048500", "quantity": 1},
            ],
        }
        prices = {"O:CSX260618C00044000": 2.50, "O:CSX260618C00048500": 0.30}
        out = _refresh_with_prices(monitor, [pos], prices)[0]
        self.assertAlmostEqual(out["unrealized_pl"], -780.0, places=2)
        self.assertEqual(_violation_alerts(monitor.supabase), [])

    def test_out_of_bounds_corruption_still_fires_and_clamps(self):
        """The guard remains the live net: an impossible mark (a debit spread
        marked above its own width — a corrupt/crossed quote) still clamps to the
        payoff bound and alerts. F full-count, long mid 3.00 / short 0.10 → net
        2.90 > width 2.0 → current=1450, -480 entry = +970 > max_profit 520 →
        clamp to 520 + critical alert."""
        monitor = _make_monitor()
        prices = {"O:F260626C00015500": 3.00, "O:F260626C00017500": 0.10}
        out = _refresh_with_prices(monitor, [_f_position(5, 5)], prices)[0]
        self.assertAlmostEqual(out["unrealized_pl"], 520.0, places=2)
        alerts = _violation_alerts(monitor.supabase)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["severity"], "critical")
        self.assertAlmostEqual(
            alerts[0]["metadata"]["raw_unrealized_pl"], 970.0, places=2
        )


if __name__ == "__main__":
    unittest.main()
