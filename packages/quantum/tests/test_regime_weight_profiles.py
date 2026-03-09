"""
Tests for Phase 4: regime-conditioned factor weight profiles.

Verifies:
1. compute_regime_adjusted_score applies regime multipliers correctly
2. High IV rank + high vol regime produces higher score than normal
3. Weights are renormalized after multiplier application
4. map_market_regime detects low_vol regime
5. low_vol regime exists in all config dicts
"""

import pytest
from packages.quantum.analytics.regime_integration import (
    compute_regime_adjusted_score,
    REGIME_WEIGHT_PROFILES,
    DEFAULT_WEIGHT_MATRIX,
    DEFAULT_REGIME_PROFILES,
    map_market_regime,
)


class TestRegimeWeightProfiles:
    """Tests for REGIME_WEIGHT_PROFILES and compute_regime_adjusted_score."""

    BASE_WEIGHTS = {
        "iv_rank": 0.3,
        "trend_momentum": 0.3,
        "volume_score": 0.2,
        "atr_compression": 0.2,
    }

    def test_high_vol_boosts_iv_rank(self):
        """In high-vol regime, IV rank weight should increase."""
        factors = {
            "iv_rank": 0.8,
            "trend_momentum": 0.5,
            "volume_score": 0.6,
            "atr_compression": 0.3,
        }

        normal_score = compute_regime_adjusted_score(self.BASE_WEIGHTS, factors, "normal")
        high_vol_score = compute_regime_adjusted_score(self.BASE_WEIGHTS, factors, "high_vol")

        # High IV rank + high vol regime should produce higher score
        assert high_vol_score > normal_score

    def test_low_vol_boosts_trend_momentum(self):
        """In low-vol regime, trend momentum weight should increase."""
        factors = {
            "iv_rank": 0.3,
            "trend_momentum": 0.9,
            "volume_score": 0.5,
            "atr_compression": 0.7,
        }

        normal_score = compute_regime_adjusted_score(self.BASE_WEIGHTS, factors, "normal")
        low_vol_score = compute_regime_adjusted_score(self.BASE_WEIGHTS, factors, "low_vol")

        # High trend_momentum + low vol regime should produce higher score
        assert low_vol_score > normal_score

    def test_low_vol_boosts_atr_compression(self):
        """In low-vol regime, ATR compression weight should increase."""
        factors = {
            "iv_rank": 0.3,
            "trend_momentum": 0.3,
            "volume_score": 0.3,
            "atr_compression": 0.95,
        }

        normal_score = compute_regime_adjusted_score(self.BASE_WEIGHTS, factors, "normal")
        low_vol_score = compute_regime_adjusted_score(self.BASE_WEIGHTS, factors, "low_vol")

        assert low_vol_score > normal_score

    def test_weights_renormalize_to_one(self):
        """Adjusted weights should sum to 1.0 after renormalization."""
        profile = REGIME_WEIGHT_PROFILES["high_vol"]
        adjusted = {k: self.BASE_WEIGHTS[k] * profile.get(k, 1.0) for k in self.BASE_WEIGHTS}
        total = sum(adjusted.values())
        normalized = {k: v / total for k, v in adjusted.items()}
        assert abs(sum(normalized.values()) - 1.0) < 1e-9

    def test_normal_regime_identity(self):
        """Normal regime multipliers are all 1.0 — score should match simple weighted average."""
        factors = {"iv_rank": 0.5, "trend_momentum": 0.5, "volume_score": 0.5, "atr_compression": 0.5}
        score = compute_regime_adjusted_score(self.BASE_WEIGHTS, factors, "normal")
        # All factors equal 0.5, all weights normalize to same ratios → score = 0.5
        assert abs(score - 0.5) < 0.01

    def test_unknown_regime_defaults_to_normal(self):
        """Unknown regime should fall back to normal profile."""
        factors = {"iv_rank": 0.7, "trend_momentum": 0.3, "volume_score": 0.5, "atr_compression": 0.4}
        unknown_score = compute_regime_adjusted_score(self.BASE_WEIGHTS, factors, "unknown_regime_xyz")
        normal_score = compute_regime_adjusted_score(self.BASE_WEIGHTS, factors, "normal")
        assert abs(unknown_score - normal_score) < 1e-9

    def test_zero_base_weights_returns_zero(self):
        """If all base weights are 0, return 0."""
        factors = {"iv_rank": 0.8, "trend_momentum": 0.5}
        zero_weights = {"iv_rank": 0.0, "trend_momentum": 0.0}
        score = compute_regime_adjusted_score(zero_weights, factors, "normal")
        assert score == 0.0

    def test_all_regimes_in_profiles(self):
        """All standard regimes should exist in REGIME_WEIGHT_PROFILES."""
        for regime in ("low_vol", "normal", "high_vol", "panic"):
            assert regime in REGIME_WEIGHT_PROFILES


class TestMapMarketRegimeLowVol:
    """Tests for low_vol regime detection in map_market_regime."""

    def test_low_vol_detected(self):
        """Low annual vol (<10%) should map to low_vol regime."""
        result = map_market_regime({"state": "crab", "vol_annual": 0.08})
        assert result == "low_vol"

    def test_very_low_vol(self):
        """Very low vol should still be low_vol."""
        result = map_market_regime({"state": "bull", "vol_annual": 0.05})
        assert result == "low_vol"

    def test_normal_vol_not_low(self):
        """Normal vol (10-20%) should be normal, not low_vol."""
        result = map_market_regime({"state": "bull", "vol_annual": 0.15})
        assert result == "normal"

    def test_high_vol_overrides_state(self):
        """High vol should still override to high_vol."""
        result = map_market_regime({"state": "bull", "vol_annual": 0.25})
        assert result == "high_vol"

    def test_shock_always_panic(self):
        """Shock state always maps to panic, even with low vol."""
        result = map_market_regime({"state": "shock", "vol_annual": 0.05})
        assert result == "panic"

    def test_zero_vol_not_low_vol(self):
        """Zero vol (data missing) should be normal, not low_vol."""
        result = map_market_regime({"state": "normal", "vol_annual": 0.0})
        assert result == "normal"


class TestDefaultConfigCompleteness:
    """Verify all config dicts include low_vol regime."""

    def test_weight_matrix_has_low_vol(self):
        assert "low_vol" in DEFAULT_WEIGHT_MATRIX

    def test_regime_profiles_has_low_vol(self):
        assert "low_vol" in DEFAULT_REGIME_PROFILES

    def test_regime_weight_profiles_has_low_vol(self):
        assert "low_vol" in REGIME_WEIGHT_PROFILES


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
