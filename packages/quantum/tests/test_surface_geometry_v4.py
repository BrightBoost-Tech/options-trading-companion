"""
Tests for Arb-Free Surface Geometry v4.

Tests:
- Per-expiry smile construction
- Butterfly arbitrage detection and convexification
- Calendar arbitrage detection
- Deterministic hashing
- Lineage signing
"""

import pytest
from datetime import datetime, timezone, timedelta

from packages.quantum.services.surface_geometry_v4 import (
    CanonicalSmilePoint,
    PerExpirySmile,
    ArbFreeSurface,
    SurfaceResult,
    build_arb_free_surface,
    build_per_expiry_smile,
    detect_butterfly_arbitrage,
    convexify_smile,
    detect_calendar_arbitrage,
    compute_moneyness,
    compute_time_to_expiry,
    compute_dte,
    find_atm_iv,
    SURFACE_VERSION,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_chain():
    """Sample option chain for testing."""
    spot = 100.0
    expiry = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")

    return [
        {"strike": 90.0, "iv": 0.25, "expiry": expiry, "right": "call", "greeks": {"delta": 0.8}},
        {"strike": 95.0, "iv": 0.22, "expiry": expiry, "right": "call", "greeks": {"delta": 0.65}},
        {"strike": 100.0, "iv": 0.20, "expiry": expiry, "right": "call", "greeks": {"delta": 0.5}},
        {"strike": 105.0, "iv": 0.22, "expiry": expiry, "right": "call", "greeks": {"delta": 0.35}},
        {"strike": 110.0, "iv": 0.25, "expiry": expiry, "right": "call", "greeks": {"delta": 0.2}},
    ]


@pytest.fixture
def butterfly_arb_chain():
    """Chain with butterfly arbitrage (negative convexity at strike 100)."""
    spot = 100.0
    expiry = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")

    # IV dips below linear interpolation at ATM (butterfly arb)
    return [
        {"strike": 90.0, "iv": 0.30, "expiry": expiry, "right": "call", "greeks": {}},
        {"strike": 95.0, "iv": 0.25, "expiry": expiry, "right": "call", "greeks": {}},
        {"strike": 100.0, "iv": 0.15, "expiry": expiry, "right": "call", "greeks": {}},  # Arb!
        {"strike": 105.0, "iv": 0.25, "expiry": expiry, "right": "call", "greeks": {}},
        {"strike": 110.0, "iv": 0.30, "expiry": expiry, "right": "call", "greeks": {}},
    ]


@pytest.fixture
def multi_expiry_chain():
    """Chain with multiple expiries for calendar arb testing."""
    spot = 100.0
    exp1 = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%d")
    exp2 = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")
    exp3 = (datetime.now(timezone.utc) + timedelta(days=60)).strftime("%Y-%m-%d")

    chain = []
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
# Unit Tests - Helper Functions
# =============================================================================

class TestComputeMoneyness:
    def test_atm(self):
        assert compute_moneyness(100.0, 100.0) == 1.0

    def test_itm_call(self):
        assert compute_moneyness(90.0, 100.0) == 0.9

    def test_otm_call(self):
        assert compute_moneyness(110.0, 100.0) == 1.1

    def test_zero_spot(self):
        assert compute_moneyness(100.0, 0.0) == 0.0

    def test_negative_spot(self):
        assert compute_moneyness(100.0, -10.0) == 0.0


class TestComputeTimeToExpiry:
    def test_future_date(self):
        as_of = datetime(2024, 1, 1, tzinfo=timezone.utc)
        tte = compute_time_to_expiry("2024-02-01", as_of)
        assert tte == pytest.approx(31 / 365.0, rel=0.01)

    def test_past_date(self):
        as_of = datetime(2024, 2, 1, tzinfo=timezone.utc)
        tte = compute_time_to_expiry("2024-01-01", as_of)
        assert tte == 0.0

    def test_same_date(self):
        as_of = datetime(2024, 1, 1, tzinfo=timezone.utc)
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
# Unit Tests - Butterfly Arbitrage
# =============================================================================

class TestDetectButterflyArbitrage:
    def test_no_arb_convex_smile(self):
        """Convex smile should have no violations."""
        points = [
            CanonicalSmilePoint(strike=90, moneyness=0.9, iv=0.25, is_call=True),
            CanonicalSmilePoint(strike=100, moneyness=1.0, iv=0.20, is_call=True),
            CanonicalSmilePoint(strike=110, moneyness=1.1, iv=0.25, is_call=True),
        ]
        violations = detect_butterfly_arbitrage(points)
        assert len(violations) == 0

    def test_arb_concave_smile(self):
        """Concave smile (bump at ATM) should detect violation."""
        points = [
            CanonicalSmilePoint(strike=90, moneyness=0.9, iv=0.20, is_call=True),
            CanonicalSmilePoint(strike=100, moneyness=1.0, iv=0.30, is_call=True),  # Concave
            CanonicalSmilePoint(strike=110, moneyness=1.1, iv=0.20, is_call=True),
        ]
        violations = detect_butterfly_arbitrage(points)
        assert len(violations) == 1
        assert 1 in violations

    def test_too_few_points(self):
        """Less than 3 points should return no violations."""
        points = [
            CanonicalSmilePoint(strike=100, moneyness=1.0, iv=0.20, is_call=True),
            CanonicalSmilePoint(strike=110, moneyness=1.1, iv=0.25, is_call=True),
        ]
        violations = detect_butterfly_arbitrage(points)
        assert len(violations) == 0


class TestConvexifySmile:
    def test_already_convex(self):
        """Convex smile should be unchanged."""
        points = [
            CanonicalSmilePoint(strike=90, moneyness=0.9, iv=0.25, is_call=True),
            CanonicalSmilePoint(strike=100, moneyness=1.0, iv=0.20, is_call=True),
            CanonicalSmilePoint(strike=110, moneyness=1.1, iv=0.25, is_call=True),
        ]
        result = convexify_smile(points)
        assert len(result) == 3
        assert not any(p.convexified for p in result)

    def test_concave_is_fixed(self):
        """Concave point should be fixed via interpolation."""
        points = [
            CanonicalSmilePoint(strike=90, moneyness=0.9, iv=0.20, is_call=True),
            CanonicalSmilePoint(strike=100, moneyness=1.0, iv=0.30, is_call=True),
            CanonicalSmilePoint(strike=110, moneyness=1.1, iv=0.20, is_call=True),
        ]
        result = convexify_smile(points)
        # Middle point should be interpolated to (0.20 + 0.20) / 2 = 0.20
        mid_point = result[1]
        assert mid_point.convexified is True
        assert mid_point.iv == pytest.approx(0.20, rel=0.01)


# =============================================================================
# Unit Tests - Calendar Arbitrage
# =============================================================================

class TestDetectCalendarArbitrage:
    def test_no_calendar_arb(self):
        """Monotonic total variance should have no violations."""
        smiles = [
            PerExpirySmile(
                expiry="2024-01-15", dte=7, time_to_expiry=7/365,
                total_variance=0.20**2 * (7/365), points=[], atm_iv=0.20
            ),
            PerExpirySmile(
                expiry="2024-02-15", dte=37, time_to_expiry=37/365,
                total_variance=0.20**2 * (37/365), points=[], atm_iv=0.20
            ),
            PerExpirySmile(
                expiry="2024-03-15", dte=67, time_to_expiry=67/365,
                total_variance=0.20**2 * (67/365), points=[], atm_iv=0.20
            ),
        ]
        violations = detect_calendar_arbitrage(smiles)
        assert len(violations) == 0

    def test_calendar_arb_detected(self):
        """Non-monotonic total variance should be detected."""
        smiles = [
            PerExpirySmile(
                expiry="2024-01-15", dte=7, time_to_expiry=7/365,
                total_variance=0.30**2 * (7/365), points=[], atm_iv=0.30
            ),
            PerExpirySmile(
                expiry="2024-02-15", dte=37, time_to_expiry=37/365,
                total_variance=0.10**2 * (37/365), points=[], atm_iv=0.10  # Lower variance!
            ),
        ]
        violations = detect_calendar_arbitrage(smiles)
        assert len(violations) == 1
        assert "2024-02-15" in violations


# =============================================================================
# Unit Tests - Find ATM IV
# =============================================================================

class TestFindAtmIv:
    def test_exact_atm(self):
        points = [
            CanonicalSmilePoint(strike=90, moneyness=0.9, iv=0.25, is_call=True),
            CanonicalSmilePoint(strike=100, moneyness=1.0, iv=0.20, is_call=True),
            CanonicalSmilePoint(strike=110, moneyness=1.1, iv=0.25, is_call=True),
        ]
        assert find_atm_iv(points) == 0.20

    def test_near_atm(self):
        points = [
            CanonicalSmilePoint(strike=99, moneyness=0.99, iv=0.21, is_call=True),
            CanonicalSmilePoint(strike=105, moneyness=1.05, iv=0.23, is_call=True),
        ]
        atm = find_atm_iv(points)
        assert atm == 0.21  # Closer to 1.0

    def test_no_close_atm(self):
        points = [
            CanonicalSmilePoint(strike=80, moneyness=0.8, iv=0.30, is_call=True),
            CanonicalSmilePoint(strike=120, moneyness=1.2, iv=0.30, is_call=True),
        ]
        # Both are >10% from ATM
        assert find_atm_iv(points) is None

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

        assert result.is_valid is True
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

    def test_butterfly_arb_detected(self, butterfly_arb_chain):
        result = build_arb_free_surface(
            chain=butterfly_arb_chain,
            spot=100.0,
            symbol="TEST",
        )

        assert result.is_valid is True
        assert result.surface is not None
        # Butterfly arb should be detected and fixed
        smile = result.surface.smiles[0]
        assert smile.butterfly_arb_detected is True
        assert smile.butterfly_arb_count > 0
        # Some points should be convexified
        assert any(p.convexified for p in smile.points)

    def test_multi_expiry_surface(self, multi_expiry_chain):
        result = build_arb_free_surface(
            chain=multi_expiry_chain,
            spot=100.0,
            symbol="TEST",
        )

        assert result.is_valid is True
        assert len(result.surface.smiles) == 3
        # Smiles should be sorted by expiry
        expiries = [s.expiry for s in result.surface.smiles]
        assert expiries == sorted(expiries)


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
            spot=100.5,  # Different spot
            symbol="TEST",
            as_of_ts=as_of,
        )

        assert result1.content_hash != result2.content_hash


class TestCanonicalSmilePointModel:
    def test_to_canonical_dict(self):
        point = CanonicalSmilePoint(
            strike=100.0,
            moneyness=1.0,
            iv=0.20,
            is_call=True,
        )
        d = point.to_canonical_dict()
        assert d["strike"] == "100.000000"
        assert d["moneyness"] == "1.000000"
        assert d["iv"] == "0.200000"
        assert d["is_call"] is True
        assert d["convexified"] is False


class TestPerExpirySmileModel:
    def test_to_canonical_dict(self):
        smile = PerExpirySmile(
            expiry="2024-06-15",
            dte=30,
            time_to_expiry=30/365,
            total_variance=0.04 * (30/365),
            points=[],
            atm_iv=0.20,
        )
        d = smile.to_canonical_dict()
        assert d["expiry"] == "2024-06-15"
        assert d["dte"] == 30
        assert d["points"] == []


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
        assert d["spot"] == "100.000000"
        assert d["version"] == SURFACE_VERSION
        assert isinstance(d["smiles"], list)


class TestSurfaceResultModel:
    def test_to_dict(self, sample_chain):
        result = build_arb_free_surface(
            chain=sample_chain,
            spot=100.0,
            symbol="TEST",
        )

        d = result.to_dict()
        assert d["is_valid"] is True
        assert d["content_hash"] != ""
        assert d["surface"] is not None
        assert d["errors"] == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
