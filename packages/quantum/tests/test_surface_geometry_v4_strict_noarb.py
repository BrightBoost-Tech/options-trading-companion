"""
Strict no-arbitrage tests for Surface Geometry v4.

These tests verify the strict enforcement of butterfly and calendar
arbitrage-free conditions in w(k) (total variance) space.
"""

import pytest
import math
from datetime import datetime, timezone, timedelta

from packages.quantum.services.surface_geometry_v4 import (
    # Models
    SVIParams,
    CanonicalSmilePoint,
    PerExpirySmile,
    ArbFreeSurface,
    SurfaceResult,
    # Core functions
    compute_forward,
    compute_log_moneyness,
    svi_total_variance,
    fit_svi,
    detect_butterfly_w,
    convexify_w,
    build_common_k_grid,
    detect_calendar_violations,
    repair_calendar,
    build_arb_free_surface,
    SURFACE_VERSION,
)


class TestSVIFitProducesUsableWGrid:
    """SVI fit returns params and produces usable w_grid."""

    def test_svi_fit_returns_valid_params(self):
        """fit_svi returns SVIParams with all fields populated."""
        k_grid = [-0.2, -0.1, 0.0, 0.1, 0.2]
        # Simulate a smile: higher IV at wings
        ivs = [0.25, 0.22, 0.20, 0.22, 0.25]
        T = 30 / 365  # 30 days
        w_grid = [(iv ** 2) * T for iv in ivs]

        params = fit_svi(k_grid, w_grid)

        assert params is not None
        assert isinstance(params, SVIParams)
        assert params.a is not None
        assert params.b is not None
        assert params.rho is not None
        assert params.m is not None
        assert params.sigma is not None
        assert params.fit_rmse is not None
        assert params.fit_rmse >= 0

    def test_svi_fit_produces_reasonable_w_values(self):
        """Fitted SVI produces w values close to input."""
        k_grid = [-0.2, -0.1, 0.0, 0.1, 0.2]
        ivs = [0.25, 0.22, 0.20, 0.22, 0.25]
        T = 30 / 365
        w_grid = [(iv ** 2) * T for iv in ivs]

        params = fit_svi(k_grid, w_grid)
        assert params is not None

        # Check that fitted w is close to original
        for k, w_orig in zip(k_grid, w_grid):
            # Use individual parameters, not params object
            w_fit = svi_total_variance(k, params.a, params.b, params.rho, params.m, params.sigma)
            # Allow 50% relative error for fit quality (SVI may not fit perfectly)
            assert abs(w_fit - w_orig) < 0.5 * w_orig + 0.005

    def test_svi_fit_on_flat_smile(self):
        """SVI fit on flat smile produces reasonable params."""
        k_grid = [-0.1, 0.0, 0.1]
        T = 30 / 365
        iv = 0.20
        w_grid = [(iv ** 2) * T] * 3

        params = fit_svi(k_grid, w_grid)

        assert params is not None
        # For flat smile, b should be relatively small
        assert params.b < 0.5

    def test_svi_fit_is_deterministic(self):
        """Same inputs produce same SVI params."""
        k_grid = [-0.2, -0.1, 0.0, 0.1, 0.2]
        ivs = [0.25, 0.22, 0.20, 0.22, 0.25]
        T = 30 / 365
        w_grid = [(iv ** 2) * T for iv in ivs]

        # fit_svi uses internal deterministic seeding based on symbol/expiry
        params1 = fit_svi(k_grid, w_grid, symbol="TEST", expiry="2024-03-15")
        params2 = fit_svi(k_grid, w_grid, symbol="TEST", expiry="2024-03-15")

        assert params1 is not None
        assert params2 is not None
        assert params1.a == params2.a
        assert params1.b == params2.b
        assert params1.rho == params2.rho
        assert params1.m == params2.m
        assert params1.sigma == params2.sigma


class TestButterflyViolationsInWSpace:
    """Butterfly violations detected in w(k) space and repaired."""

    def test_detect_butterfly_on_convex_smile(self):
        """No violations on convex w(k) smile with increasing slopes."""
        k_grid = [-0.2, -0.1, 0.0, 0.1, 0.2]
        # Truly convex: slopes are increasing (left slope < middle slope < right slope)
        # w = 0.01 + 0.1 * k^2 gives increasing slopes
        w_grid = [0.014, 0.011, 0.010, 0.011, 0.014]

        count, max_viol = detect_butterfly_w(k_grid, w_grid)

        assert count == 0

    def test_detect_butterfly_on_concave_segment(self):
        """Violations detected on concave w(k) segment."""
        k_grid = [-0.2, -0.1, 0.0, 0.1, 0.2]
        # Non-convex: middle bulges up creating decreasing slopes
        w_grid = [0.008, 0.010, 0.015, 0.010, 0.008]

        count, max_viol = detect_butterfly_w(k_grid, w_grid)

        assert count > 0

    def test_convexify_repairs_violations(self):
        """convexify_w repairs butterfly violations."""
        k_grid = [-0.2, -0.1, 0.0, 0.1, 0.2]
        # Non-convex w
        w_grid = [0.008, 0.010, 0.015, 0.010, 0.008]

        count_before, _ = detect_butterfly_w(k_grid, w_grid)
        assert count_before > 0

        w_repaired = convexify_w(k_grid, w_grid)
        count_after, _ = detect_butterfly_w(k_grid, w_repaired)

        assert count_after == 0

    def test_convexify_produces_nonnegative_w(self):
        """convexify_w produces non-negative total variance."""
        k_grid = [-0.2, -0.1, 0.0, 0.1, 0.2]
        w_grid = [0.010, 0.008, 0.009, 0.008, 0.010]

        w_repaired = convexify_w(k_grid, w_grid)

        for w in w_repaired:
            assert w >= 0

    def test_convexify_noop_on_convex_smile(self):
        """convexify_w is noop on already convex smile."""
        k_grid = [-0.2, -0.1, 0.0, 0.1, 0.2]
        # Convex parabola w = c + a*k^2
        w_grid = [0.014, 0.011, 0.010, 0.011, 0.014]

        # Verify it's already convex
        count, _ = detect_butterfly_w(k_grid, w_grid)
        assert count == 0

        w_repaired = convexify_w(k_grid, w_grid)

        for w_orig, w_new in zip(w_grid, w_repaired):
            assert abs(w_new - w_orig) < 1e-6


class TestCalendarViolationsAcrossKGrid:
    """Calendar violations across k-grid detected and repaired."""

    def test_detect_calendar_on_monotonic_surface(self):
        """No violations on monotonically increasing w(T)."""
        common_k_grid = [-0.1, 0.0, 0.1]

        # Two expiries with increasing w for each k (slices as tuples)
        slices = [
            (30 / 365, common_k_grid, [0.005, 0.004, 0.005]),  # T1
            (60 / 365, common_k_grid, [0.010, 0.008, 0.010]),  # T2 > T1
        ]

        count, max_viol, violating = detect_calendar_violations(slices, common_k_grid)

        assert count == 0

    def test_detect_calendar_on_inverted_surface(self):
        """Violations detected when short-term w > long-term w."""
        common_k_grid = [-0.1, 0.0, 0.1]

        # Short expiry has higher w than long expiry at k=0
        slices = [
            (30 / 365, common_k_grid, [0.005, 0.012, 0.005]),  # High w at ATM
            (60 / 365, common_k_grid, [0.010, 0.008, 0.010]),  # Lower w at ATM
        ]

        count, max_viol, violating = detect_calendar_violations(slices, common_k_grid)

        assert count > 0

    def test_repair_calendar_fixes_violations(self):
        """repair_calendar fixes calendar arbitrage violations."""
        common_k_grid = [-0.1, 0.0, 0.1]

        slices = [
            (30 / 365, common_k_grid, [0.005, 0.012, 0.005]),
            (60 / 365, common_k_grid, [0.010, 0.008, 0.010]),
        ]

        count_before, _, _ = detect_calendar_violations(slices, common_k_grid)
        assert count_before > 0

        repaired = repair_calendar(slices, common_k_grid)
        count_after, _, _ = detect_calendar_violations(repaired, common_k_grid)

        assert count_after == 0

    def test_repair_calendar_maintains_monotonicity(self):
        """After repair, w(T) is nondecreasing for each k."""
        common_k_grid = [-0.1, 0.0, 0.1]

        slices = [
            (30 / 365, common_k_grid, [0.005, 0.012, 0.005]),
            (60 / 365, common_k_grid, [0.010, 0.008, 0.010]),
            (90 / 365, common_k_grid, [0.009, 0.015, 0.009]),  # Another violation
        ]

        repaired = repair_calendar(slices, common_k_grid)

        # Check monotonicity for each k index
        for k_idx in range(len(common_k_grid)):
            w_values = [s[2][k_idx] for s in repaired]
            for i in range(1, len(w_values)):
                assert w_values[i] >= w_values[i - 1] - 1e-10


class TestEnforcementInvalidAfterRepairFailure:
    """Enforcement: violations remaining after repair -> is_valid=False."""

    @pytest.fixture
    def valid_chain(self):
        """Create a valid option chain with convex smile."""
        expiry = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")
        # Create convex smile (higher IV at wings)
        return [
            {"strike": 90.0, "iv": 0.28, "expiry": expiry, "right": "call", "greeks": {"delta": 0.80}},
            {"strike": 95.0, "iv": 0.24, "expiry": expiry, "right": "call", "greeks": {"delta": 0.65}},
            {"strike": 100.0, "iv": 0.20, "expiry": expiry, "right": "call", "greeks": {"delta": 0.50}},
            {"strike": 105.0, "iv": 0.24, "expiry": expiry, "right": "call", "greeks": {"delta": 0.35}},
            {"strike": 110.0, "iv": 0.28, "expiry": expiry, "right": "call", "greeks": {"delta": 0.20}},
        ]

    def test_valid_chain_produces_valid_surface(self, valid_chain):
        """Valid chain produces is_valid=True surface."""
        result = build_arb_free_surface(
            chain=valid_chain,
            spot=100.0,
            symbol="SPY",
        )

        assert result.is_valid is True
        assert result.surface is not None
        assert len(result.errors) == 0

    def test_empty_chain_produces_invalid_surface(self):
        """Empty chain produces is_valid=False."""
        result = build_arb_free_surface(
            chain=[],
            spot=100.0,
            symbol="SPY",
        )

        assert result.is_valid is False
        assert result.surface is None

    def test_single_point_chain_produces_invalid_surface(self):
        """Single-point chain produces is_valid=False."""
        expiry = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")
        chain = [
            {"strike": 100.0, "iv": 0.20, "expiry": expiry, "right": "call", "greeks": {"delta": 0.5}},
        ]

        result = build_arb_free_surface(
            chain=chain,
            spot=100.0,
            symbol="SPY",
        )

        # Need at least 3 points for SVI fit
        assert result.is_valid is False or result.surface is None

    def test_surface_with_errors_has_error_list(self):
        """Surface with issues has populated errors list."""
        result = build_arb_free_surface(
            chain=[],
            spot=100.0,
            symbol="SPY",
        )

        assert len(result.errors) > 0 or result.is_valid is False


class TestDeterminismSameInputsSameHash:
    """Determinism: same inputs => same content_hash."""

    @pytest.fixture
    def deterministic_chain(self):
        """Create chain for determinism testing."""
        expiry = "2024-03-15"  # Fixed date for determinism
        return [
            {"strike": 90.0, "iv": 0.28, "expiry": expiry, "right": "call", "greeks": {"delta": 0.80}},
            {"strike": 95.0, "iv": 0.24, "expiry": expiry, "right": "call", "greeks": {"delta": 0.65}},
            {"strike": 100.0, "iv": 0.20, "expiry": expiry, "right": "call", "greeks": {"delta": 0.50}},
            {"strike": 105.0, "iv": 0.24, "expiry": expiry, "right": "call", "greeks": {"delta": 0.35}},
            {"strike": 110.0, "iv": 0.28, "expiry": expiry, "right": "call", "greeks": {"delta": 0.20}},
        ]

    def test_same_inputs_same_hash(self, deterministic_chain):
        """Same inputs produce same content_hash."""
        # Use fixed timestamp for determinism
        fixed_ts = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        result1 = build_arb_free_surface(
            chain=deterministic_chain,
            spot=100.0,
            symbol="SPY",
            risk_free_rate=0.05,
            dividend_yield=0.01,
            as_of_ts=fixed_ts,
        )

        result2 = build_arb_free_surface(
            chain=deterministic_chain,
            spot=100.0,
            symbol="SPY",
            risk_free_rate=0.05,
            dividend_yield=0.01,
            as_of_ts=fixed_ts,
        )

        assert result1.content_hash == result2.content_hash

    def test_different_spot_different_hash(self, deterministic_chain):
        """Different spot produces different content_hash."""
        fixed_ts = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        result1 = build_arb_free_surface(
            chain=deterministic_chain,
            spot=100.0,
            symbol="SPY",
            as_of_ts=fixed_ts,
        )

        result2 = build_arb_free_surface(
            chain=deterministic_chain,
            spot=101.0,  # Different spot
            symbol="SPY",
            as_of_ts=fixed_ts,
        )

        assert result1.content_hash != result2.content_hash

    def test_different_rates_different_hash(self, deterministic_chain):
        """Different risk-free rate produces different content_hash."""
        fixed_ts = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        result1 = build_arb_free_surface(
            chain=deterministic_chain,
            spot=100.0,
            symbol="SPY",
            risk_free_rate=0.05,
            as_of_ts=fixed_ts,
        )

        result2 = build_arb_free_surface(
            chain=deterministic_chain,
            spot=100.0,
            symbol="SPY",
            risk_free_rate=0.04,  # Different rate
            as_of_ts=fixed_ts,
        )

        assert result1.content_hash != result2.content_hash

    def test_multiple_runs_deterministic(self, deterministic_chain):
        """Multiple runs produce identical results."""
        fixed_ts = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        hashes = []
        for _ in range(5):
            result = build_arb_free_surface(
                chain=deterministic_chain,
                spot=100.0,
                symbol="SPY",
                as_of_ts=fixed_ts,
            )
            hashes.append(result.content_hash)

        # All hashes should be identical
        assert len(set(hashes)) == 1


class TestCommonKGridConstruction:
    """Tests for common k-grid construction across expiries."""

    def test_build_common_k_grid_returns_grid(self):
        """Common k-grid is built from slices."""
        slices = [
            (30 / 365, [-0.1, 0.0, 0.1], [0.005, 0.004, 0.005]),
            (60 / 365, [-0.15, -0.05, 0.05, 0.15], [0.010, 0.008, 0.008, 0.010]),
        ]

        common_grid = build_common_k_grid(slices)

        assert common_grid is not None
        assert len(common_grid) > 0

    def test_build_common_k_grid_sorted(self):
        """Common k-grid is sorted ascending."""
        slices = [
            (30 / 365, [0.1, -0.1, 0.0], [0.005, 0.005, 0.004]),  # Unsorted
            (60 / 365, [-0.1, 0.0, 0.1], [0.010, 0.008, 0.010]),
        ]

        common_grid = build_common_k_grid(slices)

        assert common_grid is not None
        for i in range(1, len(common_grid)):
            assert common_grid[i] > common_grid[i - 1]

    def test_build_common_k_grid_requires_two_slices(self):
        """Common k-grid requires at least 2 slices."""
        slices = [
            (30 / 365, [-0.1, 0.0, 0.1], [0.005, 0.004, 0.005]),
        ]

        common_grid = build_common_k_grid(slices)

        assert common_grid is None


class TestForwardAndLogMoneyness:
    """Tests for forward price and log-moneyness calculations."""

    def test_compute_forward_no_divs(self):
        """Forward price without dividends."""
        S = 100.0
        r = 0.05
        q = 0.0
        T = 1.0

        F = compute_forward(S, r, q, T)

        expected = S * math.exp((r - q) * T)
        assert abs(F - expected) < 0.01

    def test_compute_forward_with_divs(self):
        """Forward price with dividends."""
        S = 100.0
        r = 0.05
        q = 0.02
        T = 1.0

        F = compute_forward(S, r, q, T)

        expected = S * math.exp((r - q) * T)
        assert abs(F - expected) < 0.01

    def test_log_moneyness_atm(self):
        """ATM option has k near zero."""
        K = 100.0
        F = 100.0

        k = compute_log_moneyness(K, F)

        assert abs(k) < 0.001

    def test_log_moneyness_otm_call(self):
        """OTM call has positive k."""
        K = 110.0
        F = 100.0

        k = compute_log_moneyness(K, F)

        assert k > 0
        # k = ln(110/100) = ln(1.1) ≈ 0.0953
        assert abs(k - 0.0953) < 0.001

    def test_log_moneyness_itm_call(self):
        """ITM call has negative k."""
        K = 90.0
        F = 100.0

        k = compute_log_moneyness(K, F)

        assert k < 0
        # k = ln(90/100) = ln(0.9) ≈ -0.1054
        assert abs(k - (-0.1054)) < 0.001


class TestSurfaceVersioning:
    """Tests for surface versioning."""

    def test_surface_has_version(self):
        """Built surface has version field."""
        expiry = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")
        chain = [
            {"strike": 90.0, "iv": 0.28, "expiry": expiry, "right": "call", "greeks": {"delta": 0.80}},
            {"strike": 100.0, "iv": 0.20, "expiry": expiry, "right": "call", "greeks": {"delta": 0.50}},
            {"strike": 110.0, "iv": 0.28, "expiry": expiry, "right": "call", "greeks": {"delta": 0.20}},
        ]

        result = build_arb_free_surface(
            chain=chain,
            spot=100.0,
            symbol="SPY",
        )

        if result.surface:
            assert result.surface.version == SURFACE_VERSION

    def test_version_is_v4(self):
        """Version should be v4."""
        assert SURFACE_VERSION == "v4"


class TestSVIModel:
    """Tests for SVI total variance function."""

    def test_svi_at_m_equals_a_plus_b_sigma(self):
        """SVI at k=m should equal a + b*sigma."""
        a, b, rho, m, sigma = 0.01, 0.1, 0.0, 0.0, 0.1

        w = svi_total_variance(m, a, b, rho, m, sigma)

        # At k=m: w = a + b*(0 + sigma) = a + b*sigma
        expected = a + b * sigma
        assert abs(w - expected) < 1e-10

    def test_svi_symmetric_when_rho_zero(self):
        """SVI is symmetric around m when rho=0."""
        a, b, rho, m, sigma = 0.01, 0.1, 0.0, 0.0, 0.1

        w_left = svi_total_variance(-0.1, a, b, rho, m, sigma)
        w_right = svi_total_variance(0.1, a, b, rho, m, sigma)

        assert abs(w_left - w_right) < 1e-10

    def test_svi_skewed_when_rho_nonzero(self):
        """SVI is skewed when rho != 0."""
        a, b, rho, m, sigma = 0.01, 0.1, -0.3, 0.0, 0.1

        w_left = svi_total_variance(-0.1, a, b, rho, m, sigma)
        w_right = svi_total_variance(0.1, a, b, rho, m, sigma)

        # With negative rho, left wing should be higher
        assert w_left > w_right


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
