"""
Tests for Regime Engine V4 — continuous multi-factor state.

Tests:
1. RegimeVector label backward compatibility
2. Factor computations with mock data
3. Composite risk score
4. Graceful degradation without market data
5. Feature flag gating
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from packages.quantum.analytics.regime_engine_v4 import (
    RegimeVector,
    RegimeEngineV4,
    is_regime_v4_enabled,
    _clamp,
    _variance,
)
from packages.quantum.common_enums import RegimeState


# ---------------------------------------------------------------------------
# RegimeVector Tests
# ---------------------------------------------------------------------------

class TestRegimeVector:
    def test_default_label_is_normal(self):
        vec = RegimeVector()
        assert vec.label == "normal"

    def test_shock_label(self):
        vec = RegimeVector(volatility_regime=0.9)
        assert vec.label == "shock"
        assert vec.regime_state == RegimeState.SHOCK
        assert vec.scoring_regime == "panic"

    def test_elevated_label(self):
        vec = RegimeVector(volatility_regime=0.7, trend_strength=-0.3)
        assert vec.label == "elevated"
        assert vec.scoring_regime == "high_vol"

    def test_rebound_label(self):
        vec = RegimeVector(volatility_regime=0.7, trend_strength=0.5)
        assert vec.label == "rebound"

    def test_chop_label(self):
        vec = RegimeVector(
            volatility_regime=0.3,
            trend_strength=0.05,
            mean_reversion=0.8,
        )
        assert vec.label == "chop"

    def test_suppressed_label(self):
        vec = RegimeVector(volatility_regime=0.1, trend_strength=0.1)
        assert vec.label == "suppressed"

    def test_to_dict(self):
        vec = RegimeVector(volatility_regime=0.5, trend_strength=0.3)
        d = vec.to_dict()
        assert "volatility_regime" in d
        assert "label" in d
        assert "scoring_regime" in d
        assert d["volatility_regime"] == 0.5

    def test_to_feature_dict(self):
        vec = RegimeVector(volatility_regime=0.6, trend_strength=-0.2)
        f = vec.to_feature_dict()
        assert f["regime_v4_vol"] == 0.6
        assert f["regime_v4_trend"] == -0.2
        assert len(f) == 7

    def test_regime_state_enum(self):
        vec = RegimeVector(volatility_regime=0.3)
        assert isinstance(vec.regime_state, RegimeState)


# ---------------------------------------------------------------------------
# Risk Score Tests
# ---------------------------------------------------------------------------

class TestRiskScore:
    def test_calm_market_low_risk(self):
        engine = RegimeEngineV4()
        vec = RegimeVector(
            volatility_regime=0.1,
            trend_strength=0.5,
            correlation_regime=0.3,
            liquidity_regime=0.9,
            event_density=0.0,
        )
        score = engine._compute_risk_score(vec)
        assert score < 30

    def test_crisis_market_high_risk(self):
        engine = RegimeEngineV4()
        vec = RegimeVector(
            volatility_regime=0.9,
            trend_strength=-0.8,
            correlation_regime=0.9,
            liquidity_regime=0.2,
            event_density=0.8,
        )
        score = engine._compute_risk_score(vec)
        assert score > 70

    def test_risk_scaler_low_risk(self):
        engine = RegimeEngineV4()
        vec = RegimeVector()
        vec.risk_score = 15
        assert engine._compute_risk_scaler(vec) == 1.2

    def test_risk_scaler_high_risk(self):
        engine = RegimeEngineV4()
        vec = RegimeVector()
        vec.risk_score = 85
        assert engine._compute_risk_scaler(vec) == 0.5


# ---------------------------------------------------------------------------
# Engine Tests (no market data)
# ---------------------------------------------------------------------------

class TestEngineNoData:
    def test_compute_without_market_data(self):
        engine = RegimeEngineV4(market_data=None)
        vec = engine.compute()
        assert vec.volatility_regime == 0.3
        assert vec.trend_strength == 0.0
        assert vec.label in ("normal", "suppressed", "chop")

    def test_event_density_with_signals(self):
        engine = RegimeEngineV4()
        signals = {
            "AAPL": {"is_earnings_week": True},
            "MSFT": {"is_earnings_week": True},
            "GOOG": {"is_earnings_week": False},
            "AMZN": {"is_earnings_week": False},
            "META": {"is_earnings_week": False},
        }
        density = engine._compute_event_density(signals)
        assert density == pytest.approx(0.4, abs=0.01)

    def test_event_density_empty(self):
        engine = RegimeEngineV4()
        assert engine._compute_event_density(None) == 0.0
        assert engine._compute_event_density({}) == 0.0


# ---------------------------------------------------------------------------
# Factor computation with mock market data
# ---------------------------------------------------------------------------

class TestFactorsWithMock:
    def _mock_market_data(self, spy_closes=None, basket_quotes=None):
        md = MagicMock()
        if spy_closes is None:
            spy_closes = [490 + i * 0.1 for i in range(100)]
        bars = [{"close": c} for c in spy_closes]
        md.daily_bars.return_value = bars
        if basket_quotes is None:
            basket_quotes = {
                sym: {"quote": {"bid": 100, "ask": 100.05, "mid": 100.025}}
                for sym in RegimeEngineV4.BASKET
            }
        md.snapshot_many.return_value = basket_quotes
        return md

    def test_trend_uptrend(self):
        closes = [400 + i * 1.5 for i in range(100)]
        md = self._mock_market_data(spy_closes=closes)
        engine = RegimeEngineV4(market_data=md)
        trend, ok = engine._compute_trend(datetime.now(timezone.utc))
        assert ok is True
        assert trend > 0.3

    def test_trend_downtrend(self):
        closes = [600 - i * 1.0 for i in range(100)]
        md = self._mock_market_data(spy_closes=closes)
        engine = RegimeEngineV4(market_data=md)
        trend, ok = engine._compute_trend(datetime.now(timezone.utc))
        assert ok is True
        assert trend < -0.3

    def test_liquidity_deep(self):
        quotes = {
            sym: {"quote": {"bid": 500, "ask": 500.01, "mid": 500.005}}
            for sym in RegimeEngineV4.BASKET
        }
        md = self._mock_market_data(basket_quotes=quotes)
        engine = RegimeEngineV4(market_data=md)
        liq, ok = engine._compute_liquidity()
        assert ok is True
        assert liq > 0.9

    def test_liquidity_thin(self):
        quotes = {
            sym: {"quote": {"bid": 100, "ask": 101, "mid": 100.5}}
            for sym in RegimeEngineV4.BASKET
        }
        md = self._mock_market_data(basket_quotes=quotes)
        engine = RegimeEngineV4(market_data=md)
        liq, ok = engine._compute_liquidity()
        assert ok is True
        assert liq < 0.3

    def test_full_compute_with_mock(self):
        md = self._mock_market_data()
        engine = RegimeEngineV4(market_data=md)
        vec = engine.compute()
        assert 0.0 <= vec.volatility_regime <= 1.0
        assert -1.0 <= vec.trend_strength <= 1.0
        assert 0.0 <= vec.risk_score <= 100.0
        assert vec.engine_version == "v4_continuous"


# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------

class TestFeatureFlag:
    @patch.dict("os.environ", {"REGIME_V4_ENABLED": "1"})
    def test_enabled(self):
        assert is_regime_v4_enabled() is True

    @patch.dict("os.environ", {"REGIME_V4_ENABLED": "0"})
    def test_disabled(self):
        assert is_regime_v4_enabled() is False

    @patch.dict("os.environ", {}, clear=True)
    def test_default_disabled(self):
        assert is_regime_v4_enabled() is False


# ---------------------------------------------------------------------------
# Utility tests
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_clamp(self):
        assert _clamp(0.5, 0, 1) == 0.5
        assert _clamp(-0.5, 0, 1) == 0.0
        assert _clamp(1.5, 0, 1) == 1.0

    def test_variance(self):
        assert _variance([1, 1, 1]) == 0.0
        assert _variance([1, 2, 3]) == pytest.approx(1.0, abs=0.01)
        assert _variance([]) == 0.0
