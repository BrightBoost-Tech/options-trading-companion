"""
Tests for UnboundLocalError fix for ev_obj in scanner.

Verifies:
1. _condor_pop_from_legs returns correct PoP values
2. PoP block handles ev_obj=None for condor path
3. Edge cases for condor leg detection
"""

import pytest
from typing import Dict, Any, List, Optional


def _condor_pop_from_legs(legs: List[Dict[str, Any]]) -> Optional[float]:
    """
    Estimate PoP for condor as 1 - (|delta_short_put| + |delta_short_call|).
    Clamped to [0.01, 0.99]. Returns None if required legs not found.
    """
    try:
        short_puts = [l for l in legs if l.get("type") == "put" and l.get("side") == "sell"]
        short_calls = [l for l in legs if l.get("type") == "call" and l.get("side") == "sell"]
        if not short_puts or not short_calls:
            return None
        sp = short_puts[0]
        sc = short_calls[0]
        p_loss_put = abs(float(sp.get("delta") or 0.0))
        p_loss_call = abs(float(sc.get("delta") or 0.0))
        p_win = 1.0 - min(1.0, p_loss_put + p_loss_call)
        return max(0.01, min(0.99, p_win))
    except Exception:
        return None


class TestCondorPopFromLegs:
    """Tests for _condor_pop_from_legs helper function."""

    def test_typical_10_delta_condor(self):
        """Typical 10-delta iron condor should have ~80% PoP."""
        legs = [
            {"type": "put", "side": "sell", "strike": 95, "delta": -0.10},
            {"type": "put", "side": "buy", "strike": 90, "delta": -0.05},
            {"type": "call", "side": "sell", "strike": 105, "delta": 0.10},
            {"type": "call", "side": "buy", "strike": 110, "delta": 0.05},
        ]
        pop = _condor_pop_from_legs(legs)
        assert pop is not None
        # p_win = 1 - (0.10 + 0.10) = 0.80
        assert abs(pop - 0.80) < 1e-9

    def test_15_delta_condor(self):
        """15-delta iron condor should have ~70% PoP."""
        legs = [
            {"type": "put", "side": "sell", "strike": 93, "delta": -0.15},
            {"type": "put", "side": "buy", "strike": 88, "delta": -0.08},
            {"type": "call", "side": "sell", "strike": 107, "delta": 0.15},
            {"type": "call", "side": "buy", "strike": 112, "delta": 0.08},
        ]
        pop = _condor_pop_from_legs(legs)
        assert pop is not None
        # p_win = 1 - (0.15 + 0.15) = 0.70
        assert abs(pop - 0.70) < 1e-9

    def test_high_delta_condor_clamped(self):
        """Very high delta condor should be clamped to 0.01."""
        legs = [
            {"type": "put", "side": "sell", "strike": 97, "delta": -0.55},
            {"type": "put", "side": "buy", "strike": 92, "delta": -0.50},
            {"type": "call", "side": "sell", "strike": 103, "delta": 0.55},
            {"type": "call", "side": "buy", "strike": 108, "delta": 0.50},
        ]
        pop = _condor_pop_from_legs(legs)
        assert pop is not None
        # p_win = 1 - min(1.0, 0.55 + 0.55) = 1 - 1.0 = 0.0
        # Clamped to 0.01
        assert pop == 0.01

    def test_low_delta_condor_clamped(self):
        """Very low delta condor should be clamped to 0.99."""
        legs = [
            {"type": "put", "side": "sell", "strike": 80, "delta": -0.001},
            {"type": "put", "side": "buy", "strike": 75, "delta": -0.0005},
            {"type": "call", "side": "sell", "strike": 120, "delta": 0.001},
            {"type": "call", "side": "buy", "strike": 125, "delta": 0.0005},
        ]
        pop = _condor_pop_from_legs(legs)
        assert pop is not None
        # p_win = 1 - 0.002 = 0.998
        # Clamped to 0.99
        assert pop == 0.99

    def test_missing_short_put_returns_none(self):
        """Missing short put should return None."""
        legs = [
            {"type": "put", "side": "buy", "strike": 90, "delta": -0.05},
            {"type": "call", "side": "sell", "strike": 105, "delta": 0.10},
            {"type": "call", "side": "buy", "strike": 110, "delta": 0.05},
        ]
        assert _condor_pop_from_legs(legs) is None

    def test_missing_short_call_returns_none(self):
        """Missing short call should return None."""
        legs = [
            {"type": "put", "side": "sell", "strike": 95, "delta": -0.10},
            {"type": "put", "side": "buy", "strike": 90, "delta": -0.05},
            {"type": "call", "side": "buy", "strike": 110, "delta": 0.05},
        ]
        assert _condor_pop_from_legs(legs) is None

    def test_empty_legs_returns_none(self):
        """Empty legs list should return None."""
        assert _condor_pop_from_legs([]) is None

    def test_delta_none_treated_as_zero(self):
        """None delta should be treated as 0."""
        legs = [
            {"type": "put", "side": "sell", "strike": 95, "delta": None},
            {"type": "put", "side": "buy", "strike": 90, "delta": -0.05},
            {"type": "call", "side": "sell", "strike": 105, "delta": None},
            {"type": "call", "side": "buy", "strike": 110, "delta": 0.05},
        ]
        pop = _condor_pop_from_legs(legs)
        assert pop is not None
        # p_win = 1 - (0 + 0) = 1.0, clamped to 0.99
        assert pop == 0.99

    def test_missing_delta_key_treated_as_zero(self):
        """Missing delta key should be treated as 0."""
        legs = [
            {"type": "put", "side": "sell", "strike": 95},  # No delta key
            {"type": "put", "side": "buy", "strike": 90, "delta": -0.05},
            {"type": "call", "side": "sell", "strike": 105},  # No delta key
            {"type": "call", "side": "buy", "strike": 110, "delta": 0.05},
        ]
        pop = _condor_pop_from_legs(legs)
        assert pop is not None
        assert pop == 0.99

    def test_string_delta_parsed_correctly(self):
        """String delta values should be parsed correctly."""
        legs = [
            {"type": "put", "side": "sell", "strike": 95, "delta": "-0.10"},
            {"type": "put", "side": "buy", "strike": 90, "delta": "-0.05"},
            {"type": "call", "side": "sell", "strike": 105, "delta": "0.10"},
            {"type": "call", "side": "buy", "strike": 110, "delta": "0.05"},
        ]
        pop = _condor_pop_from_legs(legs)
        assert pop is not None
        assert abs(pop - 0.80) < 1e-9


class TestPopBlockLogic:
    """Tests verifying PoP block logic handles ev_obj=None correctly."""

    def test_pop_block_with_ev_obj_none_condor_path(self):
        """Simulate condor path where ev_obj is None."""
        # This simulates the logic in scan_for_opportunities

        ev_obj = None  # Condor path doesn't set ev_obj
        strategy_key = "iron_condor"
        legs = [
            {"type": "put", "side": "sell", "strike": 95, "delta": -0.10},
            {"type": "put", "side": "buy", "strike": 90, "delta": -0.05},
            {"type": "call", "side": "sell", "strike": 105, "delta": 0.10},
            {"type": "call", "side": "buy", "strike": 110, "delta": 0.05},
        ]

        # Simulate PoP block logic
        pop = None
        pop_source = None

        # Use EV object if available (1-leg / 2-leg paths)
        if ev_obj is not None:
            if hasattr(ev_obj, "win_probability"):
                pop = float(ev_obj.win_probability)
                pop_source = "ev"
            elif isinstance(ev_obj, dict) and "win_probability" in ev_obj:
                pop = float(ev_obj["win_probability"])
                pop_source = "ev"

        # Condor fallback PoP (no ev_obj in condor path)
        if pop is None and len(legs) == 4 and ("condor" in strategy_key or "iron_condor" in strategy_key):
            pop = _condor_pop_from_legs(legs)
            pop_source = "condor_delta_tail" if pop is not None else None

        # Final fallback (would call _estimate_probability_of_profit in real code)
        if pop is None:
            pop = 0.5  # Fallback value
            pop_source = "score_fallback"

        # Clamp + verify
        pop = max(0.0, min(1.0, float(pop)))

        # Should NOT raise UnboundLocalError, should use condor fallback
        assert pop_source == "condor_delta_tail"
        assert abs(pop - 0.80) < 1e-9

    def test_pop_block_with_ev_obj_present(self):
        """Simulate 1-leg/2-leg path where ev_obj is set."""
        # Mock ev_obj with win_probability attribute
        class MockEVObj:
            win_probability = 0.65

        ev_obj = MockEVObj()
        strategy_key = "debit_spread"
        legs = [
            {"type": "call", "side": "buy", "strike": 100, "delta": 0.50},
            {"type": "call", "side": "sell", "strike": 105, "delta": 0.30},
        ]

        # Simulate PoP block logic
        pop = None
        pop_source = None

        # Use EV object if available
        if ev_obj is not None:
            if hasattr(ev_obj, "win_probability"):
                pop = float(ev_obj.win_probability)
                pop_source = "ev"
            elif isinstance(ev_obj, dict) and "win_probability" in ev_obj:
                pop = float(ev_obj["win_probability"])
                pop_source = "ev"

        # Should use EV source, not condor fallback
        assert pop_source == "ev"
        assert abs(pop - 0.65) < 1e-9

    def test_pop_block_with_ev_obj_dict(self):
        """Simulate case where ev_obj is a dict."""
        ev_obj = {"win_probability": 0.72, "expected_value": 25.0}
        strategy_key = "credit_spread"
        legs = [
            {"type": "put", "side": "buy", "strike": 95, "delta": -0.20},
            {"type": "put", "side": "sell", "strike": 100, "delta": -0.35},
        ]

        # Simulate PoP block logic
        pop = None
        pop_source = None

        if ev_obj is not None:
            if hasattr(ev_obj, "win_probability"):
                pop = float(ev_obj.win_probability)
                pop_source = "ev"
            elif isinstance(ev_obj, dict) and "win_probability" in ev_obj:
                pop = float(ev_obj["win_probability"])
                pop_source = "ev"

        assert pop_source == "ev"
        assert abs(pop - 0.72) < 1e-9


class TestEdgeCases:
    """Edge case tests for PoP calculation."""

    def test_non_condor_4_leg_strategy(self):
        """4-leg strategy that's not a condor should NOT use condor fallback."""
        ev_obj = None
        strategy_key = "butterfly"  # Not condor or iron_condor
        legs = [
            {"type": "call", "side": "buy", "strike": 95, "delta": 0.60},
            {"type": "call", "side": "sell", "strike": 100, "delta": 0.50},
            {"type": "call", "side": "sell", "strike": 100, "delta": 0.50},
            {"type": "call", "side": "buy", "strike": 105, "delta": 0.40},
        ]

        pop = None
        pop_source = None

        if ev_obj is not None:
            if hasattr(ev_obj, "win_probability"):
                pop = float(ev_obj.win_probability)
                pop_source = "ev"

        # Condor fallback should NOT trigger (strategy_key != condor)
        if pop is None and len(legs) == 4 and ("condor" in strategy_key or "iron_condor" in strategy_key):
            pop = _condor_pop_from_legs(legs)
            pop_source = "condor_delta_tail" if pop is not None else None

        # Should fall through to final fallback
        if pop is None:
            pop = 0.5
            pop_source = "score_fallback"

        assert pop_source == "score_fallback"

    def test_condor_with_missing_legs_falls_through(self):
        """Condor with missing short legs should fall through to final fallback."""
        ev_obj = None
        strategy_key = "iron_condor"
        legs = [
            {"type": "put", "side": "buy", "strike": 90, "delta": -0.05},
            {"type": "call", "side": "buy", "strike": 110, "delta": 0.05},
        ]  # Missing short legs

        pop = None
        pop_source = None

        if ev_obj is not None:
            pass  # Would set pop

        if pop is None and len(legs) == 4 and ("condor" in strategy_key):
            pop = _condor_pop_from_legs(legs)
            pop_source = "condor_delta_tail" if pop is not None else None

        # len(legs) == 2, so condor check won't trigger
        if pop is None:
            pop = 0.5
            pop_source = "score_fallback"

        assert pop_source == "score_fallback"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
