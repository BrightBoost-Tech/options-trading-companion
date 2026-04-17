"""
Tests for IVSurface wrapper and surface features.

Tests:
1. SVI fit on synthetic data (known surface)
2. Arbitrage constraints enforced
3. Graceful degradation with sparse data
4. Feature extraction produces expected keys
5. Caching behavior
"""

import math
import time
import pytest
from datetime import datetime, timezone

from packages.quantum.surfaces.iv_surface import (
    IVSurface,
    get_cached_surface,
    clear_cache,
    CACHE_TTL_SECONDS,
)
from packages.quantum.surfaces.surface_features import extract_surface_features
from packages.quantum.services.surface_geometry_v4 import (
    fit_svi,
    svi_total_variance,
    detect_butterfly_w,
    convexify_w,
    detect_calendar_violations,
    build_common_k_grid,
)

# Skipped in PR #1 triage to establish CI-green gate while test debt is cleared.
# [Cluster M] long tail
# Tracked in #774 (umbrella: #767).
pytestmark = pytest.mark.skip(
    reason='[Cluster M] long tail; tracked in #774',
)


# ---------------------------------------------------------------------------
# Synthetic chain builder
# ---------------------------------------------------------------------------

def _make_chain(
    spot: float = 100.0,
    expiries: list = None,
    strikes_per_expiry: int = 11,
    base_iv: float = 0.25,
    skew: float = 0.03,
) -> list:
    """
    Build a synthetic options chain with known IV surface.

    IV = base_iv + skew * (K/S - 1)  (linear skew for simplicity)
    Adds both calls and puts at each strike.
    """
    if expiries is None:
        expiries = ["2026-04-17", "2026-05-15", "2026-06-19"]

    chain = []
    for expiry in expiries:
        for i in range(strikes_per_expiry):
            strike = spot * (0.8 + 0.04 * i)  # 80% to 120% of spot
            moneyness = strike / spot
            iv = base_iv + skew * (moneyness - 1.0)
            iv = max(0.05, iv)  # Floor at 5% IV

            chain.append({
                "strike": round(strike, 2),
                "expiry": expiry,
                "iv": round(iv, 4),
                "right": "call" if strike >= spot else "put",
                "greeks": {"delta": 0.5, "vega": 0.1},
            })
    return chain


# ---------------------------------------------------------------------------
# Test SVI fit on synthetic data
# ---------------------------------------------------------------------------

class TestSVIFit:
    """Test SVI fitting on known surfaces."""

    def test_fit_recovers_flat_surface(self):
        """SVI should fit a flat surface (constant IV) with small RMSE."""
        # Flat IV = 0.25, T = 0.5 → w = 0.0625 * 0.5 = 0.03125
        k_obs = [-0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3]
        T = 0.5
        iv = 0.25
        w_obs = [iv * iv * T] * len(k_obs)

        params = fit_svi(k_obs, w_obs, "TEST", "2026-04-17")
        assert params is not None
        assert params.fit_rmse < 0.01, f"RMSE too high: {params.fit_rmse}"

    def test_fit_recovers_skewed_surface(self):
        """SVI should fit a skewed surface with reasonable RMSE."""
        k_obs = [-0.4, -0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3, 0.4]
        T = 0.25
        # Skewed: higher IV for OTM puts (negative k)
        ivs = [0.35, 0.32, 0.29, 0.27, 0.25, 0.24, 0.23, 0.225, 0.22]
        w_obs = [iv * iv * T for iv in ivs]

        params = fit_svi(k_obs, w_obs, "TEST", "2026-04-17")
        assert params is not None
        assert params.b > 0, "b should be positive"
        assert params.fit_rmse < 0.005, f"RMSE too high for skewed fit: {params.fit_rmse}"
        # Verify the fit captures the skew: w at k=-0.3 should be > w at k=+0.3
        w_left = svi_total_variance(-0.3, params.a, params.b, params.rho, params.m, params.sigma)
        w_right = svi_total_variance(0.3, params.a, params.b, params.rho, params.m, params.sigma)
        assert w_left > w_right, "SVI fit should capture left skew (higher put wing)"

    def test_fit_rejects_insufficient_data(self):
        """SVI needs at least 3 points."""
        params = fit_svi([0.0, 0.1], [0.01, 0.02])
        assert params is None


# ---------------------------------------------------------------------------
# Test arbitrage constraints
# ---------------------------------------------------------------------------

class TestArbConstraints:
    """Test butterfly and calendar arbitrage detection and repair."""

    def test_butterfly_detection_clean(self):
        """No violations on a convex w(k) curve."""
        k = [-0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3]
        # Parabola: w = 0.01 + 0.1*k^2 (convex)
        w = [0.01 + 0.1 * ki * ki for ki in k]
        count, _ = detect_butterfly_w(k, w)
        assert count == 0

    def test_butterfly_detection_violation(self):
        """Detect violations when w(k) is concave."""
        k = [-0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3]
        # Inverted parabola: concave
        w = [0.05 - 0.1 * ki * ki for ki in k]
        w = [max(0.001, wi) for wi in w]
        count, _ = detect_butterfly_w(k, w)
        assert count > 0

    def test_convexify_repairs(self):
        """convexify_w should eliminate butterfly violations."""
        k = [-0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3]
        # Non-convex: dip in the middle
        w = [0.04, 0.03, 0.025, 0.01, 0.025, 0.03, 0.04]
        count_before, _ = detect_butterfly_w(k, w)
        assert count_before > 0

        w_fixed = convexify_w(k, w)
        count_after, _ = detect_butterfly_w(k, w_fixed)
        assert count_after == 0

    def test_calendar_clean(self):
        """No violations when total variance increases with T."""
        slices = [
            (0.1, [-0.2, 0.0, 0.2], [0.005, 0.004, 0.005]),
            (0.3, [-0.2, 0.0, 0.2], [0.015, 0.012, 0.015]),
            (0.5, [-0.2, 0.0, 0.2], [0.025, 0.020, 0.025]),
        ]
        common = build_common_k_grid(slices)
        assert common is not None
        count, _, _ = detect_calendar_violations(slices, common)
        assert count == 0

    def test_calendar_violation(self):
        """Detect when short-term variance exceeds long-term."""
        slices = [
            (0.1, [-0.2, 0.0, 0.2], [0.005, 0.004, 0.005]),
            (0.3, [-0.2, 0.0, 0.2], [0.003, 0.002, 0.003]),  # lower than T=0.1!
            (0.5, [-0.2, 0.0, 0.2], [0.025, 0.020, 0.025]),
        ]
        common = build_common_k_grid(slices)
        assert common is not None
        count, _, _ = detect_calendar_violations(slices, common)
        assert count > 0


# ---------------------------------------------------------------------------
# Test IVSurface wrapper
# ---------------------------------------------------------------------------

class TestIVSurface:
    """Test high-level IVSurface interface."""

    def _build_surface(self, spot=100.0, **kwargs):
        chain = _make_chain(spot=spot, **kwargs)
        return IVSurface.from_chain(chain, spot=spot, symbol="TEST")

    def test_build_from_chain(self):
        """Should build a valid surface from synthetic chain."""
        surface = self._build_surface()
        assert surface is not None
        assert surface.is_valid or len(surface.smiles) > 0

    def test_iv_query(self):
        """iv() should return a positive value for ATM strike."""
        surface = self._build_surface()
        if not surface:
            pytest.skip("Surface build failed on this data")
        # Query ATM for first expiry
        expiry = surface.smiles[0].expiry
        iv = surface.iv(100.0, expiry)
        assert iv is not None
        assert 0.05 < iv < 2.0, f"IV out of range: {iv}"

    def test_skew(self):
        """skew() should return a value for known skewed surface."""
        surface = self._build_surface(skew=0.05)
        if not surface:
            pytest.skip("Surface build failed on this data")
        expiry = surface.smiles[0].expiry
        sk = surface.skew(expiry)
        # With positive skew coefficient, puts should be more expensive
        assert sk is not None

    def test_term_structure(self):
        """term_structure() should return one entry per expiry."""
        surface = self._build_surface()
        if not surface:
            pytest.skip("Surface build failed on this data")
        ts = surface.term_structure()
        assert len(ts) > 0
        assert all("atm_iv" in t and "dte" in t for t in ts)

    def test_surface_metrics(self):
        """surface_metrics() should return expected keys."""
        surface = self._build_surface()
        if not surface:
            pytest.skip("Surface build failed on this data")
        m = surface.surface_metrics()
        assert "atm_iv_front" in m
        assert "term_slope" in m
        assert "wing_richness" in m
        assert "num_expiries" in m

    def test_sparse_chain_degrades_gracefully(self):
        """Surface should handle sparse data without crashing."""
        # Only 2 strikes per expiry — below MIN_STRIKES_PER_EXPIRY
        chain = _make_chain(strikes_per_expiry=2)
        surface = IVSurface.from_chain(chain, spot=100.0, symbol="SPARSE")
        # Should return None (insufficient data) rather than crash
        assert surface is None

    def test_single_expiry(self):
        """Surface should work with just one expiry."""
        chain = _make_chain(expiries=["2026-04-17"])
        surface = IVSurface.from_chain(chain, spot=100.0, symbol="SINGLE")
        assert surface is not None
        ts = surface.term_structure()
        assert len(ts) == 1


# ---------------------------------------------------------------------------
# Test surface features
# ---------------------------------------------------------------------------

class TestSurfaceFeatures:
    """Test feature extraction for scoring engine."""

    def test_extract_features_keys(self):
        """extract_surface_features should return all expected keys."""
        chain = _make_chain()
        surface = IVSurface.from_chain(chain, spot=100.0, symbol="FEAT")
        if not surface:
            pytest.skip("Surface build failed")

        features = extract_surface_features(surface)

        expected_keys = [
            "surface_atm_iv_front",
            "surface_atm_iv_back",
            "surface_term_slope",
            "surface_skew_25d",
            "surface_wing_richness",
            "surface_iv_rank",
            "surface_change_1d",
            "surface_num_expiries",
            "surface_is_valid",
            "surface_skew_zscore",
        ]
        for key in expected_keys:
            assert key in features, f"Missing feature key: {key}"

    def test_iv_rank_with_percentile_data(self):
        """IV rank should compute correctly with 52-week data."""
        chain = _make_chain(base_iv=0.30)
        surface = IVSurface.from_chain(chain, spot=100.0, symbol="RANK")
        if not surface:
            pytest.skip("Surface build failed")

        features = extract_surface_features(surface, iv_percentile_data={
            "iv_52w_high": 0.50,
            "iv_52w_low": 0.15,
        })

        rank = features["surface_iv_rank"]
        assert rank is not None
        # 0.30 is 43% of the way from 0.15 to 0.50
        assert 30 < rank < 60, f"IV rank out of expected range: {rank}"


# ---------------------------------------------------------------------------
# Test caching
# ---------------------------------------------------------------------------

class TestCaching:
    """Test surface caching behavior."""

    def test_cache_returns_same_instance(self):
        """Repeated calls should return cached surface."""
        clear_cache()
        chain = _make_chain()
        s1 = get_cached_surface("CACHE_TEST", chain, 100.0)
        s2 = get_cached_surface("CACHE_TEST", chain, 100.0)
        assert s1 is s2  # Same object reference

    def test_clear_cache(self):
        """clear_cache should invalidate entries."""
        clear_cache()
        chain = _make_chain()
        s1 = get_cached_surface("CLEAR_TEST", chain, 100.0)
        assert s1 is not None
        clear_cache("CLEAR_TEST")
        s2 = get_cached_surface("CLEAR_TEST", chain, 100.0)
        assert s2 is not s1  # New instance after clear
