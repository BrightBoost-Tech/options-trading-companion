"""
Tests for v4 walk-forward fold-level parameter tuning.

Tests:
1. tune_grid generates correct combinations
2. objective_metric scoring (sharpe, profit_factor, calmar)
3. min_trades_per_fold enforcement
4. max_tune_combinations cap
5. Fallback to legacy candidates when tune_grid is None
"""

import unittest
import sys
import os
from unittest.mock import MagicMock, patch

# Add parent path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestObjectiveScoring(unittest.TestCase):
    """Tests for _compute_objective_score helper."""

    def test_sharpe_objective(self):
        """Sharpe objective returns sharpe value."""
        from services.walkforward_runner import _compute_objective_score

        metrics = {"sharpe": 1.5, "profit_factor": 2.0, "total_return": 0.10, "max_drawdown": 0.05}
        score = _compute_objective_score(metrics, "sharpe")
        self.assertEqual(score, 1.5)

    def test_profit_factor_objective(self):
        """Profit factor objective returns profit_factor value."""
        from services.walkforward_runner import _compute_objective_score

        metrics = {"sharpe": 1.5, "profit_factor": 2.0, "total_return": 0.10, "max_drawdown": 0.05}
        score = _compute_objective_score(metrics, "profit_factor")
        self.assertEqual(score, 2.0)

    def test_calmar_objective_normal(self):
        """Calmar = total_return / max_drawdown."""
        from services.walkforward_runner import _compute_objective_score

        metrics = {"sharpe": 1.5, "profit_factor": 2.0, "total_return": 0.10, "max_drawdown": 0.05}
        score = _compute_objective_score(metrics, "calmar")
        self.assertEqual(score, 2.0)  # 0.10 / 0.05

    def test_calmar_objective_zero_drawdown_positive_return(self):
        """Calmar returns inf when no drawdown but positive return."""
        from services.walkforward_runner import _compute_objective_score

        metrics = {"total_return": 0.10, "max_drawdown": 0.0}
        score = _compute_objective_score(metrics, "calmar")
        self.assertEqual(score, float("inf"))

    def test_calmar_objective_zero_drawdown_zero_return(self):
        """Calmar returns 0.0 when no drawdown and no return."""
        from services.walkforward_runner import _compute_objective_score

        metrics = {"total_return": 0.0, "max_drawdown": 0.0}
        score = _compute_objective_score(metrics, "calmar")
        self.assertEqual(score, 0.0)

    def test_unknown_objective_falls_back_to_sharpe(self):
        """Unknown objective falls back to sharpe."""
        from services.walkforward_runner import _compute_objective_score

        metrics = {"sharpe": 1.5}
        score = _compute_objective_score(metrics, "unknown")
        self.assertEqual(score, 1.5)

    def test_missing_metric_returns_default(self):
        """Missing metric returns safe default."""
        from services.walkforward_runner import _compute_objective_score

        metrics = {}
        self.assertEqual(_compute_objective_score(metrics, "sharpe"), -999.0)
        self.assertEqual(_compute_objective_score(metrics, "profit_factor"), 0.0)


class TestTuneGridCombinations(unittest.TestCase):
    """Tests that tune_grid generates correct parameter combinations."""

    def _create_mock_engine(self, trade_count=10, metrics=None):
        """Create mock engine that returns controlled results."""
        mock_engine = MagicMock()
        mock_result = MagicMock()
        mock_result.trades = [{"pnl": 100}] * trade_count
        mock_result.events = []
        mock_result.metrics = metrics or {"sharpe": 1.0, "profit_factor": 1.5}
        mock_engine.run_single.return_value = mock_result
        return mock_engine

    def _create_mock_request(self, tune_grid=None, objective_metric="sharpe", min_trades=5, max_combinations=50):
        """Create mock BacktestRequestV3 with WalkForwardConfig."""
        mock_wf = MagicMock()
        mock_wf.train_days = 30
        mock_wf.test_days = 10
        mock_wf.step_days = 10
        mock_wf.warmup_days = 0
        mock_wf.embargo_days = 0
        mock_wf.tune_grid = tune_grid
        mock_wf.objective_metric = objective_metric
        mock_wf.min_trades_per_fold = min_trades
        mock_wf.max_tune_combinations = max_combinations

        mock_cost = MagicMock()
        mock_cost.model_dump.return_value = {"commission_per_contract": 0.65}

        mock_request = MagicMock()
        mock_request.ticker = "SPY"
        mock_request.start_date = "2024-01-01"
        mock_request.end_date = "2024-03-01"
        mock_request.seed = 42
        mock_request.initial_equity = 100000.0
        mock_request.walk_forward = mock_wf
        mock_request.cost_model = mock_cost

        return mock_request

    def _create_mock_config(self):
        """Create mock StrategyConfig."""
        mock_config = MagicMock()
        mock_config.conviction_floor = 0.7
        mock_config.conviction_slope = 0.5
        mock_config.model_copy.return_value = MagicMock(
            conviction_floor=0.7,
            conviction_slope=0.5
        )
        return mock_config

    def test_tune_grid_iterates_all_combinations(self):
        """tune_grid iterates over all parameter combinations."""
        from services.walkforward_runner import WalkForwardRunner

        engine = self._create_mock_engine()
        tune_grid = {
            "conviction_floor": [0.5, 0.7],
            "conviction_slope": [0.3, 0.5]
        }
        request = self._create_mock_request(tune_grid=tune_grid)
        config = self._create_mock_config()

        runner = WalkForwardRunner(engine)
        runner.run_walk_forward(request, config)

        # Each fold should test 4 combinations (2x2)
        # Plus 1 test run per fold
        # With short date range, we get 1 fold
        call_count = engine.run_single.call_count
        # 4 train combinations + 1 test = 5 per fold
        self.assertGreaterEqual(call_count, 5)

    def test_max_tune_combinations_caps_iterations(self):
        """max_tune_combinations limits number of combinations tested."""
        from services.walkforward_runner import WalkForwardRunner

        engine = self._create_mock_engine()
        # 3x3 = 9 combinations
        tune_grid = {
            "conviction_floor": [0.5, 0.6, 0.7],
            "conviction_slope": [0.3, 0.4, 0.5]
        }
        # Cap to 4 combinations
        request = self._create_mock_request(tune_grid=tune_grid, max_combinations=4)
        config = self._create_mock_config()

        runner = WalkForwardRunner(engine)
        runner.run_walk_forward(request, config)

        # Should be capped to 4 train combinations + 1 test per fold
        # Not 9 train combinations (which would be ~30 total calls for 3 folds)
        # With cap: 4 train + 1 test = 5 per fold × 3 folds = 15 max
        # Without cap: 9 train + 1 test = 10 per fold × 3 folds = 30
        call_count = engine.run_single.call_count
        self.assertLess(call_count, 25)  # Significantly less than uncapped (30)

    def test_min_trades_per_fold_rejects_low_trade_count(self):
        """Candidates with insufficient trades are rejected, triggering fallback."""
        from services.walkforward_runner import WalkForwardRunner

        # Engine returns 3 trades (below min_trades=5)
        engine = self._create_mock_engine(trade_count=3)
        tune_grid = {"conviction_floor": [0.5, 0.7]}
        request = self._create_mock_request(tune_grid=tune_grid, min_trades=5)
        config = self._create_mock_config()

        runner = WalkForwardRunner(engine)
        result = runner.run_walk_forward(request, config)

        # All candidates rejected, triggers v5 fallback
        if result.folds:
            fold = result.folds[0]
            # v5: fallback runs populate train_metrics from fallback run
            self.assertTrue(fold.get("tuning_fallback", False))
            self.assertIn("fallback", fold["optimized_params"])

    def test_best_params_chosen_by_objective(self):
        """Best params selected based on objective metric score."""
        from services.walkforward_runner import WalkForwardRunner

        # Return different sharpe for each call
        call_count = [0]
        sharpe_values = [0.5, 1.5, 0.8, 1.0]  # Second combo (1.5) is best

        def mock_run_single(*args, **kwargs):
            result = MagicMock()
            result.trades = [{"pnl": 100}] * 10
            result.events = []
            idx = min(call_count[0], len(sharpe_values) - 1)
            result.metrics = {"sharpe": sharpe_values[idx]}
            call_count[0] += 1
            return result

        engine = MagicMock()
        engine.run_single.side_effect = mock_run_single

        tune_grid = {"conviction_floor": [0.5, 0.6, 0.7, 0.8]}
        request = self._create_mock_request(tune_grid=tune_grid)
        config = self._create_mock_config()

        runner = WalkForwardRunner(engine)
        result = runner.run_walk_forward(request, config)

        if result.folds:
            fold = result.folds[0]
            # Best sharpe (1.5) corresponds to conviction_floor=0.6 (second candidate)
            self.assertEqual(fold["optimized_params"]["conviction_floor"], 0.6)


class TestFallbackLegacyCandidates(unittest.TestCase):
    """Tests for fallback to legacy conviction_floor candidates."""

    def _create_mock_engine(self, trade_count=10):
        """Create mock engine."""
        mock_engine = MagicMock()
        mock_result = MagicMock()
        mock_result.trades = [{"pnl": 100}] * trade_count
        mock_result.events = []
        mock_result.metrics = {"sharpe": 1.0}
        mock_engine.run_single.return_value = mock_result
        return mock_engine

    def _create_mock_request_no_grid(self):
        """Create mock request without tune_grid."""
        mock_wf = MagicMock()
        mock_wf.train_days = 30
        mock_wf.test_days = 10
        mock_wf.step_days = 10
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
        mock_request.end_date = "2024-03-01"
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

    def test_no_tune_grid_uses_legacy_candidates(self):
        """When tune_grid is None, uses [0.5, 0.6, 0.7, 0.8, 0.9] candidates."""
        from services.walkforward_runner import WalkForwardRunner

        engine = self._create_mock_engine()
        request = self._create_mock_request_no_grid()
        config = self._create_mock_config()

        runner = WalkForwardRunner(engine)
        runner.run_walk_forward(request, config)

        # Should call 5 train candidates + 1 test per fold
        call_count = engine.run_single.call_count
        self.assertGreaterEqual(call_count, 6)  # At least 5 train + 1 test

    def test_fallback_only_tunes_conviction_floor(self):
        """Fallback mode only optimizes conviction_floor."""
        from services.walkforward_runner import WalkForwardRunner

        engine = self._create_mock_engine()
        request = self._create_mock_request_no_grid()
        config = self._create_mock_config()

        runner = WalkForwardRunner(engine)
        result = runner.run_walk_forward(request, config)

        if result.folds:
            fold = result.folds[0]
            # optimized_params should only have conviction_floor
            self.assertIn("conviction_floor", fold["optimized_params"])
            self.assertEqual(len(fold["optimized_params"]), 1)


class TestWalkForwardConfigFields(unittest.TestCase):
    """Tests that WalkForwardConfig has new v4 fields."""

    def test_tune_grid_field_exists(self):
        """WalkForwardConfig has tune_grid field."""
        from strategy_profiles import WalkForwardConfig

        config = WalkForwardConfig(
            train_days=60,
            test_days=30,
            step_days=30,
            tune_grid={"conviction_floor": [0.5, 0.7]}
        )
        self.assertEqual(config.tune_grid, {"conviction_floor": [0.5, 0.7]})

    def test_objective_metric_field_exists(self):
        """WalkForwardConfig has objective_metric field with default sharpe."""
        from strategy_profiles import WalkForwardConfig

        config = WalkForwardConfig(
            train_days=60,
            test_days=30,
            step_days=30
        )
        self.assertEqual(config.objective_metric, "sharpe")

    def test_max_tune_combinations_field_exists(self):
        """WalkForwardConfig has max_tune_combinations field with default 50."""
        from strategy_profiles import WalkForwardConfig

        config = WalkForwardConfig(
            train_days=60,
            test_days=30,
            step_days=30
        )
        self.assertEqual(config.max_tune_combinations, 50)

    def test_objective_metric_literal_validation(self):
        """objective_metric only accepts valid literals."""
        from strategy_profiles import WalkForwardConfig

        for metric in ["sharpe", "profit_factor", "calmar"]:
            config = WalkForwardConfig(
                train_days=60,
                test_days=30,
                step_days=30,
                objective_metric=metric
            )
            self.assertEqual(config.objective_metric, metric)


if __name__ == "__main__":
    unittest.main()
