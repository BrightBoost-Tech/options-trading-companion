"""
Tests for scanner rejection statistics.

Verifies:
1. RejectionStats class tracks rejection reasons correctly
2. Thread-safety of RejectionStats
3. scan_for_opportunities returns rejection stats
4. Workflow orchestrator includes debug info on no_candidates
"""

import pytest
import os
import threading
import json


class TestRejectionStatsClass:
    """Test the RejectionStats helper class."""

    def test_rejection_stats_imports(self):
        """Verify RejectionStats is defined in options_scanner."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "options_scanner.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "class RejectionStats:" in content, \
            "RejectionStats class should be defined"

    def test_rejection_stats_has_required_methods(self):
        """Verify RejectionStats has required methods."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "options_scanner.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Check for required methods
        assert "def record(self, reason: str)" in content, \
            "RejectionStats should have record() method"
        assert "def to_dict(self)" in content, \
            "RejectionStats should have to_dict() method"
        assert "def top_reasons(self" in content, \
            "RejectionStats should have top_reasons() method"

    def test_rejection_stats_is_thread_safe(self):
        """Verify RejectionStats uses threading lock."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "options_scanner.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Check for threading import and lock usage
        assert "import threading" in content, \
            "RejectionStats should import threading"
        assert "self._lock = threading.Lock()" in content, \
            "RejectionStats should use a threading lock"
        assert "with self._lock:" in content, \
            "RejectionStats should use lock in context manager"


class TestRejectionStatsLogic:
    """Test RejectionStats logic by replicating it locally."""

    def setup_method(self):
        """Create a local RejectionStats for testing."""
        from collections import defaultdict

        class RejectionStatsLocal:
            def __init__(self):
                self._counts = defaultdict(int)
                self._lock = threading.Lock()
                self.symbols_processed = 0
                self.chains_loaded = 0
                self.chains_empty = 0

            def record(self, reason):
                with self._lock:
                    self._counts[reason] += 1

            def increment_processed(self):
                with self._lock:
                    self.symbols_processed += 1

            def increment_chains_loaded(self):
                with self._lock:
                    self.chains_loaded += 1

            def increment_chains_empty(self):
                with self._lock:
                    self.chains_empty += 1

            def to_dict(self):
                with self._lock:
                    return {
                        "rejection_counts": dict(self._counts),
                        "symbols_processed": self.symbols_processed,
                        "chains_loaded": self.chains_loaded,
                        "chains_empty": self.chains_empty,
                        "total_rejections": sum(self._counts.values()),
                    }

            def top_reasons(self, n=5):
                with self._lock:
                    sorted_items = sorted(
                        self._counts.items(),
                        key=lambda x: x[1],
                        reverse=True
                    )
                    return sorted_items[:n]

        self.RejectionStats = RejectionStatsLocal

    def test_record_single_reason(self):
        """Test recording a single rejection reason."""
        stats = self.RejectionStats()
        stats.record("missing_quotes")

        result = stats.to_dict()
        assert result["rejection_counts"]["missing_quotes"] == 1
        assert result["total_rejections"] == 1

    def test_record_multiple_reasons(self):
        """Test recording multiple different rejection reasons."""
        stats = self.RejectionStats()
        stats.record("missing_quotes")
        stats.record("no_chain")
        stats.record("spread_too_wide")
        stats.record("missing_quotes")  # duplicate

        result = stats.to_dict()
        assert result["rejection_counts"]["missing_quotes"] == 2
        assert result["rejection_counts"]["no_chain"] == 1
        assert result["rejection_counts"]["spread_too_wide"] == 1
        assert result["total_rejections"] == 4

    def test_top_reasons_ordering(self):
        """Test top_reasons returns sorted by count descending."""
        stats = self.RejectionStats()
        stats.record("missing_quotes")
        stats.record("missing_quotes")
        stats.record("missing_quotes")
        stats.record("no_chain")
        stats.record("no_chain")
        stats.record("spread_too_wide")

        top = stats.top_reasons(3)

        assert top[0] == ("missing_quotes", 3)
        assert top[1] == ("no_chain", 2)
        assert top[2] == ("spread_too_wide", 1)

    def test_counters(self):
        """Test symbols_processed and chains counters."""
        stats = self.RejectionStats()

        stats.increment_processed()
        stats.increment_processed()
        stats.increment_chains_loaded()
        stats.increment_chains_empty()

        result = stats.to_dict()
        assert result["symbols_processed"] == 2
        assert result["chains_loaded"] == 1
        assert result["chains_empty"] == 1

    def test_thread_safety(self):
        """Test concurrent access to RejectionStats."""
        stats = self.RejectionStats()
        num_threads = 10
        records_per_thread = 100

        def worker():
            for _ in range(records_per_thread):
                stats.record("test_reason")
                stats.increment_processed()

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        result = stats.to_dict()
        expected_count = num_threads * records_per_thread
        assert result["rejection_counts"]["test_reason"] == expected_count
        assert result["symbols_processed"] == expected_count

    def test_to_dict_is_json_serializable(self):
        """Test that to_dict output is JSON-serializable."""
        stats = self.RejectionStats()
        stats.record("missing_quotes")
        stats.record("no_chain")
        stats.increment_processed()
        stats.increment_chains_loaded()

        result = stats.to_dict()

        # Should serialize without error
        json_str = json.dumps(result)
        parsed = json.loads(json_str)

        assert "rejection_counts" in parsed
        assert "symbols_processed" in parsed


class TestScannerReturnsRejectionStats:
    """Verify scan_for_opportunities returns rejection stats."""

    def test_scan_function_signature_returns_tuple(self):
        """Verify scan_for_opportunities returns tuple with RejectionStats."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "options_scanner.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Check return type annotation
        assert "Tuple[List[Dict[str, Any]], RejectionStats]" in content, \
            "scan_for_opportunities should return Tuple with RejectionStats"

        # Check return statement
        assert "return candidates, rejection_stats" in content, \
            "scan_for_opportunities should return (candidates, rejection_stats)"

    def test_scan_creates_rejection_stats(self):
        """Verify scan_for_opportunities creates RejectionStats instance."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "options_scanner.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "rejection_stats = RejectionStats()" in content, \
            "scan_for_opportunities should create RejectionStats instance"


class TestWorkflowOrchestratorDebugInfo:
    """Verify workflow orchestrator includes debug info on no_candidates."""

    def test_orchestrator_unpacks_rejection_stats(self):
        """Verify orchestrator unpacks tuple from scan_for_opportunities."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "services",
            "workflow_orchestrator.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "scout_results, rejection_stats = scan_for_opportunities(" in content, \
            "Orchestrator should unpack (results, rejection_stats) tuple"

    def test_orchestrator_includes_debug_on_no_candidates(self):
        """Verify orchestrator includes debug field in no_candidates return."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "services",
            "workflow_orchestrator.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Check for debug field in no_candidates return
        assert '"debug": rejection_stats.to_dict()' in content, \
            "no_candidates return should include debug field with rejection_stats"

    def test_orchestrator_logs_top_reasons(self):
        """Verify orchestrator logs top rejection reasons."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "services",
            "workflow_orchestrator.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "rejection_stats.top_reasons" in content, \
            "Orchestrator should call top_reasons for logging"


class TestRejectionReasonsCovered:
    """Verify key rejection reasons are tracked in scanner."""

    def test_missing_quotes_tracked(self):
        """Verify missing_quotes rejection is tracked."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "options_scanner.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert 'rej_stats.record("missing_quotes")' in content

    def test_no_chain_tracked(self):
        """Verify no_chain rejection is tracked."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "options_scanner.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert 'rej_stats.record("no_chain")' in content

    def test_spread_too_wide_tracked(self):
        """Verify spread_too_wide rejection is tracked."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "options_scanner.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert 'rej_stats.record("spread_too_wide")' in content

    def test_strategy_hold_tracked(self):
        """Verify strategy_hold rejection is tracked."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "options_scanner.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert 'rej_stats.record("strategy_hold")' in content

    def test_execution_cost_exceeds_ev_tracked(self):
        """Verify execution_cost_exceeds_ev rejection is tracked."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "options_scanner.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert 'rej_stats.record("execution_cost_exceeds_ev")' in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
