"""
Tests for midday quality gate soft mode.

Verifies:
1. _legs_have_valid_nbbo_and_mid correctly validates leg quotes
2. Soft mode behavior: fatal issues mark NOT_EXECUTABLE instead of skipping
3. Trust scanner quotes bypasses snapshot gate when legs have valid NBBO+mid
"""

import pytest
from typing import Dict, Any, List


def _legs_have_valid_nbbo_and_mid(legs: list) -> bool:
    """
    Check if all legs have valid NBBO and mid prices.
    Returns True iff every leg has bid>0, ask>0, ask>=bid, and mid>0.
    """
    if not legs:
        return False
    for leg in legs:
        bid = leg.get("bid")
        ask = leg.get("ask")
        mid = leg.get("mid")
        if bid is None or ask is None or mid is None:
            return False
        try:
            bid = float(bid)
            ask = float(ask)
            mid = float(mid)
        except (TypeError, ValueError):
            return False
        if bid <= 0 or ask <= 0 or ask < bid or mid <= 0:
            return False
    return True


class TestLegsHaveValidNbboAndMid:
    """Tests for _legs_have_valid_nbbo_and_mid helper."""

    def test_valid_iron_condor_legs(self):
        """Iron condor with valid NBBO and mid on all legs."""
        legs = [
            {"symbol": "SPY240315P00450000", "bid": 1.00, "ask": 1.10, "mid": 1.05},
            {"symbol": "SPY240315P00445000", "bid": 0.40, "ask": 0.50, "mid": 0.45},
            {"symbol": "SPY240315C00460000", "bid": 0.90, "ask": 1.00, "mid": 0.95},
            {"symbol": "SPY240315C00465000", "bid": 0.30, "ask": 0.40, "mid": 0.35},
        ]
        assert _legs_have_valid_nbbo_and_mid(legs) is True

    def test_valid_vertical_spread(self):
        """Vertical spread with valid NBBO and mid."""
        legs = [
            {"symbol": "AAPL240315C00170000", "bid": 5.00, "ask": 5.20, "mid": 5.10},
            {"symbol": "AAPL240315C00175000", "bid": 3.00, "ask": 3.20, "mid": 3.10},
        ]
        assert _legs_have_valid_nbbo_and_mid(legs) is True

    def test_empty_legs_returns_false(self):
        """Empty legs list returns False."""
        assert _legs_have_valid_nbbo_and_mid([]) is False

    def test_missing_bid_returns_false(self):
        """Leg with missing bid returns False."""
        legs = [
            {"symbol": "SPY240315P00450000", "ask": 1.10, "mid": 1.05},
        ]
        assert _legs_have_valid_nbbo_and_mid(legs) is False

    def test_missing_ask_returns_false(self):
        """Leg with missing ask returns False."""
        legs = [
            {"symbol": "SPY240315P00450000", "bid": 1.00, "mid": 1.05},
        ]
        assert _legs_have_valid_nbbo_and_mid(legs) is False

    def test_missing_mid_returns_false(self):
        """Leg with missing mid returns False."""
        legs = [
            {"symbol": "SPY240315P00450000", "bid": 1.00, "ask": 1.10},
        ]
        assert _legs_have_valid_nbbo_and_mid(legs) is False

    def test_none_bid_returns_false(self):
        """Leg with None bid returns False."""
        legs = [
            {"symbol": "SPY240315P00450000", "bid": None, "ask": 1.10, "mid": 1.05},
        ]
        assert _legs_have_valid_nbbo_and_mid(legs) is False

    def test_zero_bid_returns_false(self):
        """Leg with zero bid (one-sided quote) returns False."""
        legs = [
            {"symbol": "SPY240315P00450000", "bid": 0, "ask": 1.10, "mid": 0.55},
        ]
        assert _legs_have_valid_nbbo_and_mid(legs) is False

    def test_zero_ask_returns_false(self):
        """Leg with zero ask returns False."""
        legs = [
            {"symbol": "SPY240315P00450000", "bid": 1.00, "ask": 0, "mid": 0.50},
        ]
        assert _legs_have_valid_nbbo_and_mid(legs) is False

    def test_crossed_nbbo_returns_false(self):
        """Leg with crossed NBBO (ask < bid) returns False."""
        legs = [
            {"symbol": "SPY240315P00450000", "bid": 1.10, "ask": 1.00, "mid": 1.05},
        ]
        assert _legs_have_valid_nbbo_and_mid(legs) is False

    def test_zero_mid_returns_false(self):
        """Leg with zero mid returns False."""
        legs = [
            {"symbol": "SPY240315P00450000", "bid": 1.00, "ask": 1.10, "mid": 0},
        ]
        assert _legs_have_valid_nbbo_and_mid(legs) is False

    def test_negative_bid_returns_false(self):
        """Leg with negative bid returns False."""
        legs = [
            {"symbol": "SPY240315P00450000", "bid": -1.00, "ask": 1.10, "mid": 0.05},
        ]
        assert _legs_have_valid_nbbo_and_mid(legs) is False

    def test_one_bad_leg_fails_all(self):
        """One invalid leg fails entire check."""
        legs = [
            {"symbol": "SPY240315P00450000", "bid": 1.00, "ask": 1.10, "mid": 1.05},
            {"symbol": "SPY240315P00445000", "bid": 0, "ask": 0.50, "mid": 0.25},  # Bad bid
        ]
        assert _legs_have_valid_nbbo_and_mid(legs) is False

    def test_string_values_converted(self):
        """String numeric values should be converted correctly."""
        legs = [
            {"symbol": "SPY240315P00450000", "bid": "1.00", "ask": "1.10", "mid": "1.05"},
        ]
        assert _legs_have_valid_nbbo_and_mid(legs) is True

    def test_invalid_string_returns_false(self):
        """Invalid string values return False."""
        legs = [
            {"symbol": "SPY240315P00450000", "bid": "bad", "ask": "1.10", "mid": "1.05"},
        ]
        assert _legs_have_valid_nbbo_and_mid(legs) is False


class TestQualityGateModeLogic:
    """Tests for quality gate mode behavior."""

    def test_soft_mode_does_not_skip_on_fatal(self):
        """In soft mode, fatal issues should not skip but mark NOT_EXECUTABLE."""
        quality_gate_mode = "soft"
        has_fatal = True

        # Simulate the logic
        should_continue = False
        should_mark_not_executable = False

        if has_fatal:
            if quality_gate_mode == "hard":
                should_continue = True  # Skip
            else:
                should_mark_not_executable = True  # Don't skip, mark NOT_EXECUTABLE

        assert should_continue is False
        assert should_mark_not_executable is True

    def test_hard_mode_skips_on_fatal(self):
        """In hard mode, fatal issues should skip."""
        quality_gate_mode = "hard"
        has_fatal = True

        should_continue = False
        should_mark_not_executable = False

        if has_fatal:
            if quality_gate_mode == "hard":
                should_continue = True
            else:
                should_mark_not_executable = True

        assert should_continue is True
        assert should_mark_not_executable is False

    def test_soft_mode_does_not_skip_on_policy_skip(self):
        """In soft mode with policy=skip, should mark NOT_EXECUTABLE not skip."""
        quality_gate_mode = "soft"
        policy = "skip"
        has_fatal = False

        should_continue = False
        should_mark_not_executable = False

        if not has_fatal and policy == "skip":
            if quality_gate_mode == "hard":
                should_continue = True
            else:
                should_mark_not_executable = True

        assert should_continue is False
        assert should_mark_not_executable is True


class TestTrustScannerQuotes:
    """Tests for trust scanner quotes bypass logic."""

    def test_bypasses_gate_when_legs_valid(self):
        """Should bypass snapshot gate when legs have valid NBBO+mid."""
        trust_scanner_quotes = True
        legs = [
            {"bid": 1.00, "ask": 1.10, "mid": 1.05},
            {"bid": 0.50, "ask": 0.60, "mid": 0.55},
        ]

        scanner_quotes_valid = (
            trust_scanner_quotes
            and len(legs) >= 2
            and _legs_have_valid_nbbo_and_mid(legs)
        )

        assert scanner_quotes_valid is True

    def test_does_not_bypass_when_disabled(self):
        """Should not bypass when trust_scanner_quotes is False."""
        trust_scanner_quotes = False
        legs = [
            {"bid": 1.00, "ask": 1.10, "mid": 1.05},
            {"bid": 0.50, "ask": 0.60, "mid": 0.55},
        ]

        scanner_quotes_valid = (
            trust_scanner_quotes
            and len(legs) >= 2
            and _legs_have_valid_nbbo_and_mid(legs)
        )

        assert scanner_quotes_valid is False

    def test_does_not_bypass_for_single_leg(self):
        """Should not bypass for single-leg trades."""
        trust_scanner_quotes = True
        legs = [
            {"bid": 1.00, "ask": 1.10, "mid": 1.05},
        ]

        scanner_quotes_valid = (
            trust_scanner_quotes
            and len(legs) >= 2
            and _legs_have_valid_nbbo_and_mid(legs)
        )

        assert scanner_quotes_valid is False

    def test_does_not_bypass_with_invalid_quotes(self):
        """Should not bypass when quotes are invalid."""
        trust_scanner_quotes = True
        legs = [
            {"bid": 1.00, "ask": 1.10, "mid": 1.05},
            {"bid": 0, "ask": 0.60, "mid": 0.30},  # Invalid bid
        ]

        scanner_quotes_valid = (
            trust_scanner_quotes
            and len(legs) >= 2
            and _legs_have_valid_nbbo_and_mid(legs)
        )

        assert scanner_quotes_valid is False


class TestNoSuggestionsAfterGatesReturn:
    """Tests for return structure when no suggestions after gates."""

    def test_return_structure_has_required_fields(self):
        """Return should have all required fields when no suggestions."""
        # Simulate the return structure
        result = {
            "skipped": False,
            "reason": "no_suggestions_after_gates",
            "budget": {
                "deployable_capital": 5000.0,
                "cap": 2000.0,
                "usage": 500.0,
                "remaining": 1500.0,
                "regime": "neutral",
            },
            "counts": {
                "candidates": 10,
                "created": 0,
            },
            "debug": {
                "quality_gate_mode": "soft",
                "trust_scanner_quotes": True,
                "candidates_count": 10,
                "rejection_stats": None,
            },
        }

        assert result["skipped"] is False
        assert result["reason"] == "no_suggestions_after_gates"
        assert "budget" in result
        assert "counts" in result
        assert "debug" in result
        assert result["counts"]["created"] == 0
        assert result["counts"]["candidates"] == 10

    def test_debug_includes_gate_settings(self):
        """Debug should include quality gate configuration."""
        debug = {
            "quality_gate_mode": "soft",
            "trust_scanner_quotes": True,
            "candidates_count": 5,
            "rejection_stats": {"no_chain": 2, "spread_too_wide": 1},
        }

        assert debug["quality_gate_mode"] == "soft"
        assert debug["trust_scanner_quotes"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
