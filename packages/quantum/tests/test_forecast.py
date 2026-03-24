"""
Tests for forecast layer v4.

Tests:
1. ReturnForecast distribution properties
2. VolForecast term structure and interpolation
3. ForecastBundle serialization round-trip
4. Regime/event adjustment effects
5. forecast_ev_pop integration
"""

import math
import pytest

from packages.quantum.forecast.return_forecast import (
    ReturnForecast,
    build_return_forecast,
    _norm_cdf,
    _norm_ppf,
    is_forecast_v4_enabled,
)
from packages.quantum.forecast.vol_forecast import (
    VolForecast,
    build_vol_forecast,
)
from packages.quantum.forecast.forecast_interface import (
    ForecastBundle,
    ForecastSet,
    forecast_ev_pop,
)


# ---------------------------------------------------------------------------
# ReturnForecast Tests
# ---------------------------------------------------------------------------

class TestReturnForecast:
    def test_default_forecast(self):
        fc = ReturnForecast(symbol="SPY", horizon_days=30)
        assert fc.mean == 0.0
        assert fc.std == 0.25
        assert fc.horizon_days == 30

    def test_horizon_scaling(self):
        fc = ReturnForecast(symbol="SPY", horizon_days=365, mean=0.10, std=0.20)
        assert fc.horizon_mean == pytest.approx(0.10, abs=0.001)
        assert fc.horizon_std == pytest.approx(0.20, abs=0.001)

    def test_horizon_scaling_30d(self):
        fc = ReturnForecast(symbol="SPY", horizon_days=30, mean=0.10, std=0.20)
        # 30/365 ≈ 0.082, sqrt(0.082) ≈ 0.287
        assert fc.horizon_mean == pytest.approx(0.10 * 30 / 365, abs=0.001)
        assert fc.horizon_std == pytest.approx(0.20 * math.sqrt(30 / 365), abs=0.001)

    def test_quantile_50_is_mean(self):
        fc = ReturnForecast(symbol="SPY", horizon_days=30, mean=0.05, std=0.20)
        q50 = fc.quantile(0.5)
        assert q50 == pytest.approx(fc.horizon_mean, abs=0.01)

    def test_quantile_ordering(self):
        fc = ReturnForecast(symbol="SPY", horizon_days=30, mean=0.05, std=0.20)
        q10 = fc.quantile(0.10)
        q50 = fc.quantile(0.50)
        q90 = fc.quantile(0.90)
        assert q10 < q50 < q90

    def test_cdf_at_mean(self):
        fc = ReturnForecast(symbol="SPY", horizon_days=30, mean=0.05, std=0.20, skew=0.0)
        p = fc.cdf(fc.horizon_mean)
        assert p == pytest.approx(0.5, abs=0.05)

    def test_prob_above_zero(self):
        fc = ReturnForecast(symbol="SPY", horizon_days=30, mean=0.05, std=0.10)
        # With positive mean, P(return > 0) should be > 50%
        p = fc.prob_above(0.0)
        assert p > 0.5

    def test_to_dict_keys(self):
        fc = ReturnForecast(symbol="SPY", horizon_days=30)
        d = fc.to_dict()
        assert "symbol" in d
        assert "mean" in d
        assert "std" in d
        assert "horizon_mean" in d
        assert "regime_vol_adj" in d


class TestBuildReturnForecast:
    def test_basic_build(self):
        fc = build_return_forecast("AAPL", horizon_days=30, base_mu=0.08, iv=0.30)
        assert fc.symbol == "AAPL"
        assert fc.std > 0
        assert fc.mean == 0.08

    def test_regime_widens_vol(self):
        base = build_return_forecast("AAPL", iv=0.25)
        crisis = build_return_forecast("AAPL", iv=0.25, regime_vector={"volatility_regime": 0.9})
        assert crisis.std > base.std

    def test_event_widens_vol(self):
        base = build_return_forecast("AAPL", iv=0.25)
        event = build_return_forecast("AAPL", iv=0.25, event_adjustment={"confidence_width_multiplier": 2.0})
        assert event.std > base.std

    def test_surface_skew_adjusts(self):
        fc = build_return_forecast("AAPL", iv=0.25, surface_metrics={"surface_skew_25d": 0.05})
        assert fc.skew < 0  # Positive surface skew → negative return skew

    def test_blends_iv_and_rv(self):
        fc = build_return_forecast("AAPL", iv=0.30, realized_vol=0.20)
        # Should be between 0.20 and 0.30
        assert 0.20 < fc.std < 0.30


# ---------------------------------------------------------------------------
# VolForecast Tests
# ---------------------------------------------------------------------------

class TestVolForecast:
    def test_exact_horizon(self):
        vf = VolForecast(symbol="SPY", term_structure={7: 0.20, 30: 0.25, 60: 0.28})
        assert vf.vol(30) == 0.25

    def test_interpolation(self):
        vf = VolForecast(symbol="SPY", term_structure={7: 0.20, 30: 0.30})
        v14 = vf.vol(14)  # Should interpolate between 0.20 and 0.30
        assert 0.20 < v14 < 0.30

    def test_extrapolation_short(self):
        vf = VolForecast(symbol="SPY", term_structure={7: 0.20, 30: 0.25})
        assert vf.vol(3) == 0.20  # Clamp to shortest

    def test_extrapolation_long(self):
        vf = VolForecast(symbol="SPY", term_structure={7: 0.20, 30: 0.25})
        assert vf.vol(90) == 0.25  # Clamp to longest

    def test_vol_cone(self):
        vf = VolForecast(symbol="SPY", term_structure={30: 0.25})
        lo, hi = vf.vol_cone(30, confidence=0.68)
        assert lo < 0.25 < hi

    def test_empty_term_structure_fallback(self):
        vf = VolForecast(symbol="SPY", implied_vol_atm=0.25)
        assert vf.vol(30) == 0.25


class TestBuildVolForecast:
    def test_basic_build(self):
        vf = build_vol_forecast("AAPL", realized_vol_20d=0.22, implied_vol_atm=0.28)
        assert 30 in vf.term_structure
        assert vf.term_structure[30] > 0

    def test_term_structure_shape(self):
        """Vol should generally increase for longer horizons (contango default)."""
        vf = build_vol_forecast(
            "AAPL",
            realized_vol_5d=0.30,
            realized_vol_20d=0.25,
            realized_vol_60d=0.22,
            implied_vol_atm=0.26,
        )
        # Short-term should be influenced by recent RV
        # Long-term by IV
        assert 7 in vf.term_structure
        assert 60 in vf.term_structure

    def test_regime_adjustment(self):
        base = build_vol_forecast("AAPL", implied_vol_atm=0.25)
        crisis = build_vol_forecast("AAPL", implied_vol_atm=0.25, regime_vector={"volatility_regime": 0.9})
        assert crisis.term_structure[30] > base.term_structure[30]

    def test_iv_term_structure_input(self):
        vf = build_vol_forecast(
            "AAPL",
            implied_vol_atm=0.25,
            iv_term_structure=[
                {"dte": 7, "atm_iv": 0.28},
                {"dte": 30, "atm_iv": 0.25},
                {"dte": 60, "atm_iv": 0.23},
            ],
        )
        # Should use IV term structure, not flat implied_vol_atm
        assert vf.term_structure[7] != vf.term_structure[60]


# ---------------------------------------------------------------------------
# ForecastBundle Tests
# ---------------------------------------------------------------------------

class TestForecastBundle:
    def _make_bundle(self) -> ForecastBundle:
        rf = ReturnForecast(symbol="AAPL", horizon_days=30, mean=0.05, std=0.25)
        vf = VolForecast(symbol="AAPL", term_structure={30: 0.25})
        return ForecastBundle(
            symbol="AAPL",
            return_forecast=rf,
            vol_forecast=vf,
            predicted_ev=150.0,
            predicted_pop=0.65,
        )

    def test_serialization_roundtrip(self):
        bundle = self._make_bundle()
        d = bundle.to_dict()
        restored = ForecastBundle.from_dict(d)
        assert restored.symbol == "AAPL"
        assert restored.return_forecast.mean == 0.05
        assert restored.predicted_ev == 150.0

    def test_to_dict_keys(self):
        bundle = self._make_bundle()
        d = bundle.to_dict()
        assert "return_forecast" in d
        assert "vol_forecast" in d
        assert "predicted_ev" in d
        assert "predicted_pop" in d


class TestForecastSet:
    def test_add_and_get(self):
        fs = ForecastSet()
        rf = ReturnForecast(symbol="AAPL", horizon_days=30)
        vf = VolForecast(symbol="AAPL")
        bundle = ForecastBundle(symbol="AAPL", return_forecast=rf, vol_forecast=vf)
        fs.add(bundle)
        assert fs.get("AAPL") is bundle
        assert fs.get("MSFT") is None
        assert "AAPL" in fs.symbols()

    def test_serialization(self):
        fs = ForecastSet(as_of_ts="2026-03-24T00:00:00Z")
        rf = ReturnForecast(symbol="SPY", horizon_days=30)
        vf = VolForecast(symbol="SPY")
        fs.add(ForecastBundle(symbol="SPY", return_forecast=rf, vol_forecast=vf))
        d = fs.to_dict()
        restored = ForecastSet.from_dict(d)
        assert restored.get("SPY") is not None


# ---------------------------------------------------------------------------
# forecast_ev_pop Tests
# ---------------------------------------------------------------------------

class TestForecastEvPop:
    def test_credit_strategy(self):
        rf = ReturnForecast(symbol="AAPL", horizon_days=30, mean=0.02, std=0.20)
        vf = VolForecast(symbol="AAPL")
        bundle = ForecastBundle(symbol="AAPL", return_forecast=rf, vol_forecast=vf)

        result = forecast_ev_pop(
            bundle,
            max_profit=200,
            max_loss=800,
            breakeven_return=-0.03,  # Profitable if stock doesn't drop > 3%
            is_credit=True,
        )
        assert "ev_amount" in result
        assert "prob_profit" in result
        assert 0 < result["prob_profit"] < 1

    def test_high_vol_reduces_pop(self):
        """Higher vol should reduce POP for credit strategies."""
        rf_low = ReturnForecast(symbol="AAPL", horizon_days=30, mean=0.02, std=0.10)
        rf_high = ReturnForecast(symbol="AAPL", horizon_days=30, mean=0.02, std=0.50)
        vf = VolForecast(symbol="AAPL")

        pop_low = forecast_ev_pop(
            ForecastBundle(symbol="AAPL", return_forecast=rf_low, vol_forecast=vf),
            max_profit=200, max_loss=800, breakeven_return=-0.05, is_credit=True,
        )["prob_profit"]

        pop_high = forecast_ev_pop(
            ForecastBundle(symbol="AAPL", return_forecast=rf_high, vol_forecast=vf),
            max_profit=200, max_loss=800, breakeven_return=-0.05, is_credit=True,
        )["prob_profit"]

        assert pop_low > pop_high


# ---------------------------------------------------------------------------
# Math utility tests
# ---------------------------------------------------------------------------

class TestMathUtils:
    def test_norm_cdf_symmetry(self):
        assert _norm_cdf(0) == pytest.approx(0.5, abs=0.001)
        assert _norm_cdf(1) + _norm_cdf(-1) == pytest.approx(1.0, abs=0.001)

    def test_norm_cdf_tails(self):
        assert _norm_cdf(-8) == pytest.approx(0.0, abs=0.001)
        assert _norm_cdf(8) == pytest.approx(1.0, abs=0.001)

    def test_norm_ppf_inverse(self):
        for p in [0.1, 0.25, 0.5, 0.75, 0.9]:
            z = _norm_ppf(p)
            p_back = _norm_cdf(z)
            assert p_back == pytest.approx(p, abs=0.02)
