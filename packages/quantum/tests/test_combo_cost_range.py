"""
Tests for combo cost range calculation from legs.

Verifies:
1. _combo_cost_range_from_legs computes correct cost_min, cost_max, combo_spread_share
2. _sum_leg_spreads_share computes correct sum of per-leg spreads
3. Edge cases: invalid NBBO, missing fields, empty legs
4. Iron condor example matches expected values
"""

import pytest
from typing import Dict, Any, List, Optional


def _combo_cost_range_from_legs(legs: List[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    """
    Compute combo cost range from leg bid/ask values.

    For a multi-leg trade:
    - cost_min = Σ(buy_bid) - Σ(sell_ask)  # Best case: buy at bid, sell at ask
    - cost_max = Σ(buy_ask) - Σ(sell_bid)  # Worst case: buy at ask, sell at bid
    - combo_spread_share = cost_max - cost_min

    Returns dict with cost_min, cost_max, combo_spread_share or None if any leg
    has invalid NBBO.
    """
    if not legs:
        return None

    buy_bid_sum = 0.0
    buy_ask_sum = 0.0
    sell_bid_sum = 0.0
    sell_ask_sum = 0.0

    for leg in legs:
        bid = leg.get("bid")
        ask = leg.get("ask")
        side = leg.get("side", "").lower()

        # Validate NBBO
        if bid is None or ask is None:
            return None
        try:
            bid = float(bid)
            ask = float(ask)
        except (TypeError, ValueError):
            return None

        if bid <= 0 or ask < bid:
            return None

        if side == "buy":
            buy_bid_sum += bid
            buy_ask_sum += ask
        elif side == "sell":
            sell_bid_sum += bid
            sell_ask_sum += ask
        else:
            # Unknown side, cannot determine direction
            return None

    # cost_min: buy at bid (favorable), sell at ask (favorable)
    cost_min = buy_bid_sum - sell_ask_sum
    # cost_max: buy at ask (unfavorable), sell at bid (unfavorable)
    cost_max = buy_ask_sum - sell_bid_sum
    # combo spread is the range between best and worst case
    combo_spread_share = cost_max - cost_min

    return {
        "cost_min": cost_min,
        "cost_max": cost_max,
        "combo_spread_share": combo_spread_share,
    }


def _sum_leg_spreads_share(legs: List[Dict[str, Any]]) -> Optional[float]:
    """
    Sum of (ask - bid) for each leg (debugging/comparison helper).

    Returns the sum of per-leg spreads, or None if any leg has invalid NBBO.
    """
    if not legs:
        return None

    total = 0.0
    for leg in legs:
        bid = leg.get("bid")
        ask = leg.get("ask")

        if bid is None or ask is None:
            return None
        try:
            bid = float(bid)
            ask = float(ask)
        except (TypeError, ValueError):
            return None

        if bid <= 0 or ask < bid:
            return None

        total += (ask - bid)

    return total


class TestComboCostRangeFromLegs:
    """Tests for _combo_cost_range_from_legs helper."""

    def test_iron_condor_credit_spread(self):
        """Iron condor: 2 sells (short), 2 buys (long wings)."""
        # Example iron condor:
        # Sell put @ strike 95: bid=1.00, ask=1.10 (credit)
        # Buy put @ strike 90: bid=0.40, ask=0.50 (debit)
        # Sell call @ strike 105: bid=0.90, ask=1.00 (credit)
        # Buy call @ strike 110: bid=0.30, ask=0.40 (debit)
        legs = [
            {"strike": 95, "type": "put", "side": "sell", "bid": 1.00, "ask": 1.10},
            {"strike": 90, "type": "put", "side": "buy", "bid": 0.40, "ask": 0.50},
            {"strike": 105, "type": "call", "side": "sell", "bid": 0.90, "ask": 1.00},
            {"strike": 110, "type": "call", "side": "buy", "bid": 0.30, "ask": 0.40},
        ]

        result = _combo_cost_range_from_legs(legs)
        assert result is not None

        # cost_min = Σ(buy_bid) - Σ(sell_ask)
        # buy_bid = 0.40 + 0.30 = 0.70
        # sell_ask = 1.10 + 1.00 = 2.10
        # cost_min = 0.70 - 2.10 = -1.40 (credit received: best case)
        expected_cost_min = 0.70 - 2.10  # -1.40

        # cost_max = Σ(buy_ask) - Σ(sell_bid)
        # buy_ask = 0.50 + 0.40 = 0.90
        # sell_bid = 1.00 + 0.90 = 1.90
        # cost_max = 0.90 - 1.90 = -1.00 (credit received: worst case)
        expected_cost_max = 0.90 - 1.90  # -1.00

        # combo_spread = cost_max - cost_min = -1.00 - (-1.40) = 0.40
        expected_spread = expected_cost_max - expected_cost_min  # 0.40

        assert abs(result["cost_min"] - expected_cost_min) < 1e-9
        assert abs(result["cost_max"] - expected_cost_max) < 1e-9
        assert abs(result["combo_spread_share"] - expected_spread) < 1e-9

    def test_vertical_debit_spread(self):
        """Vertical debit spread: buy lower strike, sell higher strike."""
        # Bull call spread:
        # Buy call @ 100: bid=2.00, ask=2.20
        # Sell call @ 105: bid=0.80, ask=1.00
        legs = [
            {"strike": 100, "type": "call", "side": "buy", "bid": 2.00, "ask": 2.20},
            {"strike": 105, "type": "call", "side": "sell", "bid": 0.80, "ask": 1.00},
        ]

        result = _combo_cost_range_from_legs(legs)
        assert result is not None

        # cost_min = buy_bid - sell_ask = 2.00 - 1.00 = 1.00 (debit)
        # cost_max = buy_ask - sell_bid = 2.20 - 0.80 = 1.40 (debit)
        # spread = 1.40 - 1.00 = 0.40

        assert abs(result["cost_min"] - 1.00) < 1e-9
        assert abs(result["cost_max"] - 1.40) < 1e-9
        assert abs(result["combo_spread_share"] - 0.40) < 1e-9

    def test_single_buy_leg(self):
        """Single buy leg (long call/put)."""
        legs = [
            {"strike": 100, "type": "call", "side": "buy", "bid": 1.50, "ask": 1.60},
        ]

        result = _combo_cost_range_from_legs(legs)
        assert result is not None

        # cost_min = buy_bid - 0 = 1.50
        # cost_max = buy_ask - 0 = 1.60
        # spread = 0.10
        assert abs(result["cost_min"] - 1.50) < 1e-9
        assert abs(result["cost_max"] - 1.60) < 1e-9
        assert abs(result["combo_spread_share"] - 0.10) < 1e-9

    def test_single_sell_leg(self):
        """Single sell leg (short call/put, naked)."""
        legs = [
            {"strike": 100, "type": "put", "side": "sell", "bid": 0.80, "ask": 0.90},
        ]

        result = _combo_cost_range_from_legs(legs)
        assert result is not None

        # cost_min = 0 - sell_ask = -0.90 (credit)
        # cost_max = 0 - sell_bid = -0.80 (credit)
        # spread = -0.80 - (-0.90) = 0.10
        assert abs(result["cost_min"] - (-0.90)) < 1e-9
        assert abs(result["cost_max"] - (-0.80)) < 1e-9
        assert abs(result["combo_spread_share"] - 0.10) < 1e-9


class TestComboCostRangeEdgeCases:
    """Edge case tests for _combo_cost_range_from_legs."""

    def test_empty_legs_returns_none(self):
        """Empty legs list should return None."""
        assert _combo_cost_range_from_legs([]) is None

    def test_missing_bid_returns_none(self):
        """Missing bid should return None."""
        legs = [{"strike": 100, "side": "buy", "ask": 1.50}]
        assert _combo_cost_range_from_legs(legs) is None

    def test_missing_ask_returns_none(self):
        """Missing ask should return None."""
        legs = [{"strike": 100, "side": "buy", "bid": 1.50}]
        assert _combo_cost_range_from_legs(legs) is None

    def test_none_bid_returns_none(self):
        """None bid should return None."""
        legs = [{"strike": 100, "side": "buy", "bid": None, "ask": 1.50}]
        assert _combo_cost_range_from_legs(legs) is None

    def test_none_ask_returns_none(self):
        """None ask should return None."""
        legs = [{"strike": 100, "side": "buy", "bid": 1.50, "ask": None}]
        assert _combo_cost_range_from_legs(legs) is None

    def test_zero_bid_returns_none(self):
        """Zero bid (one-sided quote) should return None."""
        legs = [{"strike": 100, "side": "buy", "bid": 0, "ask": 1.50}]
        assert _combo_cost_range_from_legs(legs) is None

    def test_crossed_nbbo_returns_none(self):
        """Crossed NBBO (ask < bid) should return None."""
        legs = [{"strike": 100, "side": "buy", "bid": 1.50, "ask": 1.40}]
        assert _combo_cost_range_from_legs(legs) is None

    def test_missing_side_returns_none(self):
        """Missing side field should return None."""
        legs = [{"strike": 100, "bid": 1.50, "ask": 1.60}]
        assert _combo_cost_range_from_legs(legs) is None

    def test_unknown_side_returns_none(self):
        """Unknown side value should return None."""
        legs = [{"strike": 100, "side": "hold", "bid": 1.50, "ask": 1.60}]
        assert _combo_cost_range_from_legs(legs) is None

    def test_invalid_bid_type_returns_none(self):
        """Non-numeric bid should return None."""
        legs = [{"strike": 100, "side": "buy", "bid": "bad", "ask": 1.50}]
        assert _combo_cost_range_from_legs(legs) is None

    def test_invalid_ask_type_returns_none(self):
        """Non-numeric ask should return None."""
        legs = [{"strike": 100, "side": "buy", "bid": 1.50, "ask": "bad"}]
        assert _combo_cost_range_from_legs(legs) is None

    def test_one_bad_leg_fails_all(self):
        """One leg with invalid NBBO should fail entire calculation."""
        legs = [
            {"strike": 100, "side": "buy", "bid": 1.50, "ask": 1.60},
            {"strike": 105, "side": "sell", "bid": None, "ask": 0.90},  # Invalid
        ]
        assert _combo_cost_range_from_legs(legs) is None

    def test_string_numeric_bid_ask_works(self):
        """String-encoded numbers should be parsed correctly."""
        legs = [
            {"strike": 100, "side": "buy", "bid": "1.50", "ask": "1.60"},
        ]
        result = _combo_cost_range_from_legs(legs)
        assert result is not None
        assert abs(result["combo_spread_share"] - 0.10) < 1e-9

    def test_case_insensitive_side(self):
        """Side should be case-insensitive."""
        legs = [
            {"strike": 100, "side": "BUY", "bid": 1.50, "ask": 1.60},
            {"strike": 105, "side": "SELL", "bid": 0.80, "ask": 0.90},
        ]
        result = _combo_cost_range_from_legs(legs)
        assert result is not None


class TestSumLegSpreadsShare:
    """Tests for _sum_leg_spreads_share helper."""

    def test_iron_condor_sum_spreads(self):
        """Sum of spreads for iron condor legs."""
        legs = [
            {"bid": 1.00, "ask": 1.10},  # spread = 0.10
            {"bid": 0.40, "ask": 0.50},  # spread = 0.10
            {"bid": 0.90, "ask": 1.00},  # spread = 0.10
            {"bid": 0.30, "ask": 0.40},  # spread = 0.10
        ]
        result = _sum_leg_spreads_share(legs)
        assert result is not None
        assert abs(result - 0.40) < 1e-9

    def test_single_leg_spread(self):
        """Single leg spread."""
        legs = [{"bid": 2.00, "ask": 2.30}]
        result = _sum_leg_spreads_share(legs)
        assert result is not None
        assert abs(result - 0.30) < 1e-9

    def test_empty_legs_returns_none(self):
        """Empty legs should return None."""
        assert _sum_leg_spreads_share([]) is None

    def test_missing_bid_returns_none(self):
        """Missing bid should return None."""
        legs = [{"ask": 1.50}]
        assert _sum_leg_spreads_share(legs) is None

    def test_missing_ask_returns_none(self):
        """Missing ask should return None."""
        legs = [{"bid": 1.50}]
        assert _sum_leg_spreads_share(legs) is None

    def test_zero_bid_returns_none(self):
        """Zero bid should return None."""
        legs = [{"bid": 0, "ask": 1.50}]
        assert _sum_leg_spreads_share(legs) is None

    def test_crossed_nbbo_returns_none(self):
        """Crossed NBBO should return None."""
        legs = [{"bid": 1.50, "ask": 1.40}]
        assert _sum_leg_spreads_share(legs) is None

    def test_tight_spreads(self):
        """Very tight spreads (penny-wide)."""
        legs = [
            {"bid": 5.00, "ask": 5.01},
            {"bid": 3.00, "ask": 3.01},
        ]
        result = _sum_leg_spreads_share(legs)
        assert result is not None
        assert abs(result - 0.02) < 1e-9

    def test_wide_spreads(self):
        """Wide spreads."""
        legs = [
            {"bid": 1.00, "ask": 1.50},  # spread = 0.50
            {"bid": 0.50, "ask": 1.00},  # spread = 0.50
        ]
        result = _sum_leg_spreads_share(legs)
        assert result is not None
        assert abs(result - 1.00) < 1e-9


class TestComboCostRangeVsSumLegs:
    """Compare combo_spread_share with sum_leg_spreads."""

    def test_combo_spread_equals_sum_leg_spreads(self):
        """
        For any trade, combo_spread_share should equal sum of per-leg spreads.

        Proof:
        combo_spread = cost_max - cost_min
                     = (buy_ask_sum - sell_bid_sum) - (buy_bid_sum - sell_ask_sum)
                     = buy_ask_sum - sell_bid_sum - buy_bid_sum + sell_ask_sum
                     = (buy_ask_sum - buy_bid_sum) + (sell_ask_sum - sell_bid_sum)
                     = Σ(buy_spread) + Σ(sell_spread)
                     = Σ(all_spreads)
        """
        # Iron condor
        legs = [
            {"strike": 95, "side": "sell", "bid": 1.00, "ask": 1.10},
            {"strike": 90, "side": "buy", "bid": 0.40, "ask": 0.50},
            {"strike": 105, "side": "sell", "bid": 0.90, "ask": 1.00},
            {"strike": 110, "side": "buy", "bid": 0.30, "ask": 0.40},
        ]

        cost_range = _combo_cost_range_from_legs(legs)
        sum_spreads = _sum_leg_spreads_share(legs)

        assert cost_range is not None
        assert sum_spreads is not None
        assert abs(cost_range["combo_spread_share"] - sum_spreads) < 1e-9

    def test_vertical_spread_equivalence(self):
        """Vertical spread: combo_spread should equal sum of leg spreads."""
        legs = [
            {"strike": 100, "side": "buy", "bid": 2.00, "ask": 2.20},
            {"strike": 105, "side": "sell", "bid": 0.80, "ask": 1.00},
        ]

        cost_range = _combo_cost_range_from_legs(legs)
        sum_spreads = _sum_leg_spreads_share(legs)

        assert cost_range is not None
        assert sum_spreads is not None
        # combo_spread = 0.40, sum = (0.20 + 0.20) = 0.40
        assert abs(cost_range["combo_spread_share"] - sum_spreads) < 1e-9


class TestExecutionCostDiagnostics:
    """Tests verifying diagnostics structure for execution_cost_exceeds_ev samples."""

    def test_diagnostic_fields_present(self):
        """Verify expected diagnostic fields are computed."""
        legs = [
            {"strike": 95, "side": "sell", "bid": 1.00, "ask": 1.10},
            {"strike": 90, "side": "buy", "bid": 0.40, "ask": 0.50},
            {"strike": 105, "side": "sell", "bid": 0.90, "ask": 1.00},
            {"strike": 110, "side": "buy", "bid": 0.30, "ask": 0.40},
        ]

        cost_range = _combo_cost_range_from_legs(legs)
        sum_spreads = _sum_leg_spreads_share(legs)

        # Simulate what would be logged in execution_cost_exceeds_ev sample
        diagnostic = {
            "combo_spread_share": round(cost_range["combo_spread_share"], 4),
            "combo_cost_min_share": round(cost_range["cost_min"], 4),
            "combo_cost_max_share": round(cost_range["cost_max"], 4),
            "sum_leg_spreads_share": round(sum_spreads, 4),
        }

        assert "combo_spread_share" in diagnostic
        assert "combo_cost_min_share" in diagnostic
        assert "combo_cost_max_share" in diagnostic
        assert "sum_leg_spreads_share" in diagnostic

        # Values should be reasonable
        assert diagnostic["combo_spread_share"] == 0.40
        assert diagnostic["combo_cost_min_share"] == -1.40
        assert diagnostic["combo_cost_max_share"] == -1.00
        assert diagnostic["sum_leg_spreads_share"] == 0.40


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
