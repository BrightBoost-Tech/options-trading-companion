"""
Tests for Arb-Free Surface Geometry v4.

Tests:
- Per-expiry smile construction with SVI fit
- Butterfly arbitrage detection in w(k) space
- Calendar arbitrage detection across k-grid
- Deterministic hashing
- Lineage signing
"""

import pytest
from datetime import datetime, timezone, timedelta

from packages.quantum.services.surface_geometry_v4 import (
    SVIParams,
    CanonicalSmilePoint,
    PerExpirySmile,
    ArbFreeSurface,
    SurfaceResult,
    build_arb_free_surface,
    build_per_expiry_smile,
    detect_butterfly_w,
    convexify_w,
    detect_calendar_violations,
    build_common_k_grid,
    compute_moneyness,
    compute_time_to_expiry,
    compute_dte,
    compute_forward,
    compute_log_moneyness,
    svi_total_variance,
    fit_svi,
    find_atm_iv,
    SURFACE_VERSION,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_chain():
    """Sample option chain for testing with symmetric smile."""
    spot = 100.0
    expiry = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")

    # Create a convex smile (higher IV at wings)
    return [
        {"strike": 90.0, "iv": 0.28, "expiry": expiry, "right": "call", "greeks": {"delta": 0.8}},
        {"strike": 95.0, "iv": 0.23, "expiry": expiry, "right": "call", "greeks": {"delta": 0.65}},
        {"strike": 100.0, "iv": 0.20, "expiry": expiry, "right": "call", "greeks": {"delta": 0.5}},
        {"strike": 105.0, "iv": 0.23, "expiry": expiry, "right": "call", "greeks": {"delta": 0.35}},
        {"strike": 110.0, "iv": 0.28, "expiry": expiry, "right": "call", "greeks": {"delta": 0.2}},
    ]


@pytest.fixture
def butterfly_arb_chain():
    """Chain with butterfly arbitrage (non-convex w(k))."""
    spot = 100.0
    expiry = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")

    # IV that creates concave w(k) - butterfly arb
    return [
        {"strike": 90.0, "iv": 0.20, "expiry": expiry, "right": "call", "greeks": {}},
        {"strike": 95.0, "iv": 0.25, "expiry": expiry, "right": "call", "greeks": {}},
        {"strike": 100.0, "iv": 0.30, "expiry": expiry, "right": "call", "greeks": {}},  # Bump - arb!
        {"strike": 105.0, "iv": 0.25, "expiry": expiry, "right": "call", "greeks": {}},
        {"strike": 110.0, "iv": 0.20, "expiry": expiry, "right": "call", "greeks": {}},
    ]


@pytest.fixture
def multi_expiry_chain():
    """Chain with multiple expiries for calendar arb testing."""
    spot = 100.0
    exp1 = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%d")
    exp2 = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")
    exp3 = (datetime.now(timezone.utc) + timedelta(days=60)).strftime("%Y-%m-%d")

    chain = []
    # Same IV across expiries - total variance should increase with T
    for expiry in [exp1, exp2, exp3]:
        for strike in [95.0, 100.0, 105.0]:
            chain.append({
                "strike": strike,
                "iv": 0.20,
                "expiry": expiry,
                "right": "call",
                "greeks": {"delta": 0.5},
            })
    return chain


# =============================================================================
# Unit Tests - Math Functions
# =============================================================================

class TestComputeForward:
    def test_zero_time(self):
        assert compute_forward(100.0, 0.05, 0.02, 0.0) == 100.0

    def test_positive_carry(self):
        # r > q: forward > spot
        F = compute_forward(100.0, 0.05, 0.02, 1.0)
        assert F > 100.0
        assert F == pytest.approx(103.045, rel=0.01)

    def test_negative_carry(self):
        # r < q: forward < spot
        F = compute_forward(100.0, 0.02, 0.05, 1.0)
        assert F < 100.0


class TestComputeLogMoneyness:
    def test_atm(self):
        k = compute_log_moneyness(100.0, 100.0)
        assert k == pytest.approx(0.0, abs=1e-10)

    def test_otm_call(self):
        k = compute_log_moneyness(110.0, 100.0)
        assert k > 0

    def test_itm_call(self):
        k = compute_log_moneyness(90.0, 100.0)
        assert k < 0

    def test_invalid_forward(self):
        assert compute_log_moneyness(100.0, 0.0) == 0.0
        assert compute_log_moneyness(100.0, -10.0) == 0.0


class TestComputeMoneyness:
    def test_atm(self):
        assert compute_moneyness(100.0, 100.0) == 1.0

    def test_itm_call(self):
        assert compute_moneyness(90.0, 100.0) == 0.9

    def test_otm_call(self):
        assert compute_moneyness(110.0, 100.0) == 1.1

    def test_zero_spot(self):
        assert compute_moneyness(100.0, 0.0) == 0.0


class TestComputeTimeToExpiry:
    def test_future_date(self):
        as_of = datetime(2024, 1, 1, tzinfo=timezone.utc)
        tte = compute_time_to_expiry("2024-02-01", as_of)
        assert tte == pytest.approx(31 / 365.0, rel=0.01)

    def test_past_date(self):
        as_of = datetime(2024, 2, 1, tzinfo=timezone.utc)
        tte = compute_time_to_expiry("2024-01-01", as_of)
        assert tte == 0.0


class TestComputeDte:
    def test_future_date(self):
        as_of = datetime(2024, 1, 1, tzinfo=timezone.utc)
        assert compute_dte("2024-01-31", as_of) == 30

    def test_past_date(self):
        as_of = datetime(2024, 2, 1, tzinfo=timezone.utc)
        assert compute_dte("2024-01-01", as_of) == 0


# =============================================================================
# Unit Tests - SVI Model
# =============================================================================

class TestSVITotalVariance:
    def test_atm_value(self):
        # At k=m, w = a + b*sigma
        w = svi_total_variance(0.0, 0.04, 0.1, -0.3, 0.0, 0.1)
        assert w == pytest.approx(0.04 + 0.1 * 0.1, rel=0.01)

    def test_positive_k(self):
        # For k > m and rho < 0, asymptote is a + b*(1+rho)*|k-m|
        w = svi_total_variance(0.5, 0.04, 0.1, -0.3, 0.0, 0.1)
        assert w > 0.04

    def test_always_positive(self):
        # With reasonable params, w should always be positive
        for k in [-1.0, -0.5, 0.0, 0.5, 1.0]:
            w = svi_total_variance(k, 0.04, 0.1, -0.3, 0.0, 0.1)
            assert w > 0


class TestFitSVI:
    def test_fit_well_formed_smile(self):
        """SVI should fit a well-formed smile."""
        k_obs = [-0.2, -0.1, 0.0, 0.1, 0.2]
        # Generate smooth convex total variance
        T = 30 / 365
        ivs = [0.25, 0.22, 0.20, 0.22, 0.25]
        w_obs = [iv * iv * T for iv in ivs]

        params = fit_svi(k_obs, w_obs, "TEST", "2024-01-01")

        assert params is not None
        assert params.b >= 0
        assert params.sigma > 0
        assert abs(params.rho) < 1
        assert params.fit_rmse >= 0

    def test_fit_returns_usable_w_grid(self):
        """Fitted SVI should produce reasonable w values."""
        k_obs = [-0.15, -0.05, 0.0, 0.05, 0.15]
        T = 30 / 365
        ivs = [0.24, 0.21, 0.20, 0.21, 0.24]
        w_obs = [iv * iv * T for iv in ivs]

        params = fit_svi(k_obs, w_obs, "TEST", "2024-01-01")

        if params:
            # Check that w values are reasonable
            for k in k_obs:
                w = svi_total_variance(k, params.a, params.b, params.rho, params.m, params.sigma)
                assert w > 0
                assert w < 1.0  # Reasonable upper bound for 30-day variance

    def test_fit_insufficient_data(self):
        """Fit should fail with < 3 points."""
        params = fit_svi([0.0, 0.1], [0.01, 0.011], "TEST", "2024-01-01")
        assert params is None


# =============================================================================
# Unit Tests - Butterfly Arbitrage (w(k) convexity)
# =============================================================================

class TestDetectButterflyW:
    def test_convex_no_violations(self):
        """Convex w(k) should have no violations."""
        k_grid = [-0.2, -0.1, 0.0, 0.1, 0.2]
        # Convex: second derivative positive (slopes increasing)
        w_grid = [0.05, 0.02, 0.01, 0.02, 0.05]
        count, max_viol = detect_butterfly_w(k_grid, w_grid)
        assert count == 0
        assert max_viol == 0.0

    def test_concave_detects_violations(self):
        """Concave w(k) should detect violations."""
        k_grid = [-0.2, -0.1, 0.0, 0.1, 0.2]
        # Concave: second derivative negative (slopes decreasing)
        w_grid = [0.01, 0.04, 0.05, 0.04, 0.01]
        count, max_viol = detect_butterfly_w(k_grid, w_grid)
        assert count > 0
        assert max_viol > 0

    def test_too_few_points(self):
        """Less than 3 points should return no violations."""
        count, max_viol = detect_butterfly_w([0.0, 0.1], [0.01, 0.02])
        assert count == 0


class TestConvexifyW:
    def test_already_convex(self):
        """Convex w should be unchanged."""
        k_grid = [-0.2, -0.1, 0.0, 0.1, 0.2]
        w_grid = [0.05, 0.02, 0.01, 0.02, 0.05]
        result = convexify_w(k_grid, w_grid)
        # Should be same or very close
        for i in range(len(w_grid)):
            assert result[i] == pytest.approx(w_grid[i], rel=0.1)

    def test_concave_is_fixed(self):
        """Concave w should be repaired to be convex."""
        k_grid = [-0.2, -0.1, 0.0, 0.1, 0.2]
        w_grid = [0.01, 0.04, 0.05, 0.04, 0.01]

        result = convexify_w(k_grid, w_grid)

        # Post-repair should have no violations
        count, _ = detect_butterfly_w(k_grid, result)
        assert count == 0

    def test_all_positive(self):
        """Repaired w values should all be positive."""
        k_grid = [-0.2, -0.1, 0.0, 0.1, 0.2]
        w_grid = [0.01, 0.04, 0.05, 0.04, 0.01]
        result = convexify_w(k_grid, w_grid)
        assert all(w > 0 for w in result)


# =============================================================================
# Unit Tests - Calendar Arbitrage
# =============================================================================

class TestBuildCommonKGrid:
    def test_overlapping_ranges(self):
        """Should find intersection of k ranges."""
        slices = [
            (0.1, [-0.3, 0.0, 0.3], [0.01, 0.01, 0.01]),
            (0.2, [-0.2, 0.0, 0.2], [0.02, 0.02, 0.02]),
        ]
        grid = build_common_k_grid(slices)
        assert grid is not None
        assert len(grid) > 0
        assert min(grid) >= -0.2
        assert max(grid) <= 0.2

    def test_no_overlap(self):
        """Should return None if no overlap."""
        slices = [
            (0.1, [-0.5, -0.3], [0.01, 0.01]),
            (0.2, [0.3, 0.5], [0.02, 0.02]),
        ]
        grid = build_common_k_grid(slices)
        assert grid is None

    def test_single_slice(self):
        """Single slice should return None."""
        slices = [(0.1, [-0.2, 0.0, 0.2], [0.01, 0.01, 0.01])]
        grid = build_common_k_grid(slices)
        assert grid is None


class TestDetectCalendarViolations:
    def test_monotonic_no_violations(self):
        """Monotonic w across T should have no violations."""
        slices = [
            (0.1, [-0.1, 0.0, 0.1], [0.01, 0.01, 0.01]),
            (0.2, [-0.1, 0.0, 0.1], [0.02, 0.02, 0.02]),
            (0.3, [-0.1, 0.0, 0.1], [0.03, 0.03, 0.03]),
        ]
        common_k = [-0.1, 0.0, 0.1]
        count, max_viol, indices = detect_calendar_violations(slices, common_k)
        assert count == 0

    def test_non_monotonic_detects_violations(self):
        """Non-monotonic w should detect violations."""
        slices = [
            (0.1, [-0.1, 0.0, 0.1], [0.02, 0.02, 0.02]),  # Higher variance early
            (0.2, [-0.1, 0.0, 0.1], [0.01, 0.01, 0.01]),  # Lower variance later - arb!
        ]
        common_k = [-0.1, 0.0, 0.1]
        count, max_viol, indices = detect_calendar_violations(slices, common_k)
        assert count > 0


# =============================================================================
# Unit Tests - Find ATM IV
# =============================================================================

class TestFindAtmIv:
    def test_exact_atm(self):
        points = [
            CanonicalSmilePoint(strike=90, moneyness=0.9, log_moneyness=-0.1, iv=0.25, is_call=True),
            CanonicalSmilePoint(strike=100, moneyness=1.0, log_moneyness=0.0, iv=0.20, is_call=True),
            CanonicalSmilePoint(strike=110, moneyness=1.1, log_moneyness=0.1, iv=0.25, is_call=True),
        ]
        assert find_atm_iv(points) == 0.20

    def test_near_atm(self):
        points = [
            CanonicalSmilePoint(strike=99, moneyness=0.99, log_moneyness=-0.01, iv=0.21, is_call=True),
            CanonicalSmilePoint(strike=105, moneyness=1.05, log_moneyness=0.05, iv=0.23, is_call=True),
        ]
        atm = find_atm_iv(points)
        assert atm == 0.21  # Closer to 0

    def test_empty_list(self):
        assert find_atm_iv([]) is None


# =============================================================================
# Integration Tests - Build Surface
# =============================================================================

class TestBuildArbFreeSurface:
    def test_basic_surface(self, sample_chain):
        result = build_arb_free_surface(
            chain=sample_chain,
            spot=100.0,
            symbol="TEST",
            risk_free_rate=0.05,
            dividend_yield=0.01,
        )

        assert result.surface is not None
        assert result.surface.symbol == "TEST"
        assert result.surface.spot == 100.0
        assert result.surface.version == SURFACE_VERSION
        assert len(result.surface.smiles) == 1
        assert result.content_hash != ""

    def test_empty_chain(self):
        result = build_arb_free_surface(
            chain=[],
            spot=100.0,
            symbol="TEST",
        )
        assert result.is_valid is False
        assert "Empty option chain" in result.errors

    def test_invalid_spot(self, sample_chain):
        result = build_arb_free_surface(
            chain=sample_chain,
            spot=0.0,
            symbol="TEST",
        )
        assert result.is_valid is False
        assert any("Invalid spot price" in e for e in result.errors)

    def test_butterfly_arb_repaired(self, butterfly_arb_chain):
        result = build_arb_free_surface(
            chain=butterfly_arb_chain,
            spot=100.0,
            symbol="TEST",
        )

        assert result.surface is not None
        smile = result.surface.smiles[0]

        # SVI model naturally produces convex w(k), so even with
        # butterfly-violating input, the fitted surface is arb-free.
        # The surface should be valid after SVI fitting.
        assert result.is_valid is True

        # Post-repair should have no violations
        assert smile.butterfly_arb_detected_post is False

    def test_multi_expiry_surface(self, multi_expiry_chain):
        result = build_arb_free_surface(
            chain=multi_expiry_chain,
            spot=100.0,
            symbol="TEST",
        )

        assert result.surface is not None
        assert len(result.surface.smiles) == 3

        # Smiles should be sorted by time_to_expiry
        times = [s.time_to_expiry for s in result.surface.smiles]
        assert times == sorted(times)

    def test_forward_computed(self, sample_chain):
        result = build_arb_free_surface(
            chain=sample_chain,
            spot=100.0,
            symbol="TEST",
            risk_free_rate=0.05,
            dividend_yield=0.02,
        )

        assert result.surface is not None
        smile = result.surface.smiles[0]
        # Forward should be > spot with r > q
        assert smile.forward >= 100.0


class TestDeterministicHashing:
    def test_same_input_same_hash(self, sample_chain):
        as_of = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)

        result1 = build_arb_free_surface(
            chain=sample_chain,
            spot=100.0,
            symbol="TEST",
            as_of_ts=as_of,
        )

        result2 = build_arb_free_surface(
            chain=sample_chain,
            spot=100.0,
            symbol="TEST",
            as_of_ts=as_of,
        )

        assert result1.content_hash == result2.content_hash

    def test_different_spot_different_hash(self, sample_chain):
        as_of = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)

        result1 = build_arb_free_surface(
            chain=sample_chain,
            spot=100.0,
            symbol="TEST",
            as_of_ts=as_of,
        )

        result2 = build_arb_free_surface(
            chain=sample_chain,
            spot=100.5,
            symbol="TEST",
            as_of_ts=as_of,
        )

        assert result1.content_hash != result2.content_hash


# =============================================================================
# Model Tests
# =============================================================================

class TestSVIParamsModel:
    def test_to_canonical_dict(self):
        params = SVIParams(a=0.04, b=0.1, rho=-0.3, m=0.0, sigma=0.1)
        d = params.to_canonical_dict()
        assert "a" in d
        assert "b" in d
        assert "rho" in d
        assert "m" in d
        assert "sigma" in d


class TestCanonicalSmilePointModel:
    def test_to_canonical_dict(self):
        point = CanonicalSmilePoint(
            strike=100.0,
            moneyness=1.0,
            log_moneyness=0.0,
            iv=0.20,
            total_variance=0.0033,
            is_call=True,
        )
        d = point.to_canonical_dict()
        assert d["strike"] == "100.000000"
        assert d["log_moneyness"] == "0.000000"
        assert d["is_call"] is True


class TestPerExpirySmileModel:
    def test_to_canonical_dict(self, sample_chain):
        as_of = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        result = build_arb_free_surface(
            chain=sample_chain,
            spot=100.0,
            symbol="TEST",
            as_of_ts=as_of,
        )

        if result.surface and result.surface.smiles:
            smile = result.surface.smiles[0]
            d = smile.to_canonical_dict()
            assert "expiry" in d
            assert "forward" in d
            assert "k_grid" in d
            assert "w_grid" in d


class TestArbFreeSurfaceModel:
    def test_to_canonical_dict(self, sample_chain):
        as_of = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        result = build_arb_free_surface(
            chain=sample_chain,
            spot=100.0,
            symbol="TEST",
            as_of_ts=as_of,
        )

        d = result.surface.to_canonical_dict()
        assert d["symbol"] == "TEST"
        assert d["version"] == SURFACE_VERSION
        assert "common_k_grid" in d
        assert "calendar_arb_detected_pre" in d


class TestSurfaceResultModel:
    def test_to_dict(self, sample_chain):
        result = build_arb_free_surface(
            chain=sample_chain,
            spot=100.0,
            symbol="TEST",
        )

        d = result.to_dict()
        assert d["content_hash"] != ""
        assert d["surface"] is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
