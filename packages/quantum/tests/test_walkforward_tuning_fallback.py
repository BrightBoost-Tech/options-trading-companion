"""
Tests for v5 tuning fallback when no candidate passes min_trades_per_fold.

Tests:
1. Fallback triggers when all candidates rejected (returns tuning_fallback=True)
2. train_sharpe is never the sentinel -999.0
3. optimized_params contains {"fallback": True} on fallback
4. Fallback run populates train_metrics
"""

import unittest
import sys
import os
from unittest.mock import MagicMock, patch
import copy

# Add parent path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestTuningFallback(unittest.TestCase):
    """Tests for v5 tuning fallback behavior."""

    def _create_mock_engine_all_rejected(self, fallback_metrics=None):
        """
        Create mock engine where tuning candidates return empty trades
        but fallback returns metrics.
        """
        if fallback_metrics is None:
            fallback_metrics = {"sharpe": 0.5, "max_drawdown": 0.1}

        call_count = [0]

        def mock_run_single(*args, **kwargs):
            result = MagicMock()
            call_count[0] += 1

            # First N calls are tuning candidates (return 0 trades to trigger rejection)
            # After tuning loop exhausts, fallback is called
            if call_count[0] <= 5:  # 5 conviction_floor candidates
                result.trades = []  # No trades = rejected by min_trades_per_fold
                result.metrics = {}
            elif call_count[0] == 6:  # Fallback run
                result.trades = [{"pnl": 100}] * 3  # Some trades
                result.metrics = fallback_metrics
            else:  # Test run
                result.trades = [{"pnl": 50}] * 2
                result.metrics = {"sharpe": 0.3, "max_drawdown": 0.05}
                result.events = []

            result.events = []
            return result

        engine = MagicMock()
        engine.run_single.side_effect = mock_run_single
        return engine

    def _create_mock_request(self, min_trades=5):
        """Create mock BacktestRequestV3 with WalkForwardConfig."""
        mock_wf = MagicMock()
        mock_wf.train_days = 30
        mock_wf.test_days = 15
        mock_wf.step_days = 30
        mock_wf.warmup_days = 0
        mock_wf.embargo_days = 0
        mock_wf.tune_grid = None  # Use legacy candidates
        mock_wf.objective_metric = "sharpe"
        mock_wf.min_trades_per_fold = min_trades
        mock_wf.max_tune_combinations = 50

        mock_cost = MagicMock()

        mock_request = MagicMock()
        mock_request.ticker = "SPY"
        mock_request.start_date = "2024-01-01"
        mock_request.end_date = "2024-03-15"  # Short range for 1 fold
        mock_request.seed = 42
        mock_request.initial_equity = 100000.0
        mock_request.walk_forward = mock_wf
        mock_request.cost_model = mock_cost

        return mock_request

    def _create_mock_config(self):
        """Create mock StrategyConfig."""
        mock_config = MagicMock()
        mock_config.conviction_floor = 0.7
        mock_config.model_copy.return_value = MagicMock(conviction_floor=0.7)
        return mock_config

    def test_fallback_triggers_when_all_rejected(self):
        """tuning_fallback=True when all candidates rejected."""
        from services.walkforward_runner import WalkForwardRunner

        engine = self._create_mock_engine_all_rejected()
        request = self._create_mock_request(min_trades=10)  # High min to reject all
        config = self._create_mock_config()

        runner = WalkForwardRunner(engine)
        result = runner.run_walk_forward(request, config)

        self.assertGreater(len(result.folds), 0)

        fold = result.folds[0]
        self.assertTrue(
            fold.get("tuning_fallback", False),
            "Expected tuning_fallback=True when all candidates rejected"
        )

    def test_fallback_sets_optimized_params_fallback_true(self):
        """optimized_params contains {'fallback': True} on fallback."""
        from services.walkforward_runner import WalkForwardRunner

        engine = self._create_mock_engine_all_rejected()
        request = self._create_mock_request(min_trades=10)
        config = self._create_mock_config()

        runner = WalkForwardRunner(engine)
        result = runner.run_walk_forward(request, config)

        fold = result.folds[0]
        self.assertIn("fallback", fold["optimized_params"])
        self.assertTrue(fold["optimized_params"]["fallback"])

    def test_train_sharpe_never_sentinel(self):
        """train_sharpe is never the sentinel -999.0."""
        from services.walkforward_runner import WalkForwardRunner

        engine = self._create_mock_engine_all_rejected(fallback_metrics={})
        request = self._create_mock_request(min_trades=10)
        config = self._create_mock_config()

        runner = WalkForwardRunner(engine)
        result = runner.run_walk_forward(request, config)

        fold = result.folds[0]
        self.assertNotEqual(
            fold["train_sharpe"],
            -999.0,
            "train_sharpe should never be the sentinel -999.0"
        )
        self.assertGreaterEqual(
            fold["train_sharpe"],
            0.0,
            "train_sharpe should be >= 0.0 on fallback"
        )

    def test_fallback_populates_train_metrics(self):
        """Fallback run populates train_metrics from fallback result."""
        from services.walkforward_runner import WalkForwardRunner

        fallback_metrics = {"sharpe": 1.23, "max_drawdown": 0.08, "profit_factor": 1.5}
        engine = self._create_mock_engine_all_rejected(fallback_metrics=fallback_metrics)
        request = self._create_mock_request(min_trades=10)
        config = self._create_mock_config()

        runner = WalkForwardRunner(engine)
        result = runner.run_walk_forward(request, config)

        fold = result.folds[0]

        # train_metrics should contain the fallback metrics
        self.assertIsInstance(fold["train_metrics"], dict)
        self.assertEqual(fold["train_sharpe"], 1.23)

    def test_no_fallback_when_candidate_passes(self):
        """tuning_fallback=False when a candidate passes min_trades."""
        from services.walkforward_runner import WalkForwardRunner

        def mock_run_single(*args, **kwargs):
            result = MagicMock()
            result.trades = [{"pnl": 100}] * 10  # Enough trades
            result.events = []
            result.metrics = {"sharpe": 1.0, "max_drawdown": 0.05}
            return result

        engine = MagicMock()
        engine.run_single.side_effect = mock_run_single

        request = self._create_mock_request(min_trades=5)
        config = self._create_mock_config()

        runner = WalkForwardRunner(engine)
        result = runner.run_walk_forward(request, config)

        fold = result.folds[0]
        self.assertFalse(
            fold.get("tuning_fallback", False),
            "Expected tuning_fallback=False when a candidate passes"
        )
        self.assertNotIn("fallback", fold["optimized_params"])


if __name__ == "__main__":
    unittest.main()
