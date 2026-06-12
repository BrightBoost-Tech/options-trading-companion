"""Internal/shadow fills price at the EXECUTABLE side, not the optimistic
mid (#1017 class, 06-12).

The worked fixture is the real 2026-06-12 15:15:04Z NFLX x3 conservative-
shadow close: triggering mid 4.7355 booked realized +$314.70 while its own
corroboration row measured the achievable close at 4.131 (P86 long → sell at
bid 6.14; P79 short → buy at ask 2.009) → +$133.35. The $181.35 delta was
fiction headed into learning (corrected in-DB that night; this module makes
the class impossible).

Pins:
1. The NFLX fixture: _select_internal_fill_price returns the achievable
   4.131 / quality 'executable'; realized math lands +133.35 not +314.70.
2. Degenerate executable side (short leg ask missing) → all-or-nothing →
   mid fallback, quality 'mid_fallback_quote_missing' — flagged, never
   silently optimistic.
3. Quote-fetch failure → mid fallback, quality 'mid_fallback_error'; the
   function NEVER raises (a pricing bug can never abort a close).
4. One-sided-but-executable (a long leg missing only its ask) → still the
   honest executable price, flagged 'executable_partial_quote'.
5. Source pins: the internal-fill block selects the price BEFORE the fill
   update, and persists fill_quality + fill_mid_reference on the order row
   and in the ledger metadata.
"""

import os
import sys
import types
import unittest

# Stub alpaca-py so transitive imports resolve in the test venv.
sys.modules.setdefault("alpaca", types.ModuleType("alpaca"))
sys.modules.setdefault("alpaca.trading", types.ModuleType("alpaca.trading"))
sys.modules.setdefault("alpaca.trading.requests", types.ModuleType("alpaca.trading.requests"))

from packages.quantum.analytics import exit_mark_corroboration as emc  # noqa: E402
from packages.quantum.services.paper_exit_evaluator import (  # noqa: E402
    _select_internal_fill_price,
)


# ── The real 06-12 15:15:04Z fixture (corroboration row, position 1e2dd73f) ─

def _nflx_x3_position():
    return {
        "id": "1e2dd73f", "symbol": "NFLX",
        "quantity": 3.0, "avg_entry_price": 3.6865,
        "legs": [
            {"symbol": "O:NFLX260710P00086000", "action": "buy",
             "strike": 86.0, "quantity": 3},
            {"symbol": "O:NFLX260710P00079000", "action": "sell",
             "strike": 79.0, "quantity": 3},
        ],
    }


_QUOTES_1515Z = {
    "O:NFLX260710P00086000": {"bid": 6.14, "ask": 7.23, "last": 6.64},
    "O:NFLX260710P00079000": {"bid": 1.89, "ask": 2.009, "last": 2.10},
}

_TRIGGERING_MID = 4.7355  # what the old code booked: (4.7355-3.6865)*300 = +314.70


def _snap(quote_map):
    def fn(occs):
        return {occ: {"quote": quote_map.get(occ, {})} for occ in occs}
    return fn


class TestNflxFixture(unittest.TestCase):
    def test_fills_at_achievable_not_mid(self):
        price, quality = _select_internal_fill_price(
            _nflx_x3_position(), _TRIGGERING_MID, snapshot_fn=_snap(_QUOTES_1515Z),
        )
        self.assertEqual(quality, "executable")
        self.assertAlmostEqual(price, 4.131, places=3)  # 6.14 bid − 2.009 ask

    def test_realized_math_lands_honest(self):
        price, _ = _select_internal_fill_price(
            _nflx_x3_position(), _TRIGGERING_MID, snapshot_fn=_snap(_QUOTES_1515Z),
        )
        realized = round((price - 3.6865) * 3 * 100, 2)
        self.assertAlmostEqual(realized, 133.35, places=2)
        # And the mid would have fabricated +314.70:
        self.assertAlmostEqual((_TRIGGERING_MID - 3.6865) * 300, 314.70, places=2)

    def test_estimate_matches_corroboration_row(self):
        est = emc.executable_close_estimate(
            _nflx_x3_position(), snapshot_fn=_snap(_QUOTES_1515Z),
        )
        self.assertAlmostEqual(est["achievable_close"], 4.131, places=3)
        self.assertAlmostEqual(est["achievable_implied_pl"], 133.35, places=1)
        self.assertTrue(est["quote_complete"])


class TestFallbacks(unittest.TestCase):
    def test_degenerate_executable_side_falls_back_to_mid_flagged(self):
        """Short leg's ask (its executable side) missing → all-or-nothing →
        mid fallback with the explicit flag. Never a partial fabrication."""
        quotes = {
            "O:NFLX260710P00086000": {"bid": 6.14, "ask": 7.23, "last": None},
            "O:NFLX260710P00079000": {"bid": 1.89, "ask": 0.0, "last": None},
        }
        price, quality = _select_internal_fill_price(
            _nflx_x3_position(), _TRIGGERING_MID, snapshot_fn=_snap(quotes),
        )
        self.assertEqual(quality, "mid_fallback_quote_missing")
        self.assertAlmostEqual(price, _TRIGGERING_MID, places=4)

    def test_fetch_failure_falls_back_to_mid_never_raises(self):
        def boom(occs):
            raise RuntimeError("snapshot down")
        price, quality = _select_internal_fill_price(
            _nflx_x3_position(), _TRIGGERING_MID, snapshot_fn=boom,
        )
        self.assertEqual(quality, "mid_fallback_error")
        self.assertAlmostEqual(price, _TRIGGERING_MID, places=4)

    def test_partial_quote_still_executable_but_flagged(self):
        """Long leg missing only its ASK (non-executable side): the bid-based
        close is still honest → price it, but flag for learning weighting."""
        quotes = {
            "O:NFLX260710P00086000": {"bid": 6.14, "ask": 0.0, "last": None},
            "O:NFLX260710P00079000": {"bid": 1.89, "ask": 2.009, "last": None},
        }
        price, quality = _select_internal_fill_price(
            _nflx_x3_position(), _TRIGGERING_MID, snapshot_fn=_snap(quotes),
        )
        self.assertEqual(quality, "executable_partial_quote")
        self.assertAlmostEqual(price, 4.131, places=3)


class TestFillBlockWiring(unittest.TestCase):
    """Source pins on _close_position's internal-fill block — the selection
    happens before the fill update and the flags persist to the order row
    and ledger metadata."""

    def _src(self):
        import inspect
        from packages.quantum.services.paper_exit_evaluator import PaperExitEvaluator
        return inspect.getsource(PaperExitEvaluator._close_position)

    def test_price_selected_before_fill_update(self):
        src = self._src()
        self.assertIn("_select_internal_fill_price(", src)
        self.assertLess(
            src.index("_select_internal_fill_price("),
            src.index('"avg_fill_price": round(exit_price, 2)'),
        )

    def test_quality_persisted_on_order_row_and_ledger(self):
        src = self._src()
        self.assertIn('_order_json["fill_quality"]', src)
        self.assertIn('_order_json["fill_mid_reference"]', src)
        self.assertIn('"fill_quality": _fill_quality', src)       # ledger metadata
        self.assertIn('"fill_mid_reference": _mid_reference', src)


if __name__ == "__main__":
    unittest.main()
