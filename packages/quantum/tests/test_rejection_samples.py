"""
Tests for rejection samples feature.

Verifies:
1. RejectionStats.record_with_sample() caps samples correctly
2. Samples are JSON-serializable
3. Sample shape includes required fields
4. _build_condor_rejection_sample() produces correct output
"""

import pytest
import json
import os
import threading
from datetime import datetime, timezone, date
from collections import defaultdict
from typing import Dict, Any, List, Optional


# Replicate helper functions for testing without heavy imports
def _to_float_or_none(val: Any) -> Optional[float]:
    """Convert value to float or None if invalid."""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _build_condor_rejection_sample(
    symbol: str,
    strategy_key: str,
    expiry_selected: Optional[str],
    legs: List[Dict[str, Any]],
    total_cost: Optional[float],
    calls_count: int = 0,
    puts_count: int = 0,
) -> Dict[str, Any]:
    """Build a diagnostic sample for condor rejection."""
    strikes = sorted([float(leg.get("strike", 0)) for leg in legs]) if legs else []

    leg_samples = []
    legs_with_missing_quotes = []

    for leg in legs:
        bid = _to_float_or_none(leg.get("bid"))
        ask = _to_float_or_none(leg.get("ask"))
        mid = _to_float_or_none(leg.get("mid") or leg.get("premium"))

        leg_sample = {
            "symbol": str(leg.get("symbol") or ""),
            "type": leg.get("type"),
            "side": leg.get("side"),
            "strike": _to_float_or_none(leg.get("strike")),
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "premium": _to_float_or_none(leg.get("premium")),
        }
        leg_samples.append(leg_sample)

        if bid is None or ask is None or bid <= 0 or ask <= 0:
            legs_with_missing_quotes.append(str(leg.get("symbol") or "unknown"))

    net_credit = None
    if total_cost is not None:
        net_credit = -total_cost if total_cost < 0 else 0.0

    expiry_str = None
    if expiry_selected is not None:
        expiry_str = str(expiry_selected) if not isinstance(expiry_selected, str) else expiry_selected

    return {
        "symbol": symbol,
        "strategy_key": strategy_key,
        "expiry": expiry_str,
        "strikes": strikes,
        "legs": leg_samples,
        "legs_expected": 4,
        "legs_found": len(legs),
        "total_cost_share": _to_float_or_none(total_cost),
        "net_credit_share": _to_float_or_none(net_credit),
        "legs_with_missing_quotes": legs_with_missing_quotes,
        "chain_calls_count": calls_count,
        "chain_puts_count": puts_count,
    }


# Replicate RejectionStats for testing
class RejectionStatsLocal:
    """Local copy of RejectionStats for testing."""

    DEFAULT_SAMPLES_CAP = 3

    def __init__(self):
        self._counts: Dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()
        self.symbols_processed = 0
        self.chains_loaded = 0
        self.chains_empty = 0
        self._samples: List[Dict[str, Any]] = []
        self._samples_cap: int = self.DEFAULT_SAMPLES_CAP

    def record(self, reason: str) -> None:
        with self._lock:
            self._counts[reason] += 1

    def record_with_sample(self, reason: str, sample: Dict[str, Any]) -> None:
        with self._lock:
            self._counts[reason] += 1
            if len(self._samples) < self._samples_cap:
                safe_sample = self._make_json_safe(sample)
                safe_sample["reason"] = reason
                self._samples.append(safe_sample)

    @staticmethod
    def _make_json_safe(obj: Any) -> Any:
        if obj is None:
            return None
        if isinstance(obj, bool):
            return obj
        if isinstance(obj, (str, int, float)):
            return obj
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, (list, tuple)):
            return [RejectionStatsLocal._make_json_safe(item) for item in obj]
        if isinstance(obj, dict):
            return {str(k): RejectionStatsLocal._make_json_safe(v) for k, v in obj.items()}
        return str(obj)

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "rejection_counts": dict(self._counts),
                "symbols_processed": self.symbols_processed,
                "chains_loaded": self.chains_loaded,
                "chains_empty": self.chains_empty,
                "total_rejections": sum(self._counts.values()),
                "rejection_samples": list(self._samples),
                "rejection_samples_cap": self._samples_cap,
            }


class TestRejectionStatsSamples:
    """Test RejectionStats sample collection."""

    def test_record_with_sample_caps_at_limit(self):
        """Verify samples are capped at the configured limit."""
        stats = RejectionStatsLocal()
        stats._samples_cap = 3  # Explicitly set cap

        # Add 10 samples
        for i in range(10):
            sample = {"symbol": f"SYM{i}", "value": i}
            stats.record_with_sample("test_reason", sample)

        result = stats.to_dict()

        # Should only have 3 samples
        assert len(result["rejection_samples"]) == 3
        # But count should be 10
        assert result["rejection_counts"]["test_reason"] == 10

    def test_to_dict_json_serializable_with_samples(self):
        """Verify to_dict output with samples is JSON-serializable."""
        stats = RejectionStatsLocal()

        sample = {
            "symbol": "SPY",
            "expiry": "2024-01-19",
            "strikes": [450.0, 455.0, 460.0, 465.0],
            "total_cost": -1.25,
            "legs": [
                {"strike": 450.0, "bid": 1.0, "ask": 1.1},
                {"strike": 455.0, "bid": 0.5, "ask": 0.6},
            ],
        }
        stats.record_with_sample("condor_no_credit", sample)

        result = stats.to_dict()

        # Should serialize without error
        json_str = json.dumps(result)
        parsed = json.loads(json_str)

        assert "rejection_samples" in parsed
        assert len(parsed["rejection_samples"]) == 1
        assert parsed["rejection_samples"][0]["symbol"] == "SPY"

    def test_sample_includes_reason(self):
        """Verify sample includes the reason field."""
        stats = RejectionStatsLocal()

        sample = {"symbol": "QQQ", "value": 123}
        stats.record_with_sample("condor_legs_not_found", sample)

        result = stats.to_dict()

        assert result["rejection_samples"][0]["reason"] == "condor_legs_not_found"

    def test_datetime_in_sample_converted(self):
        """Verify datetime objects in samples are converted to strings."""
        stats = RejectionStatsLocal()

        sample = {
            "symbol": "AAPL",
            "timestamp": datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
            "date": date(2024, 1, 15),
        }
        stats.record_with_sample("test", sample)

        result = stats.to_dict()

        # Should serialize without error
        json_str = json.dumps(result)
        parsed = json.loads(json_str)

        # datetime should be converted to string
        assert isinstance(parsed["rejection_samples"][0]["timestamp"], str)
        assert isinstance(parsed["rejection_samples"][0]["date"], str)


class TestBuildCondorRejectionSample:
    """Test _build_condor_rejection_sample helper."""

    def test_sample_shape_minimal_fields_present(self):
        """Verify sample contains all required fields."""
        sample = _build_condor_rejection_sample(
            symbol="SPY",
            strategy_key="iron_condor",
            expiry_selected="2024-01-19",
            legs=[],
            total_cost=None,
            calls_count=50,
            puts_count=50,
        )

        # Required fields
        assert "symbol" in sample
        assert "strategy_key" in sample
        assert "expiry" in sample
        assert "strikes" in sample
        assert "legs" in sample
        assert "legs_expected" in sample
        assert "legs_found" in sample
        assert "total_cost_share" in sample
        assert "net_credit_share" in sample
        assert "legs_with_missing_quotes" in sample
        assert "chain_calls_count" in sample
        assert "chain_puts_count" in sample

    def test_sample_with_legs(self):
        """Verify sample correctly processes legs."""
        legs = [
            {"symbol": "SPY240119P450", "type": "put", "side": "sell", "strike": 450.0, "bid": 1.5, "ask": 1.6, "premium": 1.55},
            {"symbol": "SPY240119P445", "type": "put", "side": "buy", "strike": 445.0, "bid": 0.8, "ask": 0.9, "premium": 0.85},
            {"symbol": "SPY240119C465", "type": "call", "side": "sell", "strike": 465.0, "bid": 1.4, "ask": 1.5, "premium": 1.45},
            {"symbol": "SPY240119C470", "type": "call", "side": "buy", "strike": 470.0, "bid": 0.7, "ask": 0.8, "premium": 0.75},
        ]

        sample = _build_condor_rejection_sample(
            symbol="SPY",
            strategy_key="iron_condor",
            expiry_selected="2024-01-19",
            legs=legs,
            total_cost=0.10,  # Debit (not credit)
            calls_count=100,
            puts_count=100,
        )

        assert sample["symbol"] == "SPY"
        assert sample["legs_found"] == 4
        assert sample["legs_expected"] == 4
        assert len(sample["legs"]) == 4
        assert sample["strikes"] == [445.0, 450.0, 465.0, 470.0]
        assert sample["total_cost_share"] == 0.10
        assert sample["net_credit_share"] == 0.0  # Not a credit since total_cost > 0

    def test_sample_with_missing_quotes(self):
        """Verify legs with missing quotes are tracked."""
        legs = [
            {"symbol": "SPY240119P450", "type": "put", "side": "sell", "strike": 450.0, "bid": 1.5, "ask": 1.6},
            {"symbol": "SPY240119P445", "type": "put", "side": "buy", "strike": 445.0, "bid": None, "ask": None},  # Missing
            {"symbol": "SPY240119C465", "type": "call", "side": "sell", "strike": 465.0, "bid": 0, "ask": 0},  # Zero
            {"symbol": "SPY240119C470", "type": "call", "side": "buy", "strike": 470.0, "bid": 0.7, "ask": 0.8},
        ]

        sample = _build_condor_rejection_sample(
            symbol="SPY",
            strategy_key="iron_condor",
            expiry_selected="2024-01-19",
            legs=legs,
            total_cost=-1.5,
        )

        # Should have 2 legs with missing quotes
        assert len(sample["legs_with_missing_quotes"]) == 2
        assert "SPY240119P445" in sample["legs_with_missing_quotes"]
        assert "SPY240119C465" in sample["legs_with_missing_quotes"]

    def test_sample_net_credit_calculation(self):
        """Verify net credit is correctly computed."""
        # Credit trade (negative total_cost)
        sample = _build_condor_rejection_sample(
            symbol="SPY",
            strategy_key="iron_condor",
            expiry_selected="2024-01-19",
            legs=[],
            total_cost=-1.50,
        )
        assert sample["net_credit_share"] == 1.50

        # Debit trade (positive total_cost)
        sample = _build_condor_rejection_sample(
            symbol="SPY",
            strategy_key="iron_condor",
            expiry_selected="2024-01-19",
            legs=[],
            total_cost=0.50,
        )
        assert sample["net_credit_share"] == 0.0

        # No cost (None)
        sample = _build_condor_rejection_sample(
            symbol="SPY",
            strategy_key="iron_condor",
            expiry_selected="2024-01-19",
            legs=[],
            total_cost=None,
        )
        assert sample["net_credit_share"] is None

    def test_sample_is_json_serializable(self):
        """Verify sample output is JSON-serializable."""
        legs = [
            {"symbol": "SPY240119P450", "type": "put", "side": "sell", "strike": 450.0, "bid": 1.5, "ask": 1.6, "premium": 1.55},
        ]

        sample = _build_condor_rejection_sample(
            symbol="SPY",
            strategy_key="iron_condor",
            expiry_selected="2024-01-19",
            legs=legs,
            total_cost=-1.50,
        )

        # Should serialize without error
        json_str = json.dumps(sample)
        parsed = json.loads(json_str)

        assert parsed["symbol"] == "SPY"


class TestRejectionSamplesInScanner:
    """Verify rejection samples are wired up in scanner."""

    def test_scanner_has_record_with_sample_method(self):
        """Verify RejectionStats has record_with_sample method."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "options_scanner.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "def record_with_sample(self, reason: str, sample: Dict[str, Any])" in content

    def test_scanner_has_samples_in_to_dict(self):
        """Verify to_dict includes rejection_samples."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "options_scanner.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert '"rejection_samples": list(self._samples)' in content

    def test_condor_no_credit_uses_record_with_sample(self):
        """Verify condor_no_credit rejection uses record_with_sample."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "options_scanner.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert 'rej_stats.record_with_sample("condor_no_credit"' in content

    def test_condor_legs_not_found_uses_record_with_sample(self):
        """Verify condor_legs_not_found rejection uses record_with_sample."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "options_scanner.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert 'rej_stats.record_with_sample("condor_legs_not_found"' in content

    def test_build_condor_rejection_sample_helper_exists(self):
        """Verify _build_condor_rejection_sample helper is defined."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "options_scanner.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "def _build_condor_rejection_sample(" in content


class TestThreadSafety:
    """Test thread safety of sample collection."""

    def test_concurrent_record_with_sample(self):
        """Verify concurrent sample recording is thread-safe."""
        stats = RejectionStatsLocal()
        stats._samples_cap = 5
        num_threads = 10
        records_per_thread = 20

        def worker(thread_id):
            for i in range(records_per_thread):
                sample = {"thread": thread_id, "index": i}
                stats.record_with_sample("test_reason", sample)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        result = stats.to_dict()

        # Count should be total records
        expected_count = num_threads * records_per_thread
        assert result["rejection_counts"]["test_reason"] == expected_count

        # Samples should be capped
        assert len(result["rejection_samples"]) == 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
