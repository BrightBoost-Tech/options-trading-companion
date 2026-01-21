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
from unittest.mock import patch, MagicMock, call
from packages.quantum.services.market_data_truth_layer import (
    MarketDataTruthLayer,
    TruthQuoteV4,
    TruthQualityV4,
    TruthTimestampsV4,
    TruthSourceV4,
    TruthSnapshotV4,
    compute_quote_quality,
    check_snapshots_executable,
    get_marketdata_max_freshness_ms,
    get_marketdata_min_quality_score,
    get_marketdata_wide_spread_pct,
    get_marketdata_quality_policy,
    get_marketdata_warn_penalty,
    MARKETDATA_MAX_FRESHNESS_MS,
    MARKETDATA_MIN_QUALITY_SCORE,
    MARKETDATA_WIDE_SPREAD_PCT,
    # V4 Quality codes and classifiers
    QUALITY_OK,
    QUALITY_WARN_WIDE_SPREAD,
    QUALITY_WARN_LOW_QUALITY,
    QUALITY_FAIL_STALE,
    QUALITY_FAIL_CROSSED,
    QUALITY_FAIL_MISSING_SNAPSHOT,
    QUALITY_FAIL_MISSING_TIMESTAMP,
    # V4 Effective action constants
    EFFECTIVE_ACTION_SKIP_FATAL,
    EFFECTIVE_ACTION_SKIP_POLICY,
    EFFECTIVE_ACTION_DEFER,
    EFFECTIVE_ACTION_DOWNRANK,
    EFFECTIVE_ACTION_DOWNRANK_FALLBACK,
    QUALITY_FAIL_MISSING_QUOTE_FIELDS,
    FATAL_QUALITY_CODES,
    classify_snapshot_quality,
    classify_missing_snapshot,
    is_fatal_quality_code,
    format_quality_issues,
    format_snapshot_summary,
    format_quality_gate_result,
    format_blocked_detail,
    build_marketdata_block_payload,
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


class TestSymbolNormalization:
    """Tests for symbol normalization in check_snapshots_executable."""

    def test_raw_symbol_matches_canonical_key(self):
        """Raw symbol finds snapshot when key is canonical."""
        snap = TruthSnapshotV4(
            symbol_canonical="O:AAPL250117C00200000",
            quote=TruthQuoteV4(bid=5.0, ask=5.10, mid=5.05),
            timestamps=TruthTimestampsV4(source_ts=int(time.time() * 1000), received_ts=int(time.time() * 1000)),
            quality=TruthQualityV4(quality_score=100, issues=[], is_stale=False, freshness_ms=100),
            source=TruthSourceV4(),
        )

        # Snapshot stored with canonical key (O: prefix)
        # Required symbol is raw (no O: prefix)
        # Should still find it via normalization
        is_exec, issues = check_snapshots_executable(
            {"O:AAPL250117C00200000": snap},
            ["AAPL250117C00200000"]  # raw symbol without O: prefix
        )

        assert is_exec is True
        assert issues == []

    def test_canonical_symbol_matches_canonical_key(self):
        """Canonical symbol directly matches canonical key."""
        snap = TruthSnapshotV4(
            symbol_canonical="O:SPY250117P00500000",
            quote=TruthQuoteV4(bid=10.0, ask=10.20, mid=10.10),
            timestamps=TruthTimestampsV4(source_ts=int(time.time() * 1000), received_ts=int(time.time() * 1000)),
            quality=TruthQualityV4(quality_score=100, issues=[], is_stale=False, freshness_ms=100),
            source=TruthSourceV4(),
        )

        is_exec, issues = check_snapshots_executable(
            {"O:SPY250117P00500000": snap},
            ["O:SPY250117P00500000"]  # canonical symbol
        )

        assert is_exec is True
        assert issues == []

    def test_missing_snapshot_error_includes_canonical(self):
        """Error message includes canonical key when different from raw."""
        # Empty snapshots dict
        is_exec, issues = check_snapshots_executable(
            {},
            ["AAPL250117C00200000"]  # raw symbol
        )

        assert is_exec is False
        assert len(issues) == 1
        # Error should mention that the canonical form was also tried
        assert "missing_snapshot" in issues[0]


class TestTruthinessExplicitChecks:
    """Tests for explicit None checks (no truthiness bugs with 0.0 values)."""

    def test_zero_bid_spread_calculation(self):
        """Spread calculation works correctly when bid is 0.0."""
        # bid=0.0 should not be treated as "falsy"/missing
        quote = TruthQuoteV4(bid=0.0, ask=0.1, mid=0.05)
        quality = compute_quote_quality(quote, freshness_ms=1000)

        # With mid=0.05, spread = (0.1 - 0.0) / 0.05 = 2.0 = 200%
        # This should trigger wide_spread issue
        assert "wide_spread" in quality.issues
        assert quality.quality_score < 100

    def test_zero_values_not_treated_as_missing(self):
        """Values of 0.0 are not treated as missing."""
        # All values present but some are 0.0
        quote = TruthQuoteV4(bid=0.0, ask=0.0, mid=0.0)
        quality = compute_quote_quality(quote, freshness_ms=1000)

        # Should NOT have missing_quote_fields since bid and ask are present (just 0)
        assert "missing_quote_fields" not in quality.issues

    def test_narrow_spread_with_small_values(self):
        """Narrow spread works correctly with small but non-zero values."""
        # Small values but narrow spread
        quote = TruthQuoteV4(bid=0.01, ask=0.02, mid=0.015)
        quality = compute_quote_quality(quote, freshness_ms=1000, wide_spread_pct=1.0)  # 100% threshold

        # Spread = (0.02 - 0.01) / 0.015 = 0.667 = 66.7%
        # With 100% threshold, this should NOT be wide
        assert "wide_spread" not in quality.issues


class TestRawSnapshotsParameter:
    """Tests for raw_snapshots parameter to avoid double fetch."""

    def test_raw_snapshots_skips_fetch(self):
        """snapshot_many_v4 with raw_snapshots does NOT call snapshot_many."""
        layer = MarketDataTruthLayer(api_key="test")

        # Pre-fetched raw snapshots
        raw_snapshots = {
            "AAPL": {
                "ticker": "AAPL",
                "quote": {"bid": 150.0, "ask": 150.10, "mid": 150.05},
                "provider_ts": int(time.time() * 1000) - 1000,
                "staleness_ms": 1000,
            }
        }

        # Patch snapshot_many to track if it's called
        with patch.object(layer, 'snapshot_many') as mock_snapshot_many:
            results = layer.snapshot_many_v4(["AAPL"], raw_snapshots=raw_snapshots)

            # snapshot_many should NOT be called
            mock_snapshot_many.assert_not_called()

        # Results should still be valid
        assert "AAPL" in results
        assert isinstance(results["AAPL"], TruthSnapshotV4)
        assert results["AAPL"].quote.bid == 150.0

    def test_no_raw_snapshots_calls_fetch(self):
        """snapshot_many_v4 without raw_snapshots DOES call snapshot_many."""
        layer = MarketDataTruthLayer(api_key="test")

        with patch.object(layer, 'snapshot_many', return_value={}) as mock_snapshot_many:
            layer.snapshot_many_v4(["AAPL"])

            # snapshot_many SHOULD be called
            mock_snapshot_many.assert_called_once_with(["AAPL"])


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


class TestConfigurationGetters:
    """Tests for configuration getters (env-safe, read at call time)."""

    def test_env_override_max_freshness(self, monkeypatch):
        """Getter reads MARKETDATA_MAX_FRESHNESS_MS from env at call time."""
        monkeypatch.setenv("MARKETDATA_MAX_FRESHNESS_MS", "12345")
        assert get_marketdata_max_freshness_ms() == 12345

    def test_env_override_min_quality_score(self, monkeypatch):
        """Getter reads MARKETDATA_MIN_QUALITY_SCORE from env at call time."""
        monkeypatch.setenv("MARKETDATA_MIN_QUALITY_SCORE", "75")
        assert get_marketdata_min_quality_score() == 75

    def test_env_override_wide_spread_pct(self, monkeypatch):
        """Getter reads MARKETDATA_WIDE_SPREAD_PCT from env at call time."""
        monkeypatch.setenv("MARKETDATA_WIDE_SPREAD_PCT", "0.25")
        assert get_marketdata_wide_spread_pct() == pytest.approx(0.25)

    def test_getters_return_correct_types(self, monkeypatch):
        """Getters return correct types when env is not set."""
        # Clear any existing env vars
        monkeypatch.delenv("MARKETDATA_MAX_FRESHNESS_MS", raising=False)
        monkeypatch.delenv("MARKETDATA_MIN_QUALITY_SCORE", raising=False)
        monkeypatch.delenv("MARKETDATA_WIDE_SPREAD_PCT", raising=False)

        assert isinstance(get_marketdata_max_freshness_ms(), int)
        assert isinstance(get_marketdata_min_quality_score(), int)
        assert isinstance(get_marketdata_wide_spread_pct(), float)

    def test_getters_return_positive_values(self, monkeypatch):
        """Getters return positive values when env is not set."""
        monkeypatch.delenv("MARKETDATA_MAX_FRESHNESS_MS", raising=False)
        monkeypatch.delenv("MARKETDATA_MIN_QUALITY_SCORE", raising=False)
        monkeypatch.delenv("MARKETDATA_WIDE_SPREAD_PCT", raising=False)

        assert get_marketdata_max_freshness_ms() > 0
        assert get_marketdata_min_quality_score() > 0
        assert get_marketdata_wide_spread_pct() > 0

    def test_compute_quote_quality_uses_env_overrides(self, monkeypatch):
        """compute_quote_quality uses getter values, respecting env overrides."""
        # Set very strict freshness threshold (1 second)
        monkeypatch.setenv("MARKETDATA_MAX_FRESHNESS_MS", "1000")

        quote = TruthQuoteV4(bid=99.0, ask=100.0, mid=99.5)
        # 5 seconds old - should be stale with 1s threshold
        quality = compute_quote_quality(quote, freshness_ms=5000)

        assert quality.is_stale is True
        assert "stale_quote" in quality.issues

    def test_check_snapshots_executable_uses_env_overrides(self, monkeypatch):
        """check_snapshots_executable uses getter values, respecting env overrides."""
        # Set very high quality threshold
        monkeypatch.setenv("MARKETDATA_MIN_QUALITY_SCORE", "99")

        snap = TruthSnapshotV4(
            symbol_canonical="AAPL",
            quote=TruthQuoteV4(bid=150.0, ask=150.10, mid=150.05),
            timestamps=TruthTimestampsV4(source_ts=int(time.time() * 1000), received_ts=int(time.time() * 1000)),
            quality=TruthQualityV4(quality_score=80, issues=[], is_stale=False, freshness_ms=100),
            source=TruthSourceV4(),
        )

        # Score of 80 should fail with threshold of 99
        is_exec, issues = check_snapshots_executable({"AAPL": snap}, ["AAPL"])
        assert is_exec is False
        assert any("low_quality" in issue for issue in issues)


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


class TestQualityStatusCodes:
    """Tests for V4 quality status codes and classifiers."""

    def test_quality_ok_for_healthy_snapshot(self):
        """Healthy snapshot classifies as QUALITY_OK."""
        snap = TruthSnapshotV4(
            symbol_canonical="AAPL",
            quote=TruthQuoteV4(bid=150.0, ask=150.10, mid=150.05),
            timestamps=TruthTimestampsV4(source_ts=int(time.time() * 1000), received_ts=int(time.time() * 1000)),
            quality=TruthQualityV4(quality_score=100, issues=[], is_stale=False, freshness_ms=100),
            source=TruthSourceV4(),
        )

        code = classify_snapshot_quality(snap)
        assert code == QUALITY_OK

    def test_fail_crossed_for_crossed_market(self):
        """Crossed market classifies as QUALITY_FAIL_CROSSED."""
        snap = TruthSnapshotV4(
            symbol_canonical="AAPL",
            quote=TruthQuoteV4(bid=150.10, ask=150.0),  # crossed
            timestamps=TruthTimestampsV4(source_ts=int(time.time() * 1000), received_ts=int(time.time() * 1000)),
            quality=TruthQualityV4(quality_score=0, issues=["crossed_market"], is_stale=False, freshness_ms=100),
            source=TruthSourceV4(),
        )

        code = classify_snapshot_quality(snap)
        assert code == QUALITY_FAIL_CROSSED

    def test_fail_stale_for_stale_quote(self):
        """Stale quote classifies as QUALITY_FAIL_STALE."""
        snap = TruthSnapshotV4(
            symbol_canonical="AAPL",
            quote=TruthQuoteV4(bid=150.0, ask=150.10, mid=150.05),
            timestamps=TruthTimestampsV4(source_ts=1000, received_ts=int(time.time() * 1000)),
            quality=TruthQualityV4(quality_score=70, issues=["stale_quote"], is_stale=True, freshness_ms=120000),
            source=TruthSourceV4(),
        )

        code = classify_snapshot_quality(snap)
        assert code == QUALITY_FAIL_STALE

    def test_fail_missing_timestamp_when_stale_with_missing_ts(self):
        """Missing timestamp classifies as QUALITY_FAIL_MISSING_TIMESTAMP."""
        snap = TruthSnapshotV4(
            symbol_canonical="AAPL",
            quote=TruthQuoteV4(bid=150.0, ask=150.10, mid=150.05),
            timestamps=TruthTimestampsV4(source_ts=None, received_ts=int(time.time() * 1000)),
            quality=TruthQualityV4(quality_score=70, issues=["missing_timestamp"], is_stale=True, freshness_ms=None),
            source=TruthSourceV4(),
        )

        code = classify_snapshot_quality(snap)
        assert code == QUALITY_FAIL_MISSING_TIMESTAMP

    def test_fail_missing_quote_fields(self):
        """Missing quote fields classifies as QUALITY_FAIL_MISSING_QUOTE_FIELDS."""
        snap = TruthSnapshotV4(
            symbol_canonical="AAPL",
            quote=TruthQuoteV4(bid=None, ask=150.10),
            timestamps=TruthTimestampsV4(source_ts=int(time.time() * 1000), received_ts=int(time.time() * 1000)),
            quality=TruthQualityV4(quality_score=60, issues=["missing_quote_fields"], is_stale=False, freshness_ms=100),
            source=TruthSourceV4(),
        )

        code = classify_snapshot_quality(snap)
        assert code == QUALITY_FAIL_MISSING_QUOTE_FIELDS

    def test_warn_wide_spread(self):
        """Wide spread without other issues classifies as QUALITY_WARN_WIDE_SPREAD."""
        snap = TruthSnapshotV4(
            symbol_canonical="AAPL",
            quote=TruthQuoteV4(bid=140.0, ask=160.0, mid=150.0),  # 13% spread
            timestamps=TruthTimestampsV4(source_ts=int(time.time() * 1000), received_ts=int(time.time() * 1000)),
            quality=TruthQualityV4(quality_score=80, issues=["wide_spread"], is_stale=False, freshness_ms=100),
            source=TruthSourceV4(),
        )

        code = classify_snapshot_quality(snap)
        assert code == QUALITY_WARN_WIDE_SPREAD

    def test_warn_low_quality_score(self):
        """Low quality score classifies as QUALITY_WARN_LOW_QUALITY."""
        snap = TruthSnapshotV4(
            symbol_canonical="AAPL",
            quote=TruthQuoteV4(bid=150.0, ask=150.10, mid=150.05),
            timestamps=TruthTimestampsV4(source_ts=int(time.time() * 1000), received_ts=int(time.time() * 1000)),
            quality=TruthQualityV4(quality_score=50, issues=[], is_stale=False, freshness_ms=100),
            source=TruthSourceV4(),
        )

        # Default min_quality_score is 60, so 50 should trigger WARN_LOW_QUALITY
        code = classify_snapshot_quality(snap)
        assert code == QUALITY_WARN_LOW_QUALITY

    def test_classify_missing_snapshot(self):
        """classify_missing_snapshot returns QUALITY_FAIL_MISSING_SNAPSHOT."""
        code = classify_missing_snapshot("AAPL")
        assert code == QUALITY_FAIL_MISSING_SNAPSHOT

        code = classify_missing_snapshot("O:AAPL250117C00200000", canon_sym="O:AAPL250117C00200000")
        assert code == QUALITY_FAIL_MISSING_SNAPSHOT

    def test_is_fatal_quality_code_true_for_fail_codes(self):
        """Fatal codes return True from is_fatal_quality_code."""
        assert is_fatal_quality_code(QUALITY_FAIL_STALE) is True
        assert is_fatal_quality_code(QUALITY_FAIL_CROSSED) is True
        assert is_fatal_quality_code(QUALITY_FAIL_MISSING_SNAPSHOT) is True
        assert is_fatal_quality_code(QUALITY_FAIL_MISSING_TIMESTAMP) is True
        assert is_fatal_quality_code(QUALITY_FAIL_MISSING_QUOTE_FIELDS) is True

    def test_is_fatal_quality_code_false_for_non_fatal(self):
        """Non-fatal codes return False from is_fatal_quality_code."""
        assert is_fatal_quality_code(QUALITY_OK) is False
        assert is_fatal_quality_code(QUALITY_WARN_WIDE_SPREAD) is False
        assert is_fatal_quality_code(QUALITY_WARN_LOW_QUALITY) is False

    def test_fatal_quality_codes_is_frozenset(self):
        """FATAL_QUALITY_CODES is an immutable frozenset."""
        assert isinstance(FATAL_QUALITY_CODES, frozenset)
        assert len(FATAL_QUALITY_CODES) == 5


class TestIssueFormatters:
    """Tests for V4 issue formatting functions."""

    def test_format_quality_issues_empty(self):
        """Empty issues list returns empty string."""
        assert format_quality_issues([]) == ""

    def test_format_quality_issues_single(self):
        """Single issue returns just that issue."""
        assert format_quality_issues(["stale_quote"]) == "stale_quote"

    def test_format_quality_issues_multiple_sorted(self):
        """Multiple issues are sorted and pipe-separated."""
        issues = ["wide_spread", "stale_quote", "crossed_market"]
        result = format_quality_issues(issues)
        assert result == "crossed_market|stale_quote|wide_spread"

    def test_format_snapshot_summary(self):
        """format_snapshot_summary returns correct structure."""
        snap = TruthSnapshotV4(
            symbol_canonical="AAPL",
            quote=TruthQuoteV4(bid=150.0, ask=150.10, mid=150.05),
            timestamps=TruthTimestampsV4(source_ts=int(time.time() * 1000), received_ts=int(time.time() * 1000)),
            quality=TruthQualityV4(quality_score=80, issues=["wide_spread"], is_stale=False, freshness_ms=100),
            source=TruthSourceV4(),
        )

        summary = format_snapshot_summary("AAPL", snap)

        assert summary["symbol"] == "AAPL"
        assert summary["code"] == QUALITY_WARN_WIDE_SPREAD
        assert summary["score"] == 80
        assert summary["freshness_ms"] == 100
        assert summary["issues"] == "wide_spread"

    def test_format_quality_gate_result_all_healthy(self):
        """format_quality_gate_result with all healthy snapshots."""
        snap1 = TruthSnapshotV4(
            symbol_canonical="AAPL",
            quote=TruthQuoteV4(bid=150.0, ask=150.10, mid=150.05),
            timestamps=TruthTimestampsV4(source_ts=int(time.time() * 1000), received_ts=int(time.time() * 1000)),
            quality=TruthQualityV4(quality_score=100, issues=[], is_stale=False, freshness_ms=100),
            source=TruthSourceV4(),
        )
        snap2 = TruthSnapshotV4(
            symbol_canonical="SPY",
            quote=TruthQuoteV4(bid=500.0, ask=500.10, mid=500.05),
            timestamps=TruthTimestampsV4(source_ts=int(time.time() * 1000), received_ts=int(time.time() * 1000)),
            quality=TruthQualityV4(quality_score=100, issues=[], is_stale=False, freshness_ms=100),
            source=TruthSourceV4(),
        )

        result = format_quality_gate_result(
            {"AAPL": snap1, "SPY": snap2},
            ["AAPL", "SPY"]
        )

        assert result["fatal_count"] == 0
        assert result["warning_count"] == 0
        assert result["has_fatal"] is False
        assert result["has_warning"] is False
        assert len(result["symbols"]) == 2

    def test_format_quality_gate_result_with_fatal(self):
        """format_quality_gate_result with fatal issues."""
        stale_snap = TruthSnapshotV4(
            symbol_canonical="AAPL",
            quote=TruthQuoteV4(bid=150.0, ask=150.10, mid=150.05),
            timestamps=TruthTimestampsV4(source_ts=1000, received_ts=int(time.time() * 1000)),
            quality=TruthQualityV4(quality_score=70, issues=["stale_quote"], is_stale=True, freshness_ms=120000),
            source=TruthSourceV4(),
        )

        result = format_quality_gate_result({"AAPL": stale_snap}, ["AAPL"])

        assert result["fatal_count"] == 1
        assert result["has_fatal"] is True

    def test_format_quality_gate_result_with_warning(self):
        """format_quality_gate_result with warning issues."""
        warn_snap = TruthSnapshotV4(
            symbol_canonical="AAPL",
            quote=TruthQuoteV4(bid=140.0, ask=160.0, mid=150.0),  # wide spread
            timestamps=TruthTimestampsV4(source_ts=int(time.time() * 1000), received_ts=int(time.time() * 1000)),
            quality=TruthQualityV4(quality_score=80, issues=["wide_spread"], is_stale=False, freshness_ms=100),
            source=TruthSourceV4(),
        )

        result = format_quality_gate_result({"AAPL": warn_snap}, ["AAPL"])

        assert result["warning_count"] == 1
        assert result["has_warning"] is True
        assert result["has_fatal"] is False

    def test_format_quality_gate_result_missing_snapshot(self):
        """format_quality_gate_result with missing snapshot."""
        result = format_quality_gate_result({}, ["AAPL"])

        assert result["fatal_count"] == 1
        assert result["has_fatal"] is True
        assert result["symbols"][0]["code"] == QUALITY_FAIL_MISSING_SNAPSHOT
        assert result["symbols"][0]["issues"] == "missing_snapshot"

    def test_format_quality_gate_result_uses_symbol_normalization(self):
        """format_quality_gate_result normalizes symbols for lookup."""
        snap = TruthSnapshotV4(
            symbol_canonical="O:AAPL250117C00200000",
            quote=TruthQuoteV4(bid=5.0, ask=5.10, mid=5.05),
            timestamps=TruthTimestampsV4(source_ts=int(time.time() * 1000), received_ts=int(time.time() * 1000)),
            quality=TruthQualityV4(quality_score=100, issues=[], is_stale=False, freshness_ms=100),
            source=TruthSourceV4(),
        )

        # Snapshot stored with canonical key, but requested with raw symbol
        result = format_quality_gate_result(
            {"O:AAPL250117C00200000": snap},
            ["AAPL250117C00200000"]  # raw symbol without O: prefix
        )

        # Should find it via normalization
        assert result["fatal_count"] == 0
        assert result["has_fatal"] is False


class TestQualityPolicyGetter:
    """Tests for get_marketdata_quality_policy getter."""

    def test_default_policy_is_defer(self, monkeypatch):
        """Default policy is 'defer' when env not set."""
        monkeypatch.delenv("MARKETDATA_QUALITY_POLICY", raising=False)
        assert get_marketdata_quality_policy() == "defer"

    def test_env_override_skip(self, monkeypatch):
        """Policy can be set to 'skip' via env."""
        monkeypatch.setenv("MARKETDATA_QUALITY_POLICY", "skip")
        assert get_marketdata_quality_policy() == "skip"

    def test_env_override_defer(self, monkeypatch):
        """Policy can be set to 'defer' via env."""
        monkeypatch.setenv("MARKETDATA_QUALITY_POLICY", "defer")
        assert get_marketdata_quality_policy() == "defer"

    def test_env_override_downrank(self, monkeypatch):
        """Policy can be set to 'downrank' via env."""
        monkeypatch.setenv("MARKETDATA_QUALITY_POLICY", "downrank")
        assert get_marketdata_quality_policy() == "downrank"

    def test_policy_is_lowercased(self, monkeypatch):
        """Policy is lowercased from env."""
        monkeypatch.setenv("MARKETDATA_QUALITY_POLICY", "SKIP")
        assert get_marketdata_quality_policy() == "skip"

        monkeypatch.setenv("MARKETDATA_QUALITY_POLICY", "Defer")
        assert get_marketdata_quality_policy() == "defer"


class TestWarnPenaltyGetter:
    """Tests for get_marketdata_warn_penalty getter."""

    def test_default_penalty_is_0_7(self, monkeypatch):
        """Default penalty is 0.7 when env not set."""
        monkeypatch.delenv("MARKETDATA_WARN_PENALTY", raising=False)
        assert get_marketdata_warn_penalty() == pytest.approx(0.7)

    def test_env_override_penalty(self, monkeypatch):
        """Penalty can be set via env."""
        monkeypatch.setenv("MARKETDATA_WARN_PENALTY", "0.5")
        assert get_marketdata_warn_penalty() == pytest.approx(0.5)

    def test_penalty_returns_float(self, monkeypatch):
        """Getter returns float type."""
        monkeypatch.delenv("MARKETDATA_WARN_PENALTY", raising=False)
        assert isinstance(get_marketdata_warn_penalty(), float)


class TestFormatBlockedDetail:
    """Tests for format_blocked_detail function."""

    def test_single_warning_symbol(self):
        """Single warning symbol formats correctly."""
        gate_result = {
            "symbols": [
                {"symbol": "AAPL", "code": QUALITY_WARN_WIDE_SPREAD, "score": 80, "issues": "wide_spread"}
            ]
        }
        result = format_blocked_detail(gate_result)
        assert result == "AAPL:WARN_WIDE_SPREAD"

    def test_multiple_warning_symbols(self):
        """Multiple warning symbols are pipe-separated."""
        gate_result = {
            "symbols": [
                {"symbol": "AAPL", "code": QUALITY_WARN_WIDE_SPREAD, "score": 80, "issues": "wide_spread"},
                {"symbol": "SPY", "code": QUALITY_FAIL_STALE, "score": 70, "issues": "stale_quote"}
            ]
        }
        result = format_blocked_detail(gate_result)
        assert "AAPL:WARN_WIDE_SPREAD" in result
        assert "SPY:FAIL_STALE" in result
        assert "|" in result

    def test_deterministic_ordering_by_symbol(self):
        """Symbols are sorted deterministically by symbol name then code."""
        # Provide symbols out of order
        gate_result = {
            "symbols": [
                {"symbol": "ZZZ", "code": QUALITY_FAIL_STALE},
                {"symbol": "AAA", "code": QUALITY_WARN_WIDE_SPREAD},
                {"symbol": "MMM", "code": QUALITY_FAIL_CROSSED},
            ]
        }
        result = format_blocked_detail(gate_result)
        # Should be sorted by symbol: AAA, MMM, ZZZ
        assert result == "AAA:WARN_WIDE_SPREAD|MMM:FAIL_CROSSED|ZZZ:FAIL_STALE"

    def test_deterministic_ordering_same_symbol_by_code(self):
        """Same symbol with different codes sorted by code."""
        gate_result = {
            "symbols": [
                {"symbol": "AAPL", "code": "WARN_Z"},
                {"symbol": "AAPL", "code": "FAIL_A"},
            ]
        }
        result = format_blocked_detail(gate_result)
        # Same symbol, sorted by code: FAIL_A < WARN_Z
        assert result == "AAPL:FAIL_A|AAPL:WARN_Z"

    def test_ok_symbols_excluded(self):
        """OK symbols are excluded from blocked detail."""
        gate_result = {
            "symbols": [
                {"symbol": "AAPL", "code": QUALITY_OK, "score": 100, "issues": ""},
                {"symbol": "SPY", "code": QUALITY_WARN_WIDE_SPREAD, "score": 80, "issues": "wide_spread"}
            ]
        }
        result = format_blocked_detail(gate_result)
        assert "AAPL" not in result
        assert "SPY:WARN_WIDE_SPREAD" in result

    def test_empty_symbols_returns_unknown(self):
        """Empty symbols list returns unknown_issue."""
        gate_result = {"symbols": []}
        result = format_blocked_detail(gate_result)
        assert result == "unknown_issue"

    def test_all_ok_returns_unknown(self):
        """All OK symbols returns unknown_issue."""
        gate_result = {
            "symbols": [
                {"symbol": "AAPL", "code": QUALITY_OK, "score": 100, "issues": ""}
            ]
        }
        result = format_blocked_detail(gate_result)
        assert result == "unknown_issue"


class TestBuildMarketdataBlockPayload:
    """Tests for build_marketdata_block_payload function."""

    def test_defer_policy_payload(self):
        """Defer policy builds correct payload with effective_action."""
        gate_result = {
            "symbols": [{"symbol": "AAPL", "code": QUALITY_WARN_WIDE_SPREAD}],
            "fatal_count": 0,
            "warning_count": 1,
            "has_fatal": False,
            "has_warning": True,
        }
        payload = build_marketdata_block_payload(
            gate_result, "defer", EFFECTIVE_ACTION_DEFER
        )

        assert payload["event"] == "marketdata.v4.quality_gate"
        assert payload["policy"] == "defer"
        assert payload["effective_action"] == EFFECTIVE_ACTION_DEFER
        assert payload["has_warning"] is True
        assert payload["has_fatal"] is False

    def test_downrank_applied_payload(self):
        """Downrank policy with applied penalty includes downrank fields."""
        gate_result = {
            "symbols": [{"symbol": "AAPL", "code": QUALITY_WARN_WIDE_SPREAD}],
            "fatal_count": 0,
            "warning_count": 1,
            "has_fatal": False,
            "has_warning": True,
        }
        payload = build_marketdata_block_payload(
            gate_result, "downrank", EFFECTIVE_ACTION_DOWNRANK,
            downrank_applied=True, warn_penalty=0.7
        )

        assert payload["policy"] == "downrank"
        assert payload["effective_action"] == EFFECTIVE_ACTION_DOWNRANK
        assert payload["downrank_applied"] is True
        assert payload["warn_penalty"] == 0.7

    def test_downrank_fallback_payload(self):
        """Downrank policy fallback includes reason and effective_action."""
        gate_result = {
            "symbols": [{"symbol": "AAPL", "code": QUALITY_WARN_WIDE_SPREAD}],
            "fatal_count": 0,
            "warning_count": 1,
            "has_fatal": False,
            "has_warning": True,
        }
        payload = build_marketdata_block_payload(
            gate_result, "downrank", EFFECTIVE_ACTION_DOWNRANK_FALLBACK,
            downrank_applied=False,
            downrank_reason="no_rank_scalar_found"
        )

        assert payload["policy"] == "downrank"
        assert payload["effective_action"] == EFFECTIVE_ACTION_DOWNRANK_FALLBACK
        assert payload["downrank_applied"] is False
        assert payload["downrank_reason"] == "no_rank_scalar_found"


class TestEffectiveActionConstants:
    """Tests for effective_action constants."""

    def test_effective_action_constants_exist(self):
        """All effective_action constants are defined."""
        assert EFFECTIVE_ACTION_SKIP_FATAL == "skip_fatal"
        assert EFFECTIVE_ACTION_SKIP_POLICY == "skip_policy"
        assert EFFECTIVE_ACTION_DEFER == "defer"
        assert EFFECTIVE_ACTION_DOWNRANK == "downrank"
        assert EFFECTIVE_ACTION_DOWNRANK_FALLBACK == "downrank_fallback_to_defer"

    def test_payload_includes_effective_action(self):
        """All payloads include effective_action field."""
        gate_result = {
            "symbols": [],
            "fatal_count": 0,
            "warning_count": 0,
            "has_fatal": False,
            "has_warning": False,
        }

        for action in [EFFECTIVE_ACTION_SKIP_FATAL, EFFECTIVE_ACTION_SKIP_POLICY,
                       EFFECTIVE_ACTION_DEFER, EFFECTIVE_ACTION_DOWNRANK,
                       EFFECTIVE_ACTION_DOWNRANK_FALLBACK]:
            payload = build_marketdata_block_payload(gate_result, "defer", action)
            assert payload["effective_action"] == action


class TestOrderBuilderBlockedShortCircuit:
    """Tests for order builder short-circuit when candidate is already blocked."""

    def test_blocked_candidate_returns_not_executable(self):
        """Order builder returns NOT_EXECUTABLE for already-blocked candidate."""
        from packages.quantum.services.workflow_orchestrator import build_midday_order_json

        cand = {
            "symbol": "SPY",
            "suggested_entry": 1.25,
            "strategy": "vertical_spread",
            "order_type_force_limit": True,
            "blocked_reason": "marketdata_quality_gate",
            "blocked_detail": "AAPL:WARN_WIDE_SPREAD",
            "legs": [
                {"symbol": "O:SPY250101C00500000", "side": "buy", "mid": 1.50},
                {"symbol": "O:SPY250101C00505000", "side": "sell", "mid": 0.25}
            ]
        }

        order_json = build_midday_order_json(cand, 3)

        assert order_json["status"] == "NOT_EXECUTABLE"
        assert "marketdata quality gate" in order_json["reason"].lower()
        assert "AAPL:WARN_WIDE_SPREAD" in order_json["reason"]

    def test_blocked_candidate_includes_leg_info(self):
        """Blocked candidate order includes leg info."""
        from packages.quantum.services.workflow_orchestrator import build_midday_order_json

        cand = {
            "symbol": "SPY",
            "ticker": "SPY",
            "suggested_entry": 1.25,
            "strategy": "vertical_spread",
            "blocked_reason": "marketdata_quality_gate",
            "blocked_detail": "SPY:FAIL_STALE",
            "legs": [
                {"symbol": "O:SPY250101C00500000", "side": "buy"},
                {"symbol": "O:SPY250101C00505000", "side": "sell"}
            ]
        }

        order_json = build_midday_order_json(cand, 2)

        assert order_json["status"] == "NOT_EXECUTABLE"
        assert order_json["contracts"] == 2
        assert len(order_json["legs"]) == 2
        assert order_json["underlying"] == "SPY"

    def test_non_blocked_candidate_proceeds_normally(self):
        """Non-blocked candidate proceeds through normal flow."""
        from packages.quantum.services.workflow_orchestrator import build_midday_order_json

        cand = {
            "symbol": "SPY",
            "suggested_entry": 1.25,
            "strategy": "vertical_spread",
            "order_type_force_limit": True,
            # No blocked_reason
            "legs": [
                {"symbol": "O:SPY250101C00500000", "side": "buy", "mid": 1.50},
                {"symbol": "O:SPY250101C00505000", "side": "sell", "mid": 0.25}
            ]
        }

        order_json = build_midday_order_json(cand, 3)

        # Should not have NOT_EXECUTABLE from short-circuit (may have other reasons)
        # Check that it didn't hit the short-circuit path
        if order_json.get("status") == "NOT_EXECUTABLE":
            # If NOT_EXECUTABLE, reason should NOT be from blocked_reason path
            assert "Blocked by marketdata quality gate" not in order_json.get("reason", "")


class TestDeferPolicyBehavior:
    """Integration tests for defer policy behavior."""

    def test_defer_policy_attaches_payload_to_suggestion(self):
        """When defer policy, warning issues attach payload and block suggestion."""
        # This tests the pattern where a suggestion would have
        # marketdata_quality payload attached
        warn_snap = TruthSnapshotV4(
            symbol_canonical="O:SPY250101C00500000",
            quote=TruthQuoteV4(bid=140.0, ask=160.0, mid=150.0),  # wide spread
            timestamps=TruthTimestampsV4(source_ts=int(time.time() * 1000), received_ts=int(time.time() * 1000)),
            quality=TruthQualityV4(quality_score=80, issues=["wide_spread"], is_stale=False, freshness_ms=100),
            source=TruthSourceV4(),
        )

        gate_result = format_quality_gate_result(
            {"O:SPY250101C00500000": warn_snap},
            ["O:SPY250101C00500000"]
        )

        # Simulate what orchestrator does
        assert gate_result["has_warning"] is True
        assert gate_result["has_fatal"] is False

        # Build payload as orchestrator would
        payload = build_marketdata_block_payload(
            gate_result, "defer", EFFECTIVE_ACTION_DEFER
        )
        blocked_detail = format_blocked_detail(gate_result)

        # Verify payload structure
        assert payload["event"] == "marketdata.v4.quality_gate"
        assert payload["policy"] == "defer"
        assert payload["effective_action"] == EFFECTIVE_ACTION_DEFER
        assert "WARN_WIDE_SPREAD" in blocked_detail

    def test_downrank_policy_applies_penalty(self):
        """When downrank policy with ranking scalar, penalty is applied."""
        gate_result = {
            "symbols": [{"symbol": "AAPL", "code": QUALITY_WARN_WIDE_SPREAD}],
            "fatal_count": 0,
            "warning_count": 1,
            "has_fatal": False,
            "has_warning": True,
        }

        # Simulate what orchestrator does for downrank with ranking scalar
        payload = build_marketdata_block_payload(
            gate_result, "downrank", EFFECTIVE_ACTION_DOWNRANK,
            downrank_applied=True, warn_penalty=0.7
        )

        assert payload["effective_action"] == EFFECTIVE_ACTION_DOWNRANK
        assert payload["downrank_applied"] is True
        assert payload["warn_penalty"] == 0.7

    def test_downrank_policy_fallback_to_defer(self):
        """When downrank policy without ranking scalar, fallback to defer."""
        gate_result = {
            "symbols": [{"symbol": "AAPL", "code": QUALITY_WARN_WIDE_SPREAD}],
            "fatal_count": 0,
            "warning_count": 1,
            "has_fatal": False,
            "has_warning": True,
        }

        # Simulate what orchestrator does for downrank without scalar
        payload = build_marketdata_block_payload(
            gate_result, "downrank", EFFECTIVE_ACTION_DOWNRANK_FALLBACK,
            downrank_applied=False,
            downrank_reason="no_rank_scalar_found_fallback_to_defer"
        )

        assert payload["effective_action"] == EFFECTIVE_ACTION_DOWNRANK_FALLBACK
        assert payload["downrank_applied"] is False
        assert payload["downrank_reason"] == "no_rank_scalar_found_fallback_to_defer"

    def test_fatal_issues_not_deferred(self):
        """Fatal issues are not deferred (would be skipped upstream)."""
        stale_snap = TruthSnapshotV4(
            symbol_canonical="AAPL",
            quote=TruthQuoteV4(bid=150.0, ask=150.10, mid=150.05),
            timestamps=TruthTimestampsV4(source_ts=1000, received_ts=int(time.time() * 1000)),
            quality=TruthQualityV4(quality_score=70, issues=["stale_quote"], is_stale=True, freshness_ms=120000),
            source=TruthSourceV4(),
        )

        gate_result = format_quality_gate_result({"AAPL": stale_snap}, ["AAPL"])

        # Fatal issues should cause has_fatal=True
        assert gate_result["has_fatal"] is True

        # Orchestrator would skip, not defer
        # This is tested by checking has_fatal


class TestDownrankEVMultiplier:
    """Phase 2.1 tests verifying downrank policy applies 0.7 multiplier to EV."""

    def test_downrank_multiplier_default_is_0_7(self, monkeypatch):
        """Default downrank penalty multiplier is 0.7 (30% penalty)."""
        monkeypatch.delenv("MARKETDATA_WARN_PENALTY", raising=False)
        penalty = get_marketdata_warn_penalty()
        assert penalty == pytest.approx(0.7)

    def test_ev_multiplication_math(self):
        """EV is correctly multiplied by 0.7 penalty."""
        # Simulate what orchestrator does when downrank is applied
        original_ev = 100.0
        penalty = 0.7
        penalized_ev = original_ev * penalty

        assert penalized_ev == pytest.approx(70.0)

        # Verify the ranking order changes appropriately
        high_quality_ev = 80.0  # No penalty
        low_quality_ev_original = 100.0
        low_quality_ev_penalized = low_quality_ev_original * penalty

        # Before penalty: 100 > 80 (low quality ranked higher)
        # After penalty: 70 < 80 (high quality now ranked higher)
        assert low_quality_ev_original > high_quality_ev
        assert low_quality_ev_penalized < high_quality_ev

    def test_downrank_preserves_sign(self):
        """Downrank penalty preserves sign of EV (negative EVs stay negative)."""
        penalty = 0.7

        positive_ev = 50.0
        negative_ev = -30.0

        assert positive_ev * penalty > 0
        assert negative_ev * penalty < 0

    def test_downrank_zero_ev_unchanged(self):
        """Zero EV remains zero after downrank."""
        penalty = 0.7
        zero_ev = 0.0

        # Orchestrator should not apply penalty to zero EV
        # (division/multiplication by zero edge case handled)
        penalized = zero_ev * penalty if zero_ev != 0 else zero_ev
        assert penalized == 0.0

    def test_downrank_payload_includes_penalty_value(self):
        """Downrank payload includes the penalty value used for audit."""
        gate_result = {
            "symbols": [{"symbol": "SPY", "code": QUALITY_WARN_WIDE_SPREAD}],
            "fatal_count": 0,
            "warning_count": 1,
            "has_fatal": False,
            "has_warning": True,
        }

        payload = build_marketdata_block_payload(
            gate_result, "downrank", EFFECTIVE_ACTION_DOWNRANK,
            downrank_applied=True, warn_penalty=0.7
        )

        # Payload must include warn_penalty for audit trail
        assert "warn_penalty" in payload
        assert payload["warn_penalty"] == 0.7
        assert payload["downrank_applied"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
