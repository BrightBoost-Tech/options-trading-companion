
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import sys
import os

# Adjust path to import from quantum
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from analytics.progress_engine import ProgressEngine

class TestProgressEngine(unittest.TestCase):
    def setUp(self):
        self.mock_supabase = MagicMock()
        self.engine = ProgressEngine(self.mock_supabase)
        self.user_id = "test-user-id"

    def test_generate_weekly_snapshot_synthetic(self):
        # Mock logs
        mock_logs = [
            {"id": "1", "was_accepted": True, "confidence_score": 80, "symbol": "AAPL", "created_at": datetime.now(timezone.utc).isoformat()},
            {"id": "2", "was_accepted": False, "confidence_score": 60, "symbol": "MSFT", "created_at": datetime.now(timezone.utc).isoformat()}
        ]

        # Mock executions
        mock_executions = [
            {"id": "ex1", "suggestion_id": "1", "realized_pnl": 100, "timestamp": datetime.now(timezone.utc).isoformat()}
        ]

        # Mock snapshots
        mock_snapshots = [
            {"risk_metrics": {"something": True}, "created_at": datetime.now(timezone.utc).isoformat()}
        ]

        # Configure mocks
        self.engine._fetch_logs = MagicMock(return_value=mock_logs)
        self.engine._fetch_executions = MagicMock(return_value=mock_executions)
        self.engine._fetch_snapshots = MagicMock(return_value=mock_snapshots)

        # Run
        snapshot = self.engine.generate_weekly_snapshot(self.user_id, "2025-W01")

        # Verify structure
        self.assertEqual(snapshot["week_id"], "2025-W01")
        self.assertEqual(snapshot["user_metrics"]["overall_score"], 50.0) # 1 accepted out of 2 = 50% adherence
        self.assertEqual(snapshot["user_metrics"]["pnl_attribution"]["realized_pnl"], 100)

        # Check upsert call
        self.mock_supabase.table.assert_called_with("weekly_snapshots")

if __name__ == '__main__':
    unittest.main()
