import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add package root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class TestBacktestDeterminismV2(unittest.TestCase):
    @patch('packages.quantum.services.backtest_workflow.HistoricalCycleService')
    @patch('packages.quantum.services.backtest_workflow._get_supabase_client')
    def test_run_backtest_workflow_passes_seed(self, mock_get_supabase, MockHistoricalCycleService):
        from packages.quantum.services.backtest_workflow import _run_backtest_workflow

        # Setup mocks
        mock_service = MockHistoricalCycleService.return_value

        # Mock run_cycle to return a result that advances the cursor so loop runs at least once
        mock_service.run_cycle.return_value = {
            "status": "normal_exit",
            "nextCursor": "2023-01-05",
            "pnl": 100.0
        }

        request = MagicMock()
        request.start_date = "2023-01-01"
        request.end_date = "2023-01-10"
        request.ticker = "SPY"

        config = MagicMock()

        # Call the workflow with seed
        # This should NOT raise TypeError now
        _run_backtest_workflow("user1", request, "strat1", config, seed=12345)

        # Check if run_cycle got the seed
        calls = mock_service.run_cycle.call_args_list
        self.assertTrue(len(calls) > 0)

        # Check arguments of the first call
        args, kwargs = calls[0]

        # We expect seed to be passed in kwargs
        self.assertIn('seed', kwargs)
        self.assertIsNotNone(kwargs['seed'])

        # Verify deterministic derivation: same workflow seed should produce same cycle seeds
        seed1 = kwargs['seed']

        # Reset and run again with same seed
        mock_service.reset_mock()
        _run_backtest_workflow("user1", request, "strat1", config, seed=12345)

        args2, kwargs2 = mock_service.run_cycle.call_args_list[0]
        seed2 = kwargs2['seed']

        self.assertEqual(seed1, seed2, "Seeds should be identical for same workflow seed")

        # Verify different seed produces different cycle seed
        mock_service.reset_mock()
        _run_backtest_workflow("user1", request, "strat1", config, seed=99999)

        args3, kwargs3 = mock_service.run_cycle.call_args_list[0]
        seed3 = kwargs3['seed']

        self.assertNotEqual(seed1, seed3, "Different workflow seeds should produce different cycle seeds")

if __name__ == '__main__':
    unittest.main()
