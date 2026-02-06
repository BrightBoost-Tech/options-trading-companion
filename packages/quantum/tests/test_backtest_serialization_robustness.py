import unittest
from unittest.mock import MagicMock, patch
import sys
import os
import json
try:
    import numpy as np
except ImportError:
    np = None

# Add package root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class TestBacktestSerializationRobustness(unittest.TestCase):
    @patch('packages.quantum.services.backtest_workflow.HistoricalCycleService')
    @patch('packages.quantum.services.backtest_workflow._get_supabase_client')
    def test_run_backtest_workflow_serialization(self, mock_get_supabase, MockHistoricalCycleService):
        if np is None:
            self.skipTest("Numpy not installed")

        from packages.quantum.services.backtest_workflow import _run_backtest_workflow

        # Setup mocks
        mock_service = MockHistoricalCycleService.return_value

        # Mock Supabase client to capture the update call
        mock_supabase = mock_get_supabase.return_value
        mock_table = mock_supabase.table.return_value
        # mock_table.update is the method called with the payload

        # Return a result containing complex types: sets, numpy scalars, numpy arrays
        complex_result = {
            "status": "normal_exit",
            "nextCursor": "2023-01-05",
            "pnl": np.float64(100.5),
            "entry_index": np.int64(10),
            "tags": {"tag1", "tag2"},  # Set
            "indicators": np.array([1.0, 2.0]), # Numpy array
            "meta": {
                "nested_set": {1, 2, 3}
            }
        }

        mock_service.run_cycle.return_value = complex_result

        request = MagicMock()
        request.start_date = "2023-01-01"
        request.end_date = "2023-01-02" # Short run
        request.ticker = "SPY"

        config = MagicMock()
        batch_id = "test_batch_123"

        # Attempt to run workflow
        results = _run_backtest_workflow("user1", request, "strat1", config, batch_id=batch_id, seed=12345)

        # Verify Supabase was called with valid JSON
        # We access the arguments passed to update()
        self.assertTrue(mock_table.update.called, "Supabase update was not called (serialization likely failed)")

        if mock_table.update.called:
            update_call_args = mock_table.update.call_args[0][0]
            metrics = update_call_args.get("metrics", {})
            serialized_results = metrics.get("results", [])

            self.assertEqual(len(serialized_results), 1)
            first_res = serialized_results[0]

            # Verify conversions
            self.assertIsInstance(first_res["pnl"], float)
            self.assertIsInstance(first_res["entry_index"], int)
            self.assertIsInstance(first_res["tags"], list)
            self.assertEqual(sorted(first_res["tags"]), ["tag1", "tag2"])
            self.assertIsInstance(first_res["indicators"], list)
            self.assertEqual(first_res["indicators"], [1.0, 2.0])
            self.assertIsInstance(first_res["meta"]["nested_set"], list)

if __name__ == '__main__':
    unittest.main()
