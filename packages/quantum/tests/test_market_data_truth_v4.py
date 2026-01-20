"""
Tests for Market Data Truth Layer V4 - Quality Scoring and Stale-Aware Snapshots.

These tests verify:
1. Quality scoring (compute_quote_quality)
2. Executable checks (check_snapshots_executable)
3. snapshot_many_v4 returns typed V4 objects
4. Integration with build_midday_order_json
5. Backward compatibility with existing snapshot_many
"""

import pytest
import time
from unittest.mock import patch, MagicMock
from packages.quantum.services.market_data_truth_layer import (
    MarketDataTruthLayer,
    TruthQuoteV4,
    TruthQualityV4,
    TruthTimestampsV4,
    TruthSourceV4,
    TruthSnapshotV4,
    compute_quote_quality,
    check_snapshots_executable,
    MARKETDATA_MAX_FRESHNESS_MS,
    MARKETDATA_MIN_QUALITY_SCORE,
    MARKETDATA_WIDE_SPREAD_PCT,
)


class TestQualityScoring:
    """Tests for compute_quote_quality function."""

    def test_crossed_market_score_zero(self):
        """Crossed market (ask < bid) => quality_score=0, issues include crossed_market."""
        quote = TruthQuoteV4(bid=100.0, ask=99.0)  # crossed: ask < bid
        quality = compute_quote_quality(quote, freshness_ms=1000)

        assert quality.quality_score == 0
        assert "crossed_market" in quality.issues

    def test_missing_bid_reduces_score(self):
        """Missing bid => issues include missing_quote_fields, score reduced."""
        quote = TruthQuoteV4(bid=None, ask=100.0)
        quality = compute_quote_quality(quote, freshness_ms=1000)

        assert quality.quality_score < 100
        assert "missing_quote_fields" in quality.issues

    def test_missing_ask_reduces_score(self):
        """Missing ask => issues include missing_quote_fields, score reduced."""
        quote = TruthQuoteV4(bid=100.0, ask=None)
        quality = compute_quote_quality(quote, freshness_ms=1000)

        assert quality.quality_score < 100
        assert "missing_quote_fields" in quality.issues

    def test_missing_both_bid_ask_reduces_score(self):
        """Missing both bid and ask => issues include missing_quote_fields."""
        quote = TruthQuoteV4(bid=None, ask=None)
        quality = compute_quote_quality(quote, freshness_ms=1000)

        assert quality.quality_score < 100
        assert "missing_quote_fields" in quality.issues

    def test_stale_timestamp_marks_stale(self):
        """Stale timestamp (> max_freshness) => is_stale=True, issues include stale_quote."""
        quote = TruthQuoteV4(bid=99.0, ask=100.0, mid=99.5)
        # 120 seconds old (> default 60s threshold)
        quality = compute_quote_quality(quote, freshness_ms=120000)

        assert quality.is_stale is True
        assert "stale_quote" in quality.issues
        assert quality.quality_score < 100

    def test_missing_timestamp_treated_as_stale(self):
        """Missing timestamp => is_stale=True (conservative), issues include missing_timestamp."""
        quote = TruthQuoteV4(bid=99.0, ask=100.0, mid=99.5)
        quality = compute_quote_quality(quote, freshness_ms=None)

        assert quality.is_stale is True
        assert "missing_timestamp" in quality.issues

    def test_wide_spread_penalty(self):
        """Wide spread (> 10%) => issues include wide_spread, score reduced."""
        # 20% spread: (110-90)/100 = 0.20
        quote = TruthQuoteV4(bid=90.0, ask=110.0, mid=100.0)
        quality = compute_quote_quality(quote, freshness_ms=1000)

        assert "wide_spread" in quality.issues
        assert quality.quality_score < 100

    def test_narrow_spread_no_penalty(self):
        """Narrow spread (< 10%) => no wide_spread issue."""
        # 1% spread: (100.5-99.5)/100 = 0.01
        quote = TruthQuoteV4(bid=99.5, ask=100.5, mid=100.0)
        quality = compute_quote_quality(quote, freshness_ms=1000)

        assert "wide_spread" not in quality.issues

    def test_healthy_quote_full_score(self):
        """Valid quote with fresh timestamp => score=100, no issues, is_stale=False."""
        quote = TruthQuoteV4(bid=99.0, ask=100.0, mid=99.5)
        quality = compute_quote_quality(quote, freshness_ms=5000)  # 5 seconds old

        assert quality.quality_score == 100
        assert quality.issues == []
        assert quality.is_stale is False
        assert quality.freshness_ms == 5000

    def test_custom_thresholds(self):
        """Custom thresholds override defaults."""
        quote = TruthQuoteV4(bid=99.0, ask=100.0, mid=99.5)

        # With very strict freshness (1 second), 5 seconds should be stale
        quality = compute_quote_quality(quote, freshness_ms=5000, max_freshness_ms=1000)
        assert quality.is_stale is True
        assert "stale_quote" in quality.issues

        # With very lenient spread (50%), 20% spread should be fine
        wide_quote = TruthQuoteV4(bid=90.0, ask=110.0, mid=100.0)
        quality2 = compute_quote_quality(wide_quote, freshness_ms=1000, wide_spread_pct=0.50)
        assert "wide_spread" not in quality2.issues

    def test_score_clamped_to_valid_range(self):
        """Score is clamped between 0 and 100."""
        # Multiple issues that would push score below 0
        quote = TruthQuoteV4(bid=None, ask=None)  # -40
        quality = compute_quote_quality(quote, freshness_ms=120000)  # -30 for stale

        assert quality.quality_score >= 0
        assert quality.quality_score <= 100


class TestCheckSnapshotsExecutable:
    """Tests for check_snapshots_executable function."""

    def test_passes_healthy_snapshots(self):
        """Healthy snapshots pass executable check."""
        snap = TruthSnapshotV4(
            symbol_canonical="AAPL",
            quote=TruthQuoteV4(bid=150.0, ask=150.10, mid=150.05),
            timestamps=TruthTimestampsV4(source_ts=int(time.time() * 1000), received_ts=int(time.time() * 1000)),
            quality=TruthQualityV4(quality_score=100, issues=[], is_stale=False, freshness_ms=100),
            source=TruthSourceV4(),
        )

        is_exec, issues = check_snapshots_executable({"AAPL": snap}, ["AAPL"])

        assert is_exec is True
        assert issues == []

    def test_fails_missing_snapshot(self):
        """Missing snapshot fails executable check."""
        is_exec, issues = check_snapshots_executable({}, ["AAPL"])

        assert is_exec is False
        assert any("missing_snapshot" in issue for issue in issues)

    def test_fails_stale_snapshot(self):
        """Stale snapshot fails executable check."""
        snap = TruthSnapshotV4(
            symbol_canonical="AAPL",
            quote=TruthQuoteV4(bid=150.0, ask=150.10, mid=150.05),
            timestamps=TruthTimestampsV4(source_ts=1000, received_ts=int(time.time() * 1000)),
            quality=TruthQualityV4(quality_score=70, issues=["stale_quote"], is_stale=True, freshness_ms=120000),
            source=TruthSourceV4(),
        )

        is_exec, issues = check_snapshots_executable({"AAPL": snap}, ["AAPL"])

        assert is_exec is False
        assert any("stale_quote" in issue for issue in issues)

    def test_fails_low_quality_snapshot(self):
        """Low quality snapshot (below threshold) fails executable check."""
        snap = TruthSnapshotV4(
            symbol_canonical="AAPL",
            quote=TruthQuoteV4(bid=None, ask=150.10),
            timestamps=TruthTimestampsV4(source_ts=int(time.time() * 1000), received_ts=int(time.time() * 1000)),
            quality=TruthQualityV4(quality_score=50, issues=["missing_quote_fields"], is_stale=False, freshness_ms=100),
            source=TruthSourceV4(),
        )

        # Default min score is 60, snapshot has 50
        is_exec, issues = check_snapshots_executable({"AAPL": snap}, ["AAPL"])

        assert is_exec is False
        assert any("low_quality" in issue for issue in issues)

    def test_custom_min_quality_score(self):
        """Custom min_quality_score changes threshold."""
        snap = TruthSnapshotV4(
            symbol_canonical="AAPL",
            quote=TruthQuoteV4(bid=150.0, ask=150.10, mid=150.05),
            timestamps=TruthTimestampsV4(source_ts=int(time.time() * 1000), received_ts=int(time.time() * 1000)),
            quality=TruthQualityV4(quality_score=50, issues=[], is_stale=False, freshness_ms=100),
            source=TruthSourceV4(),
        )

        # With min_quality_score=40, score of 50 should pass
        is_exec, issues = check_snapshots_executable({"AAPL": snap}, ["AAPL"], min_quality_score=40)

        assert is_exec is True
        assert issues == []

    def test_multiple_symbols_all_must_pass(self):
        """All required symbols must pass for overall pass."""
        good_snap = TruthSnapshotV4(
            symbol_canonical="AAPL",
            quote=TruthQuoteV4(bid=150.0, ask=150.10, mid=150.05),
            timestamps=TruthTimestampsV4(source_ts=int(time.time() * 1000), received_ts=int(time.time() * 1000)),
            quality=TruthQualityV4(quality_score=100, issues=[], is_stale=False, freshness_ms=100),
            source=TruthSourceV4(),
        )
        bad_snap = TruthSnapshotV4(
            symbol_canonical="SPY",
            quote=TruthQuoteV4(bid=500.0, ask=499.0),  # crossed
            timestamps=TruthTimestampsV4(source_ts=int(time.time() * 1000), received_ts=int(time.time() * 1000)),
            quality=TruthQualityV4(quality_score=0, issues=["crossed_market"], is_stale=False, freshness_ms=100),
            source=TruthSourceV4(),
        )

        is_exec, issues = check_snapshots_executable(
            {"AAPL": good_snap, "SPY": bad_snap},
            ["AAPL", "SPY"]
        )

        assert is_exec is False
        assert any("SPY" in issue for issue in issues)


class TestSnapshotManyV4:
    """Tests for snapshot_many_v4 method."""

    @patch("packages.quantum.services.market_data_truth_layer.get_market_data_cache")
    @patch("packages.quantum.services.market_data_truth_layer.requests.Session.get")
    def test_returns_v4_objects(self, mock_get, mock_cache):
        """snapshot_many_v4() returns TruthSnapshotV4 objects."""
        # Mock cache to always return None (no cache hits)
        mock_cache.return_value.get.return_value = None

        layer = MarketDataTruthLayer(api_key="test")

        current_ts = int(time.time() * 1000)
        mock_response = {
            "results": [{
                "ticker": "AAPL",
                "type": "CS",
                "last_quote": {"b": 150.0, "a": 150.10},
                "updated": current_ts - 5000,  # 5 seconds ago
                "session": {"close": 150.05, "volume": 1000000}
            }]
        }
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = mock_response

        results = layer.snapshot_many_v4(["AAPL"])

        assert "AAPL" in results
        snap = results["AAPL"]

        # Verify it's a TruthSnapshotV4
        assert isinstance(snap, TruthSnapshotV4)
        assert snap.symbol_canonical == "AAPL"
        assert snap.quote.bid == 150.0
        assert snap.quote.ask == 150.10
        assert snap.quote.mid == pytest.approx(150.05)
        assert isinstance(snap.quality, TruthQualityV4)
        assert snap.quality.quality_score >= 0

    @patch("packages.quantum.services.market_data_truth_layer.get_market_data_cache")
    @patch("packages.quantum.services.market_data_truth_layer.requests.Session.get")
    def test_computes_mid_when_missing(self, mock_get, mock_cache):
        """V4 snapshot computes mid if bid/ask present but mid missing."""
        # Mock cache to always return None (no cache hits)
        mock_cache.return_value.get.return_value = None

        layer = MarketDataTruthLayer(api_key="test")

        mock_response = {
            "results": [{
                "ticker": "MSFT",  # Use different ticker to avoid any cache issues
                "type": "CS",
                "last_quote": {"b": 100.0, "a": 102.0},  # No mid provided
                "updated": int(time.time() * 1000) - 1000,
            }]
        }
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = mock_response

        results = layer.snapshot_many_v4(["MSFT"])

        snap = results["MSFT"]
        assert snap.quote.mid == pytest.approx(101.0)  # (100 + 102) / 2

    @patch("packages.quantum.services.market_data_truth_layer.get_market_data_cache")
    @patch("packages.quantum.services.market_data_truth_layer.requests.Session.get")
    def test_handles_stale_data(self, mock_get, mock_cache):
        """V4 snapshot correctly marks stale data."""
        # Mock cache to always return None (no cache hits)
        mock_cache.return_value.get.return_value = None

        layer = MarketDataTruthLayer(api_key="test")

        old_ts = int(time.time() * 1000) - 120000  # 2 minutes ago
        mock_response = {
            "results": [{
                "ticker": "GOOG",  # Use different ticker
                "type": "CS",
                "last_quote": {"b": 150.0, "a": 150.10},
                "updated": old_ts,
            }]
        }
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = mock_response

        results = layer.snapshot_many_v4(["GOOG"])

        snap = results["GOOG"]
        assert snap.quality.is_stale is True
        assert "stale_quote" in snap.quality.issues

    @patch("packages.quantum.services.market_data_truth_layer.get_market_data_cache")
    @patch("packages.quantum.services.market_data_truth_layer.requests.Session.get")
    def test_backward_compat_snapshot_many_unchanged(self, mock_get, mock_cache):
        """Existing snapshot_many() still returns dict (not Pydantic model)."""
        # Mock cache to always return None (no cache hits)
        mock_cache.return_value.get.return_value = None

        layer = MarketDataTruthLayer(api_key="test")

        mock_response = {
            "results": [{
                "ticker": "AMZN",  # Use different ticker
                "type": "CS",
                "last_quote": {"b": 150.0, "a": 150.10},
                "updated": int(time.time() * 1000),
            }]
        }
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = mock_response

        results = layer.snapshot_many(["AMZN"])

        assert "AMZN" in results
        assert isinstance(results["AMZN"], dict)
        assert not isinstance(results["AMZN"], TruthSnapshotV4)


class TestIntegrationOrderBuilder:
    """Integration tests for order builder with V4 quality checks."""

    def test_order_builder_rejects_stale_v4_quotes(self):
        """build_midday_order_json rejects when v4 snapshots are stale."""
        from packages.quantum.services.workflow_orchestrator import build_midday_order_json

        cand = {
            "symbol": "SPY",
            "suggested_entry": 1.25,
            "strategy": "vertical_spread",
            "order_type_force_limit": True,
            "legs": [
                {"symbol": "O:SPY250101C00500000", "side": "buy", "mid": 1.50},
                {"symbol": "O:SPY250101C00505000", "side": "sell", "mid": 0.25}
            ]
        }

        # Create stale V4 snapshots
        stale_snap = TruthSnapshotV4(
            symbol_canonical="O:SPY250101C00500000",
            quote=TruthQuoteV4(bid=1.45, ask=1.55, mid=1.50),
            timestamps=TruthTimestampsV4(source_ts=1000, received_ts=int(time.time() * 1000)),
            quality=TruthQualityV4(quality_score=70, issues=["stale_quote"], is_stale=True, freshness_ms=120000),
            source=TruthSourceV4(),
        )
        good_snap = TruthSnapshotV4(
            symbol_canonical="O:SPY250101C00505000",
            quote=TruthQuoteV4(bid=0.20, ask=0.30, mid=0.25),
            timestamps=TruthTimestampsV4(source_ts=int(time.time() * 1000), received_ts=int(time.time() * 1000)),
            quality=TruthQualityV4(quality_score=100, issues=[], is_stale=False, freshness_ms=100),
            source=TruthSourceV4(),
        )

        v4_snapshots = {
            "O:SPY250101C00500000": stale_snap,
            "O:SPY250101C00505000": good_snap,
        }

        order_json = build_midday_order_json(cand, 3, leg_snapshots_v4=v4_snapshots)

        assert order_json["status"] == "NOT_EXECUTABLE"
        assert "quality gate failed" in order_json["reason"].lower()

    def test_order_builder_accepts_healthy_v4_quotes(self):
        """build_midday_order_json accepts when v4 snapshots are healthy."""
        from packages.quantum.services.workflow_orchestrator import build_midday_order_json

        cand = {
            "symbol": "SPY",
            "suggested_entry": 1.25,
            "strategy": "vertical_spread",
            "order_type_force_limit": True,
            "legs": [
                {"symbol": "O:SPY250101C00500000", "side": "buy", "mid": 1.50},
                {"symbol": "O:SPY250101C00505000", "side": "sell", "mid": 0.25}
            ]
        }

        # Create healthy V4 snapshots
        healthy_snap1 = TruthSnapshotV4(
            symbol_canonical="O:SPY250101C00500000",
            quote=TruthQuoteV4(bid=1.45, ask=1.55, mid=1.50),
            timestamps=TruthTimestampsV4(source_ts=int(time.time() * 1000), received_ts=int(time.time() * 1000)),
            quality=TruthQualityV4(quality_score=100, issues=[], is_stale=False, freshness_ms=100),
            source=TruthSourceV4(),
        )
        healthy_snap2 = TruthSnapshotV4(
            symbol_canonical="O:SPY250101C00505000",
            quote=TruthQuoteV4(bid=0.20, ask=0.30, mid=0.25),
            timestamps=TruthTimestampsV4(source_ts=int(time.time() * 1000), received_ts=int(time.time() * 1000)),
            quality=TruthQualityV4(quality_score=100, issues=[], is_stale=False, freshness_ms=100),
            source=TruthSourceV4(),
        )

        v4_snapshots = {
            "O:SPY250101C00500000": healthy_snap1,
            "O:SPY250101C00505000": healthy_snap2,
        }

        order_json = build_midday_order_json(cand, 3, leg_snapshots_v4=v4_snapshots)

        # Should not have NOT_EXECUTABLE status
        assert order_json.get("status") != "NOT_EXECUTABLE"
        assert order_json["limit_price"] == 1.25
        assert order_json["contracts"] == 3

    def test_order_builder_backward_compat_no_v4_snapshots(self):
        """build_midday_order_json works without v4 snapshots (backward compat)."""
        from packages.quantum.services.workflow_orchestrator import build_midday_order_json

        cand = {
            "symbol": "SPY",
            "suggested_entry": 1.25,
            "strategy": "vertical_spread",
            "order_type_force_limit": True,
            "legs": [
                {"symbol": "O:SPY250101C00500000", "side": "buy", "mid": 1.50},
                {"symbol": "O:SPY250101C00505000", "side": "sell", "mid": 0.25}
            ]
        }

        # No v4 snapshots provided - should still work
        order_json = build_midday_order_json(cand, 3)

        assert order_json.get("status") != "NOT_EXECUTABLE"
        assert order_json["limit_price"] == 1.25


class TestConfigurationDefaults:
    """Tests for configuration defaults and environment overrides."""

    def test_default_max_freshness(self):
        """Default MARKETDATA_MAX_FRESHNESS_MS is 60000."""
        assert MARKETDATA_MAX_FRESHNESS_MS == 60000

    def test_default_min_quality_score(self):
        """Default MARKETDATA_MIN_QUALITY_SCORE is 60."""
        assert MARKETDATA_MIN_QUALITY_SCORE == 60

    def test_default_wide_spread_pct(self):
        """Default MARKETDATA_WIDE_SPREAD_PCT is 0.10 (10%)."""
        assert MARKETDATA_WIDE_SPREAD_PCT == pytest.approx(0.10)


class TestTimestampNormalization:
    """Tests for timestamp normalization."""

    def test_normalize_nanoseconds(self):
        """Nanoseconds (> 10^16) converted to milliseconds."""
        layer = MarketDataTruthLayer(api_key="test")
        # Nanoseconds: 1.7e18
        ns_ts = 1700000000000000000  # ~2023 in nanoseconds
        result = layer._normalize_timestamp_to_ms(ns_ts)
        assert result == 1700000000000  # Should be in milliseconds

    def test_normalize_microseconds(self):
        """Microseconds (> 10^14) converted to milliseconds."""
        layer = MarketDataTruthLayer(api_key="test")
        # Microseconds: 1.7e15
        us_ts = 1700000000000000  # ~2023 in microseconds
        result = layer._normalize_timestamp_to_ms(us_ts)
        assert result == 1700000000000  # Should be in milliseconds

    def test_normalize_milliseconds_unchanged(self):
        """Milliseconds (> 10^11) returned as-is."""
        layer = MarketDataTruthLayer(api_key="test")
        ms_ts = 1700000000000  # ~2023 in milliseconds
        result = layer._normalize_timestamp_to_ms(ms_ts)
        assert result == 1700000000000

    def test_normalize_seconds_to_milliseconds(self):
        """Seconds converted to milliseconds."""
        layer = MarketDataTruthLayer(api_key="test")
        sec_ts = 1700000000  # ~2023 in seconds
        result = layer._normalize_timestamp_to_ms(sec_ts)
        assert result == 1700000000000

    def test_normalize_none_returns_none(self):
        """None input returns None."""
        layer = MarketDataTruthLayer(api_key="test")
        assert layer._normalize_timestamp_to_ms(None) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
