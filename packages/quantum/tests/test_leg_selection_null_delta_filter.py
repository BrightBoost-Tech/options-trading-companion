"""Regression: null-delta contract filtering in _select_legs_from_chain.

The bug (PR #656, 2026-02-05 -> 2026-06-01): `has_delta` was read from
candidates[0] (the deepest-ITM/OTM strike). Providers (Alpaca AND Polygon,
verified) omit greeks on illiquid deep strikes, so candidates[0] had null delta
-> has_delta=False universe-wide -> the 3-bucket moneyness fallback
(spot x {0.95,1.0,1.05}) -> credit/put verticals collapsed to SAME strike
(width=0), which produced the 200%/spread_too_wide artifact (~50-65% of
spread-calc rejections daily for ~4 months).

The validated fix (shadow scan, 24/24 cells): FILTER null-delta contracts before
selection. This self-corrects the has_delta detection AND removes the
`_delta(x) or 0 = 0` contaminants that broke the bisect's strike<->delta
monotonicity. On full-greeks chains the filter is a no-op (zero regression).

These fixtures mirror the proven partial-greeks shape: deep strikes with null
delta + near-the-money strikes with valid delta.
"""
import unittest

from packages.quantum.options_scanner import (
    _select_legs_from_chain,
    _chain_has_any_delta,
    _get_delta_nested,
)

CP = 100.0  # underlying

# strategy leg_defs (deltas mirror strategy_selector.py; values are the contract)
CREDIT_CALL = [{"side": "sell", "type": "call", "delta_target": 0.30},
               {"side": "buy",  "type": "call", "delta_target": 0.15}]
CREDIT_PUT  = [{"side": "sell", "type": "put",  "delta_target": -0.30},
               {"side": "buy",  "type": "put",  "delta_target": -0.15}]
PUT_DEBIT   = [{"side": "buy",  "type": "put",  "delta_target": -0.60},
               {"side": "sell", "type": "put",  "delta_target": -0.30}]
CALL_DEBIT  = [{"side": "buy",  "type": "call", "delta_target": 0.60},
               {"side": "sell", "type": "call", "delta_target": 0.30}]


def _c(strike, right, delta, bid, ask, expiry="2026-07-17"):
    """One nested-schema contract. delta=None => provider omitted greeks."""
    return {"contract": f"O:X{int(strike)}{right[0].upper()}",
            "strike": float(strike), "expiry": expiry, "right": right,
            "quote": {"bid": bid, "ask": ask, "mid": (bid + ask) / 2.0, "last": (bid + ask) / 2.0},
            "greeks": {"delta": delta}}


# Calls sorted by strike asc; deepest two (50,60) have NULL delta (the trigger),
# near-the-money strikes carry valid greeks.
PARTIAL_CALLS = sorted([
    _c(50, "call", None, 50.1, 50.6),   # candidates[0] -> null delta (deep ITM)
    _c(60, "call", None, 40.1, 40.6),
    _c(95,  "call", 0.65, 7.0, 7.3),
    _c(100, "call", 0.50, 4.0, 4.3),
    _c(105, "call", 0.35, 2.2, 2.5),
    _c(110, "call", 0.25, 1.1, 1.4),
    _c(115, "call", 0.15, 0.5, 0.8),
    _c(120, "call", 0.08, 0.2, 0.5),
], key=lambda x: x["strike"])

PARTIAL_PUTS = sorted([
    _c(50, "put", None, 0.01, 0.05),    # candidates[0] -> null delta (deep OTM)
    _c(60, "put", None, 0.02, 0.06),
    _c(80,  "put", -0.10, 0.4, 0.7),
    _c(85,  "put", -0.15, 0.6, 0.9),
    _c(90,  "put", -0.25, 1.1, 1.4),
    _c(95,  "put", -0.35, 2.0, 2.3),
    _c(100, "put", -0.50, 3.8, 4.1),
    _c(105, "put", -0.65, 6.5, 6.8),
], key=lambda x: x["strike"])

# Healthy chain: every contract has greeks (filter must be a no-op here).
FULL_CALLS = sorted([c for c in PARTIAL_CALLS if _get_delta_nested(c) is not None]
                    + [_c(90, "call", 0.78, 11.0, 11.4)], key=lambda x: x["strike"])
FULL_PUTS = sorted([c for c in PARTIAL_PUTS if _get_delta_nested(c) is not None]
                   + [_c(110, "put", -0.78, 10.5, 10.9)], key=lambda x: x["strike"])

# Genuinely greeks-less chain (total outage): NO delta anywhere.
EMPTY_CALLS = [_c(s, "call", None, 1.0, 1.3) for s in (95, 100, 105, 110)]
EMPTY_PUTS = [_c(s, "put", None, 1.0, 1.3) for s in (90, 95, 100, 105)]


def _strikes(legs):
    return sorted(l["strike"] for l in legs)


class TestTriggerCondition(unittest.TestCase):
    def test_candidates0_is_null_delta(self):
        # The fixture genuinely reproduces the bug condition: the deepest strike
        # (candidates[0]) lacks delta while ATM strikes have it.
        self.assertIsNone(_get_delta_nested(PARTIAL_CALLS[0]))
        self.assertIsNone(_get_delta_nested(PARTIAL_PUTS[0]))
        self.assertTrue(any(_get_delta_nested(c) is not None for c in PARTIAL_CALLS))
        self.assertTrue(any(_get_delta_nested(c) is not None for c in PARTIAL_PUTS))


class TestNoSameStrikeCollapse(unittest.TestCase):
    """The exact bug: credit/put verticals collapsed to a single strike."""

    def _assert_distinct(self, leg_defs, msg):
        legs, _ = _select_legs_from_chain(PARTIAL_CALLS, PARTIAL_PUTS, leg_defs, CP)
        self.assertEqual(len(legs), 2, msg)
        s = _strikes(legs)
        self.assertNotEqual(s[0], s[1], f"{msg}: legs collapsed to same strike {s}")

    def test_credit_call_distinct(self):
        self._assert_distinct(CREDIT_CALL, "credit_call")

    def test_credit_put_distinct(self):
        self._assert_distinct(CREDIT_PUT, "credit_put")

    def test_put_debit_distinct(self):
        self._assert_distinct(PUT_DEBIT, "put_debit")

    def test_call_debit_distinct(self):
        # Guards against the one-line-revert regression that collapsed call_debit.
        self._assert_distinct(CALL_DEBIT, "call_debit")


class TestDeltaTargeting(unittest.TestCase):
    """Legs land near the strategy delta targets, NOT at spot x +/-5% moneyness."""

    def _deltas_for(self, leg_defs):
        legs, _ = _select_legs_from_chain(PARTIAL_CALLS, PARTIAL_PUTS, leg_defs, CP)
        by_side = {l["side"]: l for l in legs}
        return by_side

    def test_credit_call_deltas_near_targets(self):
        bs = self._deltas_for(CREDIT_CALL)
        self.assertAlmostEqual(abs(bs["sell"]["delta"]), 0.30, delta=0.10)
        self.assertAlmostEqual(abs(bs["buy"]["delta"]), 0.15, delta=0.10)

    def test_credit_put_deltas_near_targets(self):
        bs = self._deltas_for(CREDIT_PUT)
        self.assertAlmostEqual(abs(bs["sell"]["delta"]), 0.30, delta=0.10)
        self.assertAlmostEqual(abs(bs["buy"]["delta"]), 0.15, delta=0.10)

    def test_debit_longs_deltas_near_targets(self):
        for ld in (PUT_DEBIT, CALL_DEBIT):
            bs = self._deltas_for(ld)
            self.assertAlmostEqual(abs(bs["buy"]["delta"]), 0.60, delta=0.12)
            self.assertAlmostEqual(abs(bs["sell"]["delta"]), 0.30, delta=0.12)

    def test_strikes_not_at_moneyness(self):
        # Moneyness fallback would put BOTH credit-call legs at ~spot*1.05 = 105.
        legs, _ = _select_legs_from_chain(PARTIAL_CALLS, PARTIAL_PUTS, CREDIT_CALL, CP)
        s = _strikes(legs)
        self.assertNotEqual(s, [105.0, 105.0])


class TestNoOpOnHealthyChain(unittest.TestCase):
    """On a full-greeks chain the filter removes nothing -> selection unchanged."""

    def test_full_greeks_selects_delta_targeted_distinct(self):
        for ld in (CREDIT_CALL, CREDIT_PUT, PUT_DEBIT, CALL_DEBIT):
            legs, _ = _select_legs_from_chain(FULL_CALLS, FULL_PUTS, ld, CP)
            self.assertEqual(len(legs), 2)
            s = _strikes(legs)
            self.assertNotEqual(s[0], s[1])

    def test_filter_noop_identical_selection(self):
        # Pre-filter list (all have delta) == post-filter list, so the selected
        # legs are identical whether or not the filter ran.
        legs, _ = _select_legs_from_chain(FULL_CALLS, FULL_PUTS, CREDIT_CALL, CP)
        manual = [c for c in FULL_CALLS if _get_delta_nested(c) is not None]
        legs2, _ = _select_legs_from_chain(manual, FULL_PUTS, CREDIT_CALL, CP)
        self.assertEqual(_strikes(legs), _strikes(legs2))


class TestLoudGuardScope(unittest.TestCase):
    """_chain_has_any_delta: True on partial (no loud), False on total outage."""

    def test_partial_greeks_has_delta_true(self):
        # COMMON case: the loud guard must NOT fire on partial greeks.
        self.assertTrue(_chain_has_any_delta(PARTIAL_CALLS, PARTIAL_PUTS))

    def test_genuinely_empty_has_delta_false(self):
        # RARE total outage: the loud guard fires (no_deltas_in_chain).
        self.assertFalse(_chain_has_any_delta(EMPTY_CALLS, EMPTY_PUTS))

    def test_flat_schema_supported(self):
        flat = [{"strike": 100.0, "delta": 0.5, "right": "call"}]
        self.assertTrue(_chain_has_any_delta(flat, []))
        flat_null = [{"strike": 100.0, "delta": None, "right": "call"}]
        self.assertFalse(_chain_has_any_delta(flat_null, []))


if __name__ == "__main__":
    unittest.main()
