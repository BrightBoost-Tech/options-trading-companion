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

The former `TestFillBlockWiring` source-string pins (inspect.getsource
assertions on `_order_json["fill_quality"]` / the ledger emit) were REMOVED for
V17-1 A2 (2026-07-19, Lane 1B): they were the #1126 costume the doctrine warns
against — a string match that stays green while the route walks past. The
persistence now happens server-side inside rpc_commit_internal_close_v1, and the
route-level guarantee (fill_quality + fill_mid_reference reach the atomic commit;
the price is selected before the commit) is proven by driving the REAL
_close_position end-to-end in test_internal_close_route_atomic_switch.py and
test_credit_close_sign_contract.py.
"""

import os
import sys
import types
import unittest

# Stub alpaca-py so transitive imports resolve in the test venv.
from packages.quantum.tests._alpaca_stub import ensure_alpaca as _ensure_alpaca

_ensure_alpaca()

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


# NOTE (V17-1 A2, Lane 1B): TestFillBlockWiring was REMOVED here — see the module
# docstring. Its route-level intent is covered by driving the real _close_position
# in test_internal_close_route_atomic_switch.py (fill_quality + fill_mid_reference
# reach the atomic RPC; price selected before the commit) and
# test_credit_close_sign_contract.py (executable magnitude committed, not the mid).


if __name__ == "__main__":
    unittest.main()
