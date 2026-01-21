"""
Tests for Walk-Forward Runner v4 upgrades.

Tests:
1. generate_folds() includes train_start_engine with warmup
2. Fold payload includes full train_metrics
3. Edge cases: empty folds, missing metrics
"""

import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

import sys
import os

# Add parent path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestGenerateFoldsV4(unittest.TestCase):
    """Tests for generate_folds() v4 upgrades."""

    def test_generate_folds_includes_train_start_engine(self):
        """Folds include train_start_engine for warmup expansion."""
        from services.walkforward_runner import generate_folds

        folds = generate_folds(
            start_date="2024-01-01",
            end_date="2024-06-30",
            train_days=60,
            test_days=30,
            step_days=30,
            warmup_days=10,
            embargo_days=0
        )

        self.assertGreater(len(folds), 0)

        # First fold should have train_start_engine
        fold = folds[0]
        self.assertIn("train_start_engine", fold)
        self.assertIn("train_start", fold)
        self.assertIn("train_end", fold)
        self.assertIn("test_start", fold)
        self.assertIn("test_end", fold)

    def test_train_start_engine_expanded_by_warmup(self):
        """train_start_engine is train_start - warmup_days (when not clamped)."""
        from services.walkforward_runner import generate_folds

        # Use a date range where later folds can expand without clamping
        folds = generate_folds(
            start_date="2024-01-01",
            end_date="2024-12-31",
            train_days=60,
            test_days=30,
            step_days=30,
            warmup_days=10,
            embargo_days=0
        )

        self.assertGreater(len(folds), 1)
        # Second fold starts at day 30, so train_start_engine can expand
        fold = folds[1]  # Use second fold to avoid clamping

        # Parse dates
        train_start = datetime.strptime(fold["train_start"], "%Y-%m-%d")
        train_start_engine = datetime.strptime(fold["train_start_engine"], "%Y-%m-%d")

        # Engine start should be 10 days before train_start
        diff_days = (train_start - train_start_engine).days
        self.assertEqual(diff_days, 10)

    def test_train_start_engine_clamped_to_request_start(self):
        """train_start_engine does not go before request start_date."""
        from services.walkforward_runner import generate_folds

        folds = generate_folds(
            start_date="2024-01-01",
            end_date="2024-06-30",
            train_days=60,
            test_days=30,
            step_days=30,
            warmup_days=30,  # Large warmup
            embargo_days=0
        )

        self.assertGreater(len(folds), 0)
        fold = folds[0]

        # First fold's train_start is 2024-01-01
        # warmup=30 would try to go to 2023-12-02, but should clamp to 2024-01-01
        self.assertEqual(fold["train_start_engine"], "2024-01-01")

    def test_generate_folds_empty_on_invalid_dates(self):
        """Returns empty list on invalid date range."""
        from services.walkforward_runner import generate_folds

        folds = generate_folds(
            start_date="2024-06-01",
            end_date="2024-01-01",  # End before start
            train_days=60,
            test_days=30,
            step_days=30,
            warmup_days=0,
            embargo_days=0
        )

        self.assertEqual(folds, [])


class TestWalkForwardRunnerV4(unittest.TestCase):
    """Tests for WalkForwardRunner v4 fold payload upgrades."""

    def _create_mock_engine(self, metrics=None, trade_count=10):
        """Create mock engine that returns specified metrics."""
        if metrics is None:
            metrics = {
                "sharpe": 1.5,
                "max_drawdown": 0.15,
                "profit_factor": 1.8,
                "win_rate": 0.55,
                "total_pnl": 5000.0
            }

        mock_result = MagicMock()
        mock_result.metrics = metrics
        mock_result.trades = [{"pnl": 100}] * trade_count  # v4: sufficient trades
        mock_result.events = []

        engine = MagicMock()
        engine.run_single.return_value = mock_result
        return engine

    def _create_mock_request(self):
        """Create mock BacktestRequestV3."""
        mock_wf_config = MagicMock()
        mock_wf_config.train_days = 30
        mock_wf_config.test_days = 15
        mock_wf_config.step_days = 15
        mock_wf_config.warmup_days = 5
        mock_wf_config.embargo_days = 0
        # v4: New fields for fold-level tuning
        mock_wf_config.tune_grid = None  # Fall back to legacy candidates
        mock_wf_config.objective_metric = "sharpe"
        mock_wf_config.min_trades_per_fold = 5
        mock_wf_config.max_tune_combinations = 50

        mock_request = MagicMock()
        mock_request.ticker = "SPY"
        mock_request.start_date = "2024-01-01"
        mock_request.end_date = "2024-04-30"
        mock_request.walk_forward = mock_wf_config
        mock_request.cost_model = None
        mock_request.seed = 42
        mock_request.initial_equity = 100000.0
        return mock_request

    def _create_mock_config(self):
        """Create mock StrategyConfig."""
        mock_config = MagicMock()
        mock_config.conviction_floor = 0.7
        mock_config.model_copy.return_value = MagicMock(conviction_floor=0.7)
        return mock_config

    def test_fold_payload_includes_train_metrics(self):
        """Fold results include full train_metrics dict."""
        from services.walkforward_runner import WalkForwardRunner

        train_metrics = {
            "sharpe": 2.0,
            "max_drawdown": 0.10,
            "profit_factor": 2.5,
            "win_rate": 0.60,
            "total_pnl": 8000.0
        }
        test_metrics = {
            "sharpe": 1.5,
            "max_drawdown": 0.15,
            "profit_factor": 1.8,
            "win_rate": 0.55,
            "total_pnl": 5000.0
        }

        engine = self._create_mock_engine(train_metrics)
        # Override for test phase
        def run_single_side_effect(*args, **kwargs):
            result = MagicMock()
            # Check if this is train or test phase by date
            start_date = args[1] if len(args) > 1 else kwargs.get('start_date', '')
            if "train" in str(start_date).lower() or args[1] < "2024-02-15":
                result.metrics = train_metrics
            else:
                result.metrics = test_metrics
            result.trades = []
            result.events = []
            return result

        engine.run_single.return_value.metrics = train_metrics
        engine.run_single.return_value.trades = [{"pnl": 100}] * 10  # v4: sufficient trades
        engine.run_single.return_value.events = []

        runner = WalkForwardRunner(engine)
        request = self._create_mock_request()
        config = self._create_mock_config()

        result = runner.run_walk_forward(request, config)

        self.assertGreater(len(result.folds), 0)

        fold = result.folds[0]
        # Check v4 fields
        self.assertIn("train_metrics", fold)
        self.assertIn("train_sharpe", fold)  # backward compat
        self.assertIn("test_metrics", fold)
        self.assertIn("optimized_params", fold)
        self.assertIn("trades_count", fold)

        # train_metrics should be a dict with multiple keys
        self.assertIsInstance(fold["train_metrics"], dict)

    def test_aggregate_metrics_includes_total_folds(self):
        """Aggregate metrics include total_folds count."""
        from services.walkforward_runner import WalkForwardRunner

        engine = self._create_mock_engine()
        runner = WalkForwardRunner(engine)
        request = self._create_mock_request()
        config = self._create_mock_config()

        result = runner.run_walk_forward(request, config)

        self.assertIn("total_folds", result.aggregate_metrics)
        self.assertEqual(result.aggregate_metrics["total_folds"], len(result.folds))

    def test_empty_folds_safe_defaults(self):
        """Empty folds produce safe default metrics."""
        from services.walkforward_runner import WalkForwardRunner

        engine = self._create_mock_engine()
        runner = WalkForwardRunner(engine)

        # Request with date range that produces no folds
        request = self._create_mock_request()
        request.start_date = "2024-01-01"
        request.end_date = "2024-01-15"  # Too short for any folds

        config = self._create_mock_config()

        result = runner.run_walk_forward(request, config)

        self.assertEqual(result.folds, [])
        self.assertEqual(result.aggregate_metrics["total_folds"], 0)
        self.assertEqual(result.aggregate_metrics["sharpe"], 0.0)
        self.assertEqual(result.aggregate_metrics["max_drawdown"], 0.0)


if __name__ == "__main__":
    unittest.main()
