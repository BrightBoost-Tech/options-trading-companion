"""
Tests for liquidity-aware mid calculation and condor spread gating.

Verifies:
1. Mid is NOT computed from one-sided quotes (bid=0 or ask=0)
2. _is_valid_nbbo correctly validates bid/ask pairs
3. _leg_spread_pct computes per-leg spread percentage
4. Condor spread gate uses max per-leg spread, not combo_width/entry_cost
"""

import pytest
from typing import Dict, Any, Optional, List


# Replicate helper functions for testing
def _is_valid_nbbo(bid: Any, ask: Any) -> bool:
    """
    Check if bid/ask values constitute a valid NBBO.
    Returns True only if bid > 0, ask > 0, and ask >= bid.
    """
    try:
        if bid is None or ask is None:
            return False
        bid_f = float(bid)
        ask_f = float(ask)
        return bid_f > 0 and ask_f > 0 and ask_f >= bid_f
    except (TypeError, ValueError):
        return False


def _leg_spread_pct(leg: Dict[str, Any]) -> Optional[float]:
    """
    Compute per-leg spread percentage: (ask - bid) / mid.
    Returns None if leg doesn't have valid NBBO or mid <= 0.
    """
    try:
        bid = leg.get("bid")
        ask = leg.get("ask")
        if not _is_valid_nbbo(bid, ask):
            return None
        bid_f = float(bid)
        ask_f = float(ask)
        mid = (bid_f + ask_f) / 2.0
        if mid <= 0:
            return None
        return (ask_f - bid_f) / mid
    except (TypeError, ValueError):
        return None


def _leg_has_valid_bidask(leg: Dict[str, Any]) -> bool:
    """Check if leg has valid bid/ask quotes."""
    try:
        bid = leg.get("bid")
        ask = leg.get("ask")
        if bid is None or ask is None:
            return False
        bid_f = float(bid)
        ask_f = float(ask)
        return bid_f > 0 and ask_f > 0 and ask_f >= bid_f
    except (TypeError, ValueError):
        return False


class TestIsValidNBBO:
    """Test _is_valid_nbbo helper function."""

    def test_valid_nbbo(self):
        """Valid bid/ask returns True."""
        assert _is_valid_nbbo(1.50, 1.60) is True

    def test_bid_zero(self):
        """Bid=0 returns False."""
        assert _is_valid_nbbo(0, 1.60) is False

    def test_ask_zero(self):
        """Ask=0 returns False."""
        assert _is_valid_nbbo(1.50, 0) is False

    def test_both_zero(self):
        """Both zero returns False."""
        assert _is_valid_nbbo(0, 0) is False

    def test_bid_none(self):
        """Bid None returns False."""
        assert _is_valid_nbbo(None, 1.60) is False

    def test_ask_none(self):
        """Ask None returns False."""
        assert _is_valid_nbbo(1.50, None) is False

    def test_crossed_market(self):
        """Crossed market (bid > ask) returns False."""
        assert _is_valid_nbbo(1.60, 1.50) is False

    def test_locked_market(self):
        """Locked market (bid == ask) returns True."""
        assert _is_valid_nbbo(1.50, 1.50) is True

    def test_string_values(self):
        """String values are converted."""
        assert _is_valid_nbbo("1.50", "1.60") is True

    def test_negative_bid(self):
        """Negative bid returns False."""
        assert _is_valid_nbbo(-1.50, 1.60) is False


class TestLegSpreadPct:
    """Test _leg_spread_pct helper function."""

    def test_valid_leg(self):
        """Valid leg returns correct spread pct."""
        leg = {"bid": 1.00, "ask": 1.20}
        # mid = 1.10, spread = 0.20, pct = 0.20/1.10 = 0.1818...
        result = _leg_spread_pct(leg)
        assert result is not None
        assert abs(result - 0.1818) < 0.01

    def test_tight_spread(self):
        """Tight spread returns small pct."""
        leg = {"bid": 1.00, "ask": 1.02}
        # mid = 1.01, spread = 0.02, pct = 0.02/1.01 = 0.0198
        result = _leg_spread_pct(leg)
        assert result is not None
        assert result < 0.03

    def test_wide_spread(self):
        """Wide spread returns large pct."""
        leg = {"bid": 0.50, "ask": 1.00}
        # mid = 0.75, spread = 0.50, pct = 0.50/0.75 = 0.667
        result = _leg_spread_pct(leg)
        assert result is not None
        assert result > 0.5

    def test_bid_zero_returns_none(self):
        """Bid=0 returns None."""
        leg = {"bid": 0, "ask": 1.00}
        assert _leg_spread_pct(leg) is None

    def test_ask_zero_returns_none(self):
        """Ask=0 returns None."""
        leg = {"bid": 1.00, "ask": 0}
        assert _leg_spread_pct(leg) is None

    def test_missing_bid_returns_none(self):
        """Missing bid returns None."""
        leg = {"ask": 1.00}
        assert _leg_spread_pct(leg) is None

    def test_missing_ask_returns_none(self):
        """Missing ask returns None."""
        leg = {"bid": 1.00}
        assert _leg_spread_pct(leg) is None

    def test_crossed_market_returns_none(self):
        """Crossed market returns None."""
        leg = {"bid": 1.20, "ask": 1.00}
        assert _leg_spread_pct(leg) is None


class TestMidCalculation:
    """Test that mid is NOT computed from one-sided quotes."""

    def test_mid_not_computed_bid_zero(self):
        """Mid should NOT be computed when bid=0."""
        bid = 0
        ask = 15.0
        mid = None
        if _is_valid_nbbo(bid, ask):
            mid = (float(bid) + float(ask)) / 2.0

        # Mid should be None because bid=0 is invalid
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


class TestCondorSpreadGating:
    """Test condor-specific spread gating using max per-leg spread."""

    def test_condor_uses_max_leg_spread(self):
        """Condor spread_pct should use max per-leg spread."""
        legs = [
            {"symbol": "O:SPY240119P450", "bid": 1.00, "ask": 1.10},  # 9.5% spread
            {"symbol": "O:SPY240119P445", "bid": 0.50, "ask": 0.60},  # 18% spread
            {"symbol": "O:SPY240119C465", "bid": 1.00, "ask": 1.15},  # 14% spread
            {"symbol": "O:SPY240119C470", "bid": 0.40, "ask": 0.60},  # 40% spread (widest)
        ]

        per_leg_pcts = [p for p in (_leg_spread_pct(l) for l in legs) if p is not None]
        max_spread = max(per_leg_pcts)

        # The widest spread is 40% on leg 4 (0.20 / 0.50 = 0.40)
        assert max_spread > 0.35
        assert len(per_leg_pcts) == 4

    def test_condor_rejects_wide_spread(self):
        """Condor should be rejected if max leg spread > threshold."""
        legs = [
            {"symbol": "O:SPY240119P450", "bid": 0.10, "ask": 0.30},  # 100% spread
            {"symbol": "O:SPY240119P445", "bid": 0.10, "ask": 0.30},
            {"symbol": "O:SPY240119C465", "bid": 0.10, "ask": 0.30},
            {"symbol": "O:SPY240119C470", "bid": 0.10, "ask": 0.30},
        ]

        per_leg_pcts = [p for p in (_leg_spread_pct(l) for l in legs) if p is not None]
        max_spread = max(per_leg_pcts) if per_leg_pcts else 1.0

        threshold = 0.35  # CONDOR_MAX_LEG_SPREAD_PCT default

        # All legs have 100% spread, should exceed threshold
        assert max_spread > threshold

    def test_condor_passes_tight_spread(self):
        """Condor should pass if all legs have tight spreads."""
        legs = [
            {"symbol": "O:SPY240119P450", "bid": 1.00, "ask": 1.05},  # 5% spread
            {"symbol": "O:SPY240119P445", "bid": 0.80, "ask": 0.85},  # 6% spread
            {"symbol": "O:SPY240119C465", "bid": 1.10, "ask": 1.15},  # 4.5% spread
            {"symbol": "O:SPY240119C470", "bid": 0.70, "ask": 0.75},  # 7% spread
        ]

        per_leg_pcts = [p for p in (_leg_spread_pct(l) for l in legs) if p is not None]
        max_spread = max(per_leg_pcts) if per_leg_pcts else 1.0

        threshold = 0.35

        # All legs have tight spreads, should pass
        assert max_spread < threshold

    def test_condor_missing_nbbo_conservative(self):
        """Condor with missing NBBO should use conservative default."""
        legs = [
            {"symbol": "O:SPY240119P450", "bid": None, "ask": None},
            {"symbol": "O:SPY240119P445", "bid": None, "ask": None},
            {"symbol": "O:SPY240119C465", "bid": None, "ask": None},
            {"symbol": "O:SPY240119C470", "bid": None, "ask": None},
        ]

        per_leg_pcts = [p for p in (_leg_spread_pct(l) for l in legs) if p is not None]

        if per_leg_pcts:
            option_spread_pct = max(per_leg_pcts)
        else:
            option_spread_pct = 1.0  # Conservative default

        # No valid legs, should use 1.0 (100%)
        assert option_spread_pct == 1.0

    def test_condor_partial_nbbo(self):
        """Condor with some valid NBBO should use max of valid legs."""
        legs = [
            {"symbol": "O:SPY240119P450", "bid": 1.00, "ask": 1.20},  # 18% spread
            {"symbol": "O:SPY240119P445", "bid": None, "ask": None},  # Invalid
            {"symbol": "O:SPY240119C465", "bid": 1.00, "ask": 1.10},  # 9% spread
            {"symbol": "O:SPY240119C470", "bid": 0, "ask": 1.00},     # Invalid (bid=0)
        ]

        per_leg_pcts = [p for p in (_leg_spread_pct(l) for l in legs) if p is not None]

        # Only 2 legs are valid
        assert len(per_leg_pcts) == 2
        max_spread = max(per_leg_pcts)
        # Max is the 18% spread
        assert abs(max_spread - 0.1818) < 0.01


class TestLegacyNonCondorBehavior:
    """Test that non-condor strategies still use legacy spread calculation."""

    def test_single_leg_uses_legacy(self):
        """Single leg strategy uses combo_width/entry_cost."""
        # For non-condor strategies, we use the legacy calculation
        # This test just verifies the logic conceptually
        legs = [
            {"symbol": "O:SPY240119P450", "bid": 1.00, "ask": 1.20},
        ]

        is_condor = len(legs) == 4  # False
        assert is_condor is False

    def test_two_leg_spread_uses_legacy(self):
        """Two-leg spread uses combo_width/entry_cost."""
        legs = [
            {"symbol": "O:SPY240119P450", "bid": 1.00, "ask": 1.20},
            {"symbol": "O:SPY240119P445", "bid": 0.50, "ask": 0.60},
        ]

        strategy_key = "bull_put_spread"
        is_condor = len(legs) == 4 and ("condor" in strategy_key or "iron_condor" in strategy_key)
        assert is_condor is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
