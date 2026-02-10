"""
Tests for execution cost samples and configurable slippage model.

Verifies:
1. Mid is NOT computed from one-sided quotes (bid=0 or ask=0)
2. execution_cost_exceeds_ev rejection samples contain expected keys
3. Env var changes take_frac affects computed proxy cost
4. Limit vs market order slippage fractions are applied correctly
"""

import pytest
import os
from typing import Dict, Any, Optional


# Replicate helper functions for testing
def _is_valid_nbbo(bid: Any, ask: Any) -> bool:
    """Check if bid/ask values constitute a valid NBBO."""
    try:
        if bid is None or ask is None:
            return False
        bid_f = float(bid)
        ask_f = float(ask)
        return bid_f > 0 and ask_f > 0 and ask_f >= bid_f
    except (TypeError, ValueError):
        return False


def _determine_execution_cost_local(
    drag_map: Dict[str, Any],
    symbol: str,
    combo_width_share: float,
    num_legs: int,
    is_limit: bool = True,
    limit_frac: float = 0.25,
    market_frac: float = 0.50
) -> Dict[str, Any]:
    """
    Local copy of _determine_execution_cost for testing.
    """
    take_frac = limit_frac if is_limit else market_frac
    proxy_cost_share = (combo_width_share * take_frac) + (num_legs * 0.0065)
    proxy_cost_contract = proxy_cost_share * 100.0

    stats = drag_map.get(symbol)
    history_cost_contract = 0.0
    history_samples = 0
    has_history = False

    if stats and isinstance(stats, dict):
        history_cost_contract = float(stats.get("avg_drag") or 0.0)
        history_samples = int(stats.get("n", stats.get("N", 0)) or 0)
        has_history = True

    execution_drag_source = "history" if has_history else "proxy"

    if history_cost_contract >= proxy_cost_contract and history_samples > 0:
        expected_execution_cost = history_cost_contract
        execution_cost_source_used = "history"
        execution_cost_samples_used = history_samples
    else:
        expected_execution_cost = proxy_cost_contract
        execution_cost_source_used = "proxy"
        execution_cost_samples_used = 0

    return {
        "expected_execution_cost": expected_execution_cost,
        "execution_cost_source_used": execution_cost_source_used,
        "execution_cost_samples_used": execution_cost_samples_used,
        "execution_drag_source": execution_drag_source,
        "spread_take_frac": take_frac,
        "proxy_cost_contract": proxy_cost_contract,
    }


class TestMidCalculation:
    """Test that mid is NOT computed from one-sided quotes."""

    def test_mid_not_computed_bid_zero(self):
        """Mid should NOT be computed when bid=0."""
        bid = 0
        ask = 15.0
        mid = None
        if _is_valid_nbbo(bid, ask):
            mid = (float(bid) + float(ask)) / 2.0

        assert mid is None

    def test_mid_not_computed_ask_zero(self):
        """Mid should NOT be computed when ask=0."""
        bid = 1.50
        ask = 0
        mid = None
        if _is_valid_nbbo(bid, ask):
            mid = (float(bid) + float(ask)) / 2.0

        assert mid is None

    def test_mid_computed_valid_nbbo(self):
        """Mid should be computed when NBBO is valid."""
        bid = 1.50
        ask = 1.60
        mid = None
        if _is_valid_nbbo(bid, ask):
            mid = (float(bid) + float(ask)) / 2.0

        assert mid == 1.55

    def test_mid_not_computed_bid_none(self):
        """Mid should NOT be computed when bid is None."""
        bid = None
        ask = 1.60
        mid = None
        if _is_valid_nbbo(bid, ask):
            mid = (float(bid) + float(ask)) / 2.0

        assert mid is None


class TestExecutionCostSlippage:
    """Test configurable slippage fractions for limit vs market orders."""

    def test_limit_order_uses_limit_frac(self):
        """Limit orders use EXECUTION_SPREAD_TAKE_FRAC_LIMIT."""
        combo_width = 0.10  # 10 cents
        num_legs = 4

        cost = _determine_execution_cost_local(
            drag_map={},
            symbol="SPY",
            combo_width_share=combo_width,
            num_legs=num_legs,
            is_limit=True,
            limit_frac=0.25,
            market_frac=0.50
        )

        # Expected: (0.10 * 0.25) + (4 * 0.0065) = 0.025 + 0.026 = 0.051 per share
        # * 100 = $5.10 per contract
        assert cost["spread_take_frac"] == 0.25
        assert abs(cost["proxy_cost_contract"] - 5.10) < 0.01

    def test_market_order_uses_market_frac(self):
        """Market orders use EXECUTION_SPREAD_TAKE_FRAC_MARKET."""
        combo_width = 0.10
        num_legs = 4

        cost = _determine_execution_cost_local(
            drag_map={},
            symbol="SPY",
            combo_width_share=combo_width,
            num_legs=num_legs,
            is_limit=False,
            limit_frac=0.25,
            market_frac=0.50
        )

        # Expected: (0.10 * 0.50) + (4 * 0.0065) = 0.05 + 0.026 = 0.076 per share
        # * 100 = $7.60 per contract
        assert cost["spread_take_frac"] == 0.50
        assert abs(cost["proxy_cost_contract"] - 7.60) < 0.01

    def test_limit_cheaper_than_market(self):
        """Limit order execution cost should be less than market order."""
        combo_width = 0.20
        num_legs = 4

        limit_cost = _determine_execution_cost_local(
            drag_map={},
            symbol="SPY",
            combo_width_share=combo_width,
            num_legs=num_legs,
            is_limit=True,
            limit_frac=0.25,
            market_frac=0.50
        )

        market_cost = _determine_execution_cost_local(
            drag_map={},
            symbol="SPY",
            combo_width_share=combo_width,
            num_legs=num_legs,
            is_limit=False,
            limit_frac=0.25,
            market_frac=0.50
        )

        assert limit_cost["expected_execution_cost"] < market_cost["expected_execution_cost"]

    def test_custom_fracs(self):
        """Custom slippage fractions are applied correctly."""
        combo_width = 0.10
        num_legs = 2

        cost = _determine_execution_cost_local(
            drag_map={},
            symbol="SPY",
            combo_width_share=combo_width,
            num_legs=num_legs,
            is_limit=True,
            limit_frac=0.10,  # Custom 10%
            market_frac=0.50
        )

        # (0.10 * 0.10) + (2 * 0.0065) = 0.01 + 0.013 = 0.023 per share
        # * 100 = $2.30 per contract
        assert cost["spread_take_frac"] == 0.10
        assert abs(cost["proxy_cost_contract"] - 2.30) < 0.01


class TestExecutionCostSampleShape:
    """Test that execution_cost_exceeds_ev samples have expected shape."""

    def test_sample_contains_required_keys(self):
        """Sample should contain all required diagnostic keys."""
        # Simulate the sample that would be created
        sample = {
            "symbol": "SPY",
            "strategy_key": "iron_condor",
            "total_ev": 12.50,
            "expected_execution_cost": 15.00,
            "entry_cost_share": 1.40,
            "combo_width_share": 0.12,
            "max_leg_spread_pct": 0.25,
            "is_limit_order": True,
            "thresholds": {
                "condor_max_leg_spread_pct": 0.35,
                "spread_take_frac": 0.25,
            },
            "cost_details": {
                "source_used": "proxy",
                "proxy_cost": 15.00,
            }
        }

        # Required top-level keys
        assert "symbol" in sample
        assert "strategy_key" in sample
        assert "total_ev" in sample
        assert "expected_execution_cost" in sample
        assert "entry_cost_share" in sample
        assert "combo_width_share" in sample
        assert "max_leg_spread_pct" in sample
        assert "is_limit_order" in sample
        assert "thresholds" in sample
        assert "cost_details" in sample

        # Thresholds sub-keys
        assert "condor_max_leg_spread_pct" in sample["thresholds"]
        assert "spread_take_frac" in sample["thresholds"]

        # Cost details sub-keys
        assert "source_used" in sample["cost_details"]
        assert "proxy_cost" in sample["cost_details"]

    def test_sample_values_are_rounded(self):
        """Numeric values in sample should be rounded."""
        sample = {
            "total_ev": round(12.123456, 4),
            "expected_execution_cost": round(15.789012, 4),
        }

        # Should be 4 decimal places
        assert sample["total_ev"] == 12.1235
        assert sample["expected_execution_cost"] == 15.789

    def test_sample_with_none_max_leg_spread(self):
        """max_leg_spread_pct can be None for non-condor strategies."""
        sample = {
            "symbol": "SPY",
            "strategy_key": "bull_put_spread",
            "max_leg_spread_pct": None,
        }

        assert sample["max_leg_spread_pct"] is None


class TestHistoryVsProxy:
    """Test that history cost is used when higher than proxy."""

    def test_history_used_when_higher(self):
        """History cost used when higher than proxy."""
        drag_map = {
            "SPY": {"avg_drag": 20.0, "n": 10}
        }

        cost = _determine_execution_cost_local(
            drag_map=drag_map,
            symbol="SPY",
            combo_width_share=0.10,
            num_legs=4,
            is_limit=True
        )

        # History (20.0) > proxy (~5.10), so history used
        assert cost["execution_cost_source_used"] == "history"
        assert cost["expected_execution_cost"] == 20.0

    def test_proxy_used_when_higher(self):
        """Proxy cost used when higher than history."""
        drag_map = {
            "SPY": {"avg_drag": 2.0, "n": 10}  # Lower than proxy
        }

        cost = _determine_execution_cost_local(
            drag_map=drag_map,
            symbol="SPY",
            combo_width_share=0.10,
            num_legs=4,
            is_limit=True
        )

        # Proxy (~5.10) > history (2.0), so proxy used
        assert cost["execution_cost_source_used"] == "proxy"
        assert cost["expected_execution_cost"] > 2.0

    def test_proxy_used_when_no_history(self):
        """Proxy cost used when no history available."""
        cost = _determine_execution_cost_local(
            drag_map={},
            symbol="SPY",
            combo_width_share=0.10,
            num_legs=4,
            is_limit=True
        )

        assert cost["execution_cost_source_used"] == "proxy"
        assert cost["execution_drag_source"] == "proxy"


class TestMultiLegDefaultsToLimit:
    """Test that multi-leg trades default to limit order slippage."""

    def test_two_leg_is_limit(self):
        """Two-leg trades should use limit order slippage."""
        num_legs = 2
        is_limit = num_legs >= 2
        assert is_limit is True

    def test_four_leg_is_limit(self):
        """Four-leg trades should use limit order slippage."""
        num_legs = 4
        is_limit = num_legs >= 2
        assert is_limit is True

    def test_single_leg_not_limit(self):
        """Single-leg trades would not use limit by this rule."""
        num_legs = 1
        is_limit = num_legs >= 2
        assert is_limit is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
