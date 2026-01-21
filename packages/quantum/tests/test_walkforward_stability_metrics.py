"""
Tests for v6 walk-forward stability metrics and worst-fold risk indicators.

Tests:
1. stability_score is in [0,100]
2. max_drawdown_worst equals highest DD across folds
3. sharpe_std > 0 when folds have varying sharpes
4. pct_positive_folds calculated correctly
5. worst_fold_index_by_drawdown identifies correct fold
6. stability_tier assigned correctly
7. Empty folds return safe defaults
"""

import unittest
import sys
import os

# Add parent path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestComputeWfaStability(unittest.TestCase):
    """Tests for _compute_wfa_stability helper function."""

    def test_stability_score_bounded(self):
        """stability_score is in [0, 100]."""
        from services.walkforward_runner import _compute_wfa_stability

        fold_results = [
            {"test_metrics": {"sharpe": 1.0, "max_drawdown": 0.10, "total_pnl": 1000}},
            {"test_metrics": {"sharpe": 0.5, "max_drawdown": 0.25, "total_pnl": -200}},
            {"test_metrics": {"sharpe": 1.5, "max_drawdown": 0.05, "total_pnl": 800}},
        ]

        stability = _compute_wfa_stability(fold_results)

        self.assertGreaterEqual(stability["stability_score"], 0.0)
        self.assertLessEqual(stability["stability_score"], 100.0)

    def test_max_drawdown_worst_equals_highest(self):
        """max_drawdown_worst equals the highest DD across folds."""
        from services.walkforward_runner import _compute_wfa_stability

        fold_results = [
            {"test_metrics": {"sharpe": 1.0, "max_drawdown": 0.10}},
            {"test_metrics": {"sharpe": 0.5, "max_drawdown": 0.25}},  # worst
            {"test_metrics": {"sharpe": 1.5, "max_drawdown": 0.05}},
        ]

        stability = _compute_wfa_stability(fold_results)

        self.assertEqual(stability["max_drawdown_worst"], 0.25)

    def test_sharpe_std_positive_with_varying_sharpes(self):
        """sharpe_std > 0 when folds have varying sharpes."""
        from services.walkforward_runner import _compute_wfa_stability

        fold_results = [
            {"test_metrics": {"sharpe": 1.0, "max_drawdown": 0.10}},
            {"test_metrics": {"sharpe": 0.5, "max_drawdown": 0.15}},
            {"test_metrics": {"sharpe": 1.5, "max_drawdown": 0.05}},
        ]

        stability = _compute_wfa_stability(fold_results)

        self.assertGreater(stability["sharpe_std"], 0.0)

    def test_pct_positive_folds_calculation(self):
        """pct_positive_folds calculated correctly from total_pnl."""
        from services.walkforward_runner import _compute_wfa_stability

        fold_results = [
            {"test_metrics": {"sharpe": 1.0, "max_drawdown": 0.10, "total_pnl": 1000}},  # positive
            {"test_metrics": {"sharpe": 0.5, "max_drawdown": 0.25, "total_pnl": -200}},  # negative
            {"test_metrics": {"sharpe": 1.5, "max_drawdown": 0.05, "total_pnl": 800}},   # positive
        ]

        stability = _compute_wfa_stability(fold_results)

        # 2 out of 3 positive
        self.assertAlmostEqual(stability["pct_positive_folds"], 2/3, places=3)

    def test_worst_fold_index_by_drawdown(self):
        """worst_fold_index_by_drawdown identifies correct fold."""
        from services.walkforward_runner import _compute_wfa_stability

        fold_results = [
            {"test_metrics": {"sharpe": 1.0, "max_drawdown": 0.10}},
            {"test_metrics": {"sharpe": 0.5, "max_drawdown": 0.25}},  # worst DD at index 1
            {"test_metrics": {"sharpe": 1.5, "max_drawdown": 0.05}},
        ]

        stability = _compute_wfa_stability(fold_results)

        self.assertEqual(stability["worst_fold_index_by_drawdown"], 1)

    def test_worst_fold_index_by_sharpe(self):
        """worst_fold_index_by_sharpe identifies correct fold."""
        from services.walkforward_runner import _compute_wfa_stability

        fold_results = [
            {"test_metrics": {"sharpe": 1.0, "max_drawdown": 0.10}},
            {"test_metrics": {"sharpe": 0.5, "max_drawdown": 0.25}},  # worst sharpe at index 1
            {"test_metrics": {"sharpe": 1.5, "max_drawdown": 0.05}},
        ]

        stability = _compute_wfa_stability(fold_results)

        self.assertEqual(stability["worst_fold_index_by_sharpe"], 1)

    def test_stability_tier_a(self):
        """stability_tier is 'A' for score >= 70."""
        from services.walkforward_runner import _compute_wfa_stability

        # High sharpe, low std, low DD -> high score
        fold_results = [
            {"test_metrics": {"sharpe": 2.0, "max_drawdown": 0.02, "total_pnl": 1000}},
            {"test_metrics": {"sharpe": 2.1, "max_drawdown": 0.03, "total_pnl": 1100}},
            {"test_metrics": {"sharpe": 1.9, "max_drawdown": 0.02, "total_pnl": 900}},
        ]

        stability = _compute_wfa_stability(fold_results)

        self.assertEqual(stability["stability_tier"], "A")
        self.assertGreaterEqual(stability["stability_score"], 70)

    def test_stability_tier_d(self):
        """stability_tier is 'D' for score < 25."""
        from services.walkforward_runner import _compute_wfa_stability

        # Low/negative sharpe, high DD -> low score
        fold_results = [
            {"test_metrics": {"sharpe": -0.5, "max_drawdown": 0.50, "total_pnl": -500}},
            {"test_metrics": {"sharpe": 0.1, "max_drawdown": 0.45, "total_pnl": -200}},
            {"test_metrics": {"sharpe": -0.2, "max_drawdown": 0.60, "total_pnl": -300}},
        ]

        stability = _compute_wfa_stability(fold_results)

        self.assertEqual(stability["stability_tier"], "D")
        self.assertLess(stability["stability_score"], 25)

    def test_empty_folds_returns_safe_defaults(self):
        """Empty folds return safe defaults."""
        from services.walkforward_runner import _compute_wfa_stability

        stability = _compute_wfa_stability([])

        self.assertEqual(stability["fold_count"], 0)
        self.assertEqual(stability["stability_score"], 0.0)
        self.assertEqual(stability["stability_tier"], "D")
        self.assertEqual(stability["sharpe_std"], 0.0)
        self.assertEqual(stability["max_drawdown_worst"], 0.0)
        self.assertEqual(stability["pct_positive_folds"], 0.0)
        self.assertIsNone(stability["worst_fold_index_by_drawdown"])
        self.assertIsNone(stability["worst_fold_index_by_sharpe"])

    def test_missing_test_metrics_handled(self):
        """Missing test_metrics keys handled with defaults."""
        from services.walkforward_runner import _compute_wfa_stability

        fold_results = [
            {"test_metrics": {}},  # Missing all metrics
            {"test_metrics": {"sharpe": 1.0}},  # Partial
            {"trades_count": 5},  # No test_metrics at all
        ]

        # Should not raise
        stability = _compute_wfa_stability(fold_results)

        self.assertEqual(stability["fold_count"], 3)
        self.assertIsInstance(stability["stability_score"], float)

    def test_fold_count_matches(self):
        """fold_count equals number of input folds."""
        from services.walkforward_runner import _compute_wfa_stability

        fold_results = [
            {"test_metrics": {"sharpe": 1.0, "max_drawdown": 0.10}},
            {"test_metrics": {"sharpe": 0.5, "max_drawdown": 0.15}},
            {"test_metrics": {"sharpe": 1.5, "max_drawdown": 0.05}},
            {"test_metrics": {"sharpe": 0.8, "max_drawdown": 0.08}},
        ]

        stability = _compute_wfa_stability(fold_results)

        self.assertEqual(stability["fold_count"], 4)

    def test_sharpe_mean_and_median(self):
        """sharpe_mean and sharpe_median calculated correctly."""
        from services.walkforward_runner import _compute_wfa_stability

        fold_results = [
            {"test_metrics": {"sharpe": 1.0, "max_drawdown": 0.10}},
            {"test_metrics": {"sharpe": 2.0, "max_drawdown": 0.15}},
            {"test_metrics": {"sharpe": 3.0, "max_drawdown": 0.05}},
        ]

        stability = _compute_wfa_stability(fold_results)

        # Mean of [1, 2, 3] = 2.0
        self.assertAlmostEqual(stability["sharpe_mean"], 2.0, places=3)
        # Median of [1, 2, 3] = 2.0
        self.assertAlmostEqual(stability["sharpe_median"], 2.0, places=3)


class TestWalkForwardRunnerStabilityIntegration(unittest.TestCase):
    """Tests that stability metrics are integrated into WalkForwardRunner output."""

    def _create_mock_engine(self, metrics=None, trade_count=10):
        """Create mock engine."""
        from unittest.mock import MagicMock

        if metrics is None:
            metrics = {"sharpe": 1.0, "max_drawdown": 0.10, "total_pnl": 500}

        mock_result = MagicMock()
        mock_result.trades = [{"pnl": 100}] * trade_count
        mock_result.events = []
        mock_result.metrics = metrics

        engine = MagicMock()
        engine.run_single.return_value = mock_result
        return engine

    def _create_mock_request(self):
        """Create mock BacktestRequestV3."""
        from unittest.mock import MagicMock

        mock_wf = MagicMock()
        mock_wf.train_days = 30
        mock_wf.test_days = 15
        mock_wf.step_days = 15
        mock_wf.warmup_days = 0
        mock_wf.embargo_days = 0
        mock_wf.tune_grid = None
        mock_wf.objective_metric = "sharpe"
        mock_wf.min_trades_per_fold = 5
        mock_wf.max_tune_combinations = 50

        mock_cost = MagicMock()

        mock_request = MagicMock()
        mock_request.ticker = "SPY"
        mock_request.start_date = "2024-01-01"
        mock_request.end_date = "2024-06-30"
        mock_request.seed = 42
        mock_request.initial_equity = 100000.0
        mock_request.walk_forward = mock_wf
        mock_request.cost_model = mock_cost

        return mock_request

    def _create_mock_config(self):
        """Create mock StrategyConfig."""
        from unittest.mock import MagicMock

        mock_config = MagicMock()
        mock_config.conviction_floor = 0.7
        mock_config.model_copy.return_value = MagicMock(conviction_floor=0.7)
        return mock_config

    def test_aggregate_metrics_includes_stability(self):
        """aggregate_metrics includes stability metrics after run_walk_forward."""
        from services.walkforward_runner import WalkForwardRunner

        engine = self._create_mock_engine()
        request = self._create_mock_request()
        config = self._create_mock_config()

        runner = WalkForwardRunner(engine)
        result = runner.run_walk_forward(request, config)

        # Check stability metrics are present
        self.assertIn("stability_score", result.aggregate_metrics)
        self.assertIn("stability_tier", result.aggregate_metrics)
        self.assertIn("sharpe_std", result.aggregate_metrics)
        self.assertIn("max_drawdown_worst", result.aggregate_metrics)
        self.assertIn("pct_positive_folds", result.aggregate_metrics)
        self.assertIn("worst_fold_index_by_drawdown", result.aggregate_metrics)
        self.assertIn("worst_fold_index_by_sharpe", result.aggregate_metrics)

    def test_existing_metrics_preserved(self):
        """Existing aggregate metrics (sharpe, max_drawdown, total_folds) preserved."""
        from services.walkforward_runner import WalkForwardRunner

        engine = self._create_mock_engine()
        request = self._create_mock_request()
        config = self._create_mock_config()

        runner = WalkForwardRunner(engine)
        result = runner.run_walk_forward(request, config)

        # Existing metrics still present
        self.assertIn("sharpe", result.aggregate_metrics)
        self.assertIn("max_drawdown", result.aggregate_metrics)
        self.assertIn("total_folds", result.aggregate_metrics)


if __name__ == "__main__":
    unittest.main()
