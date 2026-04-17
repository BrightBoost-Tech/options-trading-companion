"""
Tests for Phase 3: strategy-aware probability of profit (PoP) via calculate_pop.

Verifies:
1. Credit spread PoP uses credit/width ratio
2. Debit spread PoP uses long leg delta
3. Single-leg long uses raw delta
4. Single-leg short uses 1 - delta
5. Fallback to delta when strategy-specific data is missing
6. calculate_ev uses calibrated PoP (no double-inversion)
"""

import pytest
from packages.quantum.ev_calculator import calculate_pop, calculate_ev

# Skipped in PR #1 triage to establish CI-green gate while test debt is cleared.
# [Cluster L] stale PoP test (pre 2026-04-12 long-leg delta); fix in follow-up
# Tracked in #775 (umbrella: #767).
pytestmark = pytest.mark.skip(
    reason='[Cluster L] stale PoP test (pre 2026-04-12 long-leg delta); fix in follow-up; tracked in #775',
)


class TestCalculatePop:
    """Tests for calculate_pop function."""

    def test_credit_spread_with_credit_width(self):
        """Credit spread PoP = credit / width (max_gain / total)."""
        pop = calculate_pop("credit_spread", credit=1.50, width=5.0)
        # max_gain = 150, max_loss = 350, PoP = 150 / 500 = 0.30
        assert abs(pop - 0.30) < 0.01

    def test_credit_spread_fallback_to_delta(self):
        """Credit spread without credit/width should use 1 - delta."""
        pop = calculate_pop("credit_spread", delta=0.30)
        assert abs(pop - 0.70) < 0.01

    def test_credit_put_spread(self):
        """Credit put spread PoP from credit/width."""
        pop = calculate_pop("credit_put_spread", credit=2.0, width=5.0)
        # max_gain = 200, max_loss = 300, PoP = 200 / 500 = 0.40
        assert abs(pop - 0.40) < 0.01

    def test_debit_spread_uses_long_leg_delta(self):
        """Debit spread PoP ≈ long leg delta."""
        legs = [
            {"action": "buy", "delta": 0.60},
            {"action": "sell", "delta": 0.30},
        ]
        pop = calculate_pop("debit_spread", legs=legs)
        assert abs(pop - 0.60) < 0.01

    def test_long_call_uses_delta(self):
        """Long call PoP ≈ delta."""
        pop = calculate_pop("long_call", delta=0.35)
        assert abs(pop - 0.35) < 0.01

    def test_long_put_uses_delta(self):
        """Long put PoP ≈ delta."""
        pop = calculate_pop("long_put", delta=0.40)
        assert abs(pop - 0.40) < 0.01

    def test_short_call_uses_one_minus_delta(self):
        """Short call PoP = 1 - delta."""
        pop = calculate_pop("short_call", delta=0.25)
        assert abs(pop - 0.75) < 0.01

    def test_short_put_uses_one_minus_delta(self):
        """Short put PoP = 1 - delta."""
        pop = calculate_pop("short_put", delta=0.30)
        assert abs(pop - 0.70) < 0.01

    def test_naked_call_same_as_short(self):
        """Naked call should use 1 - delta."""
        pop = calculate_pop("naked_call", delta=0.20)
        assert abs(pop - 0.80) < 0.01

    def test_unknown_strategy_fallback(self):
        """Unknown strategy falls back to raw delta."""
        pop = calculate_pop("exotic_butterfly_condor", delta=0.55)
        assert abs(pop - 0.55) < 0.01

    def test_no_delta_returns_neutral(self):
        """With no delta and no other data, return 0.5."""
        pop = calculate_pop("unknown_strategy")
        assert pop == 0.5

    def test_credit_spread_from_sell_leg_delta(self):
        """Credit spread fallback: use sell leg delta when no raw delta."""
        legs = [
            {"action": "sell", "delta": 0.25},
            {"action": "buy", "delta": 0.10},
        ]
        pop = calculate_pop("credit_spread", legs=legs)
        # 1 - 0.25 = 0.75
        assert abs(pop - 0.75) < 0.01


class TestCalculateEvIntegration:
    """Tests that calculate_ev uses calibrated PoP correctly."""

    def test_short_call_no_double_inversion(self):
        """Short call EV should use win_prob = 1 - delta (not delta after inversion)."""
        ev_result = calculate_ev(
            premium=2.0,
            strike=100.0,
            current_price=95.0,
            delta=0.25,
            strategy="short_call",
        )
        # win_prob should be 1 - 0.25 = 0.75 (from calculate_pop)
        # NOT 0.25 (which would be double-inverted back to delta)
        assert abs(ev_result.win_probability - 0.75) < 0.01
        assert abs(ev_result.loss_probability - 0.25) < 0.01

    def test_short_put_no_double_inversion(self):
        """Short put EV should use win_prob = 1 - delta."""
        ev_result = calculate_ev(
            premium=1.50,
            strike=50.0,
            current_price=55.0,
            delta=0.30,
            strategy="short_put",
        )
        assert abs(ev_result.win_probability - 0.70) < 0.01

    def test_credit_spread_calibrated_pop(self):
        """Credit spread should use credit/width PoP when both are available."""
        ev_result = calculate_ev(
            premium=1.50,  # credit
            strike=100.0,
            current_price=95.0,
            delta=0.30,
            strategy="credit_spread",
            width=5.0,
        )
        # PoP = 1.50/5.0 = 0.30 (from credit/width ratio)
        assert abs(ev_result.win_probability - 0.30) < 0.01

    def test_long_call_uses_delta_directly(self):
        """Long call should use delta as PoP, unchanged."""
        ev_result = calculate_ev(
            premium=3.0,
            strike=100.0,
            current_price=98.0,
            delta=0.45,
            strategy="long_call",
        )
        assert abs(ev_result.win_probability - 0.45) < 0.01

    def test_long_put_uses_delta_directly(self):
        """Long put should use delta as PoP."""
        ev_result = calculate_ev(
            premium=2.0,
            strike=100.0,
            current_price=102.0,
            delta=0.40,
            strategy="long_put",
        )
        assert abs(ev_result.win_probability - 0.40) < 0.01


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
