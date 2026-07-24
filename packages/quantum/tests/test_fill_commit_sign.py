"""Fill-commit sign normalization (the 06-11 phantom force-close incident).

PR #1055 made live credit OPENS fill — and Alpaca's mleg filled_avg_price is
SIGNED (negative = net credit received). _commit_fill stored that raw signed
value into avg_entry_price / max_credit, but finalize_mark
(risk/mark_math.py:110) documents both fields as the ABSOLUTE per-spread
premium ("avg_entry_price stores the absolute per-spread net premium for
both"), and compute_realized_pl (services/close_math.py) documents
entry_price as "NEVER signed".

Consequence on 06-11: the first two live condors (filled −1.61 / −1.48)
landed in the DB with negative entries; the 16:30Z monitor computed
entry_value = −$161 and unrealized = −161 − |current_value| ≈ −$300 on a
position that was actually +$10.50 — a −22.8% phantom daily loss that
force-closed the ENTIRE live book (NFLX/QQQ/SPY, all healthy).

Pins:
- _abs_entry_premium: signed credit fill → positive premium; debit unchanged
- _weighted_abs_entry_avg: add-to-position math on ABS values throughout
- all write sites in _commit_fill / _repair_filled_order_commit route
  through the helpers (source pins)
- ROUND TRIP with the actual 06-11 numbers: fill −1.61, mark −1.505 →
  unrealized +$10.50 during the hold AND realized +$10.50 at a close at the
  same value. The incident-reproduction assertion documents what the raw
  signed write produced (−$311.50). This test existing on 06-10 would have
  caught the entire incident chain.
"""

import inspect
import sys
import types
import unittest
from decimal import Decimal

# Stub alpaca-py so transitive imports resolve in the test venv.
from packages.quantum.tests._alpaca_stub import ensure_alpaca as _ensure_alpaca

_ensure_alpaca()

from packages.quantum import paper_endpoints as pe  # noqa: E402
from packages.quantum.paper_endpoints import (  # noqa: E402
    _abs_entry_premium,
    _weighted_abs_entry_avg,
)
from packages.quantum.risk.mark_math import finalize_mark  # noqa: E402
from packages.quantum.services.close_math import compute_realized_pl  # noqa: E402


class TestAbsEntryPremium(unittest.TestCase):
    def test_live_credit_fill_normalizes_positive(self):
        # The 06-11 QQQ condor: Alpaca filled_avg_price = −1.61
        self.assertEqual(_abs_entry_premium(-1.61), 1.61)

    def test_live_debit_fill_unchanged(self):
        # The 06-04 NFLX debit spread: filled at +3.65 — no sign damage
        self.assertEqual(_abs_entry_premium(3.65), 3.65)

    def test_no_double_abs_distortion(self):
        # abs is idempotent — an already-positive premium stays itself
        self.assertEqual(_abs_entry_premium(_abs_entry_premium(-1.48)), 1.48)

    def test_none_and_zero(self):
        self.assertEqual(_abs_entry_premium(None), 0.0)
        self.assertEqual(_abs_entry_premium(0), 0.0)

    def test_string_coercion(self):
        # Broker JSON sometimes arrives stringly
        self.assertEqual(_abs_entry_premium("-1.61"), 1.61)


class TestWeightedAbsEntryAvg(unittest.TestCase):
    def test_add_to_credit_position_stays_positive(self):
        # Holding −1 @ 1.61 (stored ABS), add −1 filled at −1.55 (signed):
        # weighted avg must be (1.61 + 1.55) / 2 = 1.58, NOT (1.61 − 1.55)/2.
        avg = _weighted_abs_entry_avg(-1, 1.61, -1, -1.55)
        self.assertAlmostEqual(avg, 1.58, places=6)

    def test_add_to_debit_position_unchanged(self):
        avg = _weighted_abs_entry_avg(1, 3.65, 1, 3.55)
        self.assertAlmostEqual(avg, 3.60, places=6)

    def test_legacy_negative_stored_avg_also_normalized(self):
        # A pre-fix corrupted row (stored −1.61) being added to must not
        # poison the new average.
        avg = _weighted_abs_entry_avg(-1, -1.61, -1, -1.55)
        self.assertAlmostEqual(avg, 1.58, places=6)

    def test_unequal_quantities_weighting(self):
        # 2 @ 1.00 + 1 @ 1.60 → (2.00 + 1.60) / 3
        avg = _weighted_abs_entry_avg(-2, 1.00, -1, -1.60)
        self.assertAlmostEqual(avg, 1.20, places=6)

    def test_zero_denominator_returns_prior(self):
        self.assertEqual(_weighted_abs_entry_avg(0, 1.61, 0, -1.55), 1.61)


class TestWriteSitesRouted(unittest.TestCase):
    """Every position-write seam routes premiums through the helpers — the
    raw-signed assignments may not return (the 06-11 write-side bug)."""

    def test_commit_fill_sites(self):
        src = inspect.getsource(pe._commit_fill)
        self.assertIn("max_credit = _abs_entry_premium(this_fill_price)", src)
        self.assertIn('"avg_entry_price": _abs_entry_premium(this_fill_price)', src)
        self.assertIn("_weighted_abs_entry_avg(", src)
        # flip case
        self.assertIn("new_avg = _abs_entry_premium(this_fill_price)", src)
        # the raw assignments must be gone
        self.assertNotIn("max_credit = this_fill_price", src)
        self.assertNotIn('"avg_entry_price": this_fill_price', src)

    def test_repair_commit_sites(self):
        src = inspect.getsource(pe._repair_filled_order_commit)
        self.assertIn("max_credit = _abs_entry_premium(avg_fill_price)", src)
        self.assertIn('"avg_entry_price": _abs_entry_premium(avg_fill_price)', src)
        self.assertIn("_weighted_abs_entry_avg(", src)
        self.assertIn("new_avg = _abs_entry_premium(avg_fill_price)", src)
        self.assertNotIn("max_credit = avg_fill_price", src)
        self.assertNotIn('"avg_entry_price": avg_fill_price', src)


class TestRoundTripTodaysNumbers(unittest.TestCase):
    """The 06-11 QQQ condor, end to end, with the broker's actual numbers:
    filled_avg_price −1.61 (credit), 16:45Z verified mark −1.505 and
    unrealized +$10.50."""

    FILL = -1.61            # broker signed fill
    CURRENT_VALUE = -150.5  # signed leg-summed value at the 16:45Z mark

    def test_hold_unrealized_is_correct(self):
        entry = _abs_entry_premium(self.FILL)
        self.assertEqual(entry, 1.61)
        per_mark, unrealized = finalize_mark(
            quantity=-1, avg_entry_price=entry, current_value=self.CURRENT_VALUE
        )
        self.assertAlmostEqual(per_mark, -1.505, places=6)
        self.assertAlmostEqual(unrealized, 10.50, places=6)

    def test_incident_reproduction_raw_signed_entry(self):
        """What the pre-fix write produced: the documented phantom. This is
        the assertion that did not exist on 06-10 — keep it as the record of
        WHY the abs() seam is load-bearing."""
        _, unrealized = finalize_mark(
            quantity=-1, avg_entry_price=self.FILL, current_value=self.CURRENT_VALUE
        )
        self.assertAlmostEqual(unrealized, -311.50, places=6)  # vs true +10.50

    def test_realized_at_close_matches_hold_pnl(self):
        """Coherence: closing at the same structure value must realize the
        same P&L the hold showed (+$10.50). compute_realized_pl consumes the
        stored entry (close path at paper_endpoints _commit_fill close
        branch) — positive entry, spread_type='credit' (qty<0)."""
        close_legs = [  # buy-to-close shorts, sell-to-close longs; net debit 1.505
            {"action": "buy", "filled_qty": 1, "filled_avg_price": 6.00},
            {"action": "sell", "filled_qty": 1, "filled_avg_price": 5.50},
            {"action": "buy", "filled_qty": 1, "filled_avg_price": 5.00},
            {"action": "sell", "filled_qty": 1, "filled_avg_price": 3.995},
        ]
        realized = compute_realized_pl(
            close_legs=close_legs,
            entry_price=Decimal("1.61"),  # the ABS stored entry
            qty=1,
            spread_type="credit",
        )
        self.assertEqual(realized, Decimal("10.50"))

    def test_debit_round_trip_nflx_numbers(self):
        """The live NFLX debit spread (entry 3.65, 16:45Z mark 4.10 →
        unrealized +$45) — the debit side must be undamaged by the fix."""
        entry = _abs_entry_premium(3.65)
        per_mark, unrealized = finalize_mark(
            quantity=1, avg_entry_price=entry, current_value=410.0
        )
        self.assertAlmostEqual(per_mark, 4.10, places=6)
        self.assertAlmostEqual(unrealized, 45.0, places=6)
        realized = compute_realized_pl(
            close_legs=[
                {"action": "sell", "filled_qty": 1, "filled_avg_price": 5.85},
                {"action": "buy", "filled_qty": 1, "filled_avg_price": 1.75},
            ],
            entry_price=Decimal("3.65"),
            qty=1,
            spread_type="debit",
        )
        self.assertEqual(realized, Decimal("45.00"))


if __name__ == "__main__":
    unittest.main()
