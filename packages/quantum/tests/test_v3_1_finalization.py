import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta, timezone
from packages.quantum.services.execution_service import ExecutionService

# Mock data for executions
MOCK_EXECUTIONS = [
    {"symbol": "AAPL", "fill_price": 150.0, "fees": 1.0, "suggestion_id": "s1", "timestamp": "2024-01-01T10:00:00Z"},
    {"symbol": "AAPL", "fill_price": 151.0, "fees": 1.0, "suggestion_id": "s2", "timestamp": "2024-01-02T10:00:00Z"},
    {"symbol": "AAPL", "fill_price": 152.0, "fees": 1.0, "suggestion_id": "s3", "timestamp": "2024-01-03T10:00:00Z"},
    {"symbol": "MSFT", "fill_price": 300.0, "fees": 2.0, "suggestion_id": "s4", "timestamp": "2024-01-01T10:00:00Z"}, # Only 1 sample
]

MOCK_LOGS = [
    {"id": "s1", "target_price": 149.0},
    {"id": "s2", "target_price": 150.0},
    {"id": "s3", "target_price": 151.0},
    {"id": "s4", "target_price": 299.0},
]

class TestExecutionService:
    @pytest.fixture
    def mock_supabase(self):
        client = MagicMock()
        return client

    def test_drag_stats_min_samples_and_source(self, mock_supabase):
        # Setup mocks
        mock_query_exec = MagicMock()
        mock_query_exec.execute.return_value.data = MOCK_EXECUTIONS

        # Chain for executions query: table -> select -> eq -> in_ -> neq -> neq -> gte -> order -> execute
        # Note: We expect .limit() to be REMOVED.

        # We need to construct a flexible mock because the chain is long
        mock_supabase.table.return_value.select.return_value \
            .eq.return_value.in_.return_value \
            .neq.return_value.neq.return_value \
            .gte.return_value.order.return_value = mock_query_exec

        # Also need to handle the .limit() call if it exists (we want to detect if it's called)
        # If we mock .order() to return an object that HAS .limit(), we can check if it was called.
        # But we want to ensure .limit() is NOT called or at least not restricting to 100.

        # Logs query
        mock_logs_exec = MagicMock()
        mock_logs_exec.execute.return_value.data = MOCK_LOGS
        mock_supabase.table.return_value.select.return_value \
            .in_.return_value = mock_logs_exec

        service = ExecutionService(mock_supabase)

        # Call
        stats = service.get_batch_execution_drag_stats("user1", ["AAPL", "MSFT"], min_samples=3)

        # Assertions
        assert "AAPL" in stats
        assert "MSFT" not in stats # MSFT has 1 sample < 3

        aapl_stats = stats["AAPL"]
        assert aapl_stats["n"] == 3
        assert aapl_stats.get("source") == "history" # This should fail initially

        # Verify limit call
        # The chain ends at .order(...) in the new code, or .order(...).limit(...) in old code.
        # We check the mock_query_exec (which is returned by order).
        # If .limit() was called on it, it would be a child mock.

        # However, checking if .limit was called is tricky with this mock setup unless we are careful.
        # Let's verify the behavior first.

    def test_rebalance_path_no_iv_regime_service(self):
        # Read api.py content and check for strings
        with open("packages/quantum/api.py", "r") as f:
            content = f.read()

        assert "IVRegimeService" not in content.replace("# IVRegimeService", "") # Ignore the specific comment if needed, but better if gone.
        # Actually, we want to ensure it's not imported or used.
        # We can check for "from ... import IVRegimeService" uncommented.

        lines = content.splitlines()
        for line in lines:
            stripped = line.strip()
            if "IVRegimeService" in stripped and not stripped.startswith("#"):
                pytest.fail(f"Found IVRegimeService usage: {line}")
