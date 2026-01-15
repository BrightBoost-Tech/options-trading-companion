"""
Tests for PR4: Self-learning training loop for historical validation.

Verifies:
1. train_historical runs until target_streak consecutive passes
2. Config mutation on failures based on fail_reason
3. Guardrails prevent extreme config values
4. Strategy config persistence with versioning
5. Exhausted status when max_attempts reached
"""
import pytest
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch, call

from packages.quantum.validation_endpoints import HistoricalRunConfig
from packages.quantum.strategy_profiles import StrategyConfig


class TestHistoricalRunConfigTrainingFields:
    """Tests for HistoricalRunConfig training fields."""

    def test_default_train_is_false(self):
        """Default train is False."""
        config = HistoricalRunConfig()
        assert config.train is False

    def test_train_fields_accepted(self):
        """Training fields are accepted."""
        config = HistoricalRunConfig(
            train=True,
            train_target_streak=3,
            train_max_attempts=20,
            train_strategy_name="my_strategy",
            train_versioning="increment"
        )
        assert config.train is True
        assert config.train_target_streak == 3
        assert config.train_max_attempts == 20
        assert config.train_strategy_name == "my_strategy"
        assert config.train_versioning == "increment"

    def test_train_versioning_overwrite(self):
        """train_versioning can be 'overwrite'."""
        config = HistoricalRunConfig(
            train=True,
            train_versioning="overwrite"
        )
        assert config.train_versioning == "overwrite"

    def test_train_fields_serialize_to_dict(self):
        """Training fields serialize to dict."""
        config = HistoricalRunConfig(
            train=True,
            train_target_streak=5,
            train_max_attempts=30
        )
        d = config.dict()
        assert d["train"] is True
        assert d["train_target_streak"] == 5
        assert d["train_max_attempts"] == 30


class TestTrainHistoricalMethod:
    """Tests for GoLiveValidationService.train_historical method."""

    def _create_mock_supabase(self, state_data=None, strategy_data=None):
        """Helper to create mock supabase client."""
        mock = MagicMock()

        # State query
        state_result = MagicMock()
        state_result.data = state_data or {
            "user_id": "test-user",
            "paper_baseline_capital": 10000,
            "paper_ready": False,
            "historical_last_result": {}
        }
        mock.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = state_result

        # Strategy query
        strategy_result = MagicMock()
        strategy_result.data = strategy_data or []
        mock.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = strategy_result

        # Insert/update mocks
        mock.table.return_value.insert.return_value.execute.return_value = MagicMock()
        mock.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock()

        return mock

    @patch('packages.quantum.services.go_live_validation_service.BacktestEngine')
    @patch('packages.quantum.services.go_live_validation_service.OptionContractResolver')
    def test_train_reaches_target_streak(self, mock_resolver_class, mock_engine_class):
        """Training succeeds when target_streak consecutive passes achieved."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService

        mock_supabase = self._create_mock_supabase()

        # Setup backtest to pass every time
        mock_engine = MagicMock()
        mock_bt_result = MagicMock()
        mock_bt_result.equity_curve = [{"equity": 11000}]  # 10% return
        mock_bt_result.trades = [{"exit_date": "2024-02-15", "pnl": 1000}]
        mock_engine.run_single.return_value = mock_bt_result
        mock_engine_class.return_value = mock_engine

        service = GoLiveValidationService(mock_supabase)

        result = service.train_historical("test-user", {
            "symbol": "SPY",
            "window_days": 30,
            "concurrent_runs": 1,
            "goal_return_pct": 10.0,
            "train": True,
            "train_target_streak": 3,
            "train_max_attempts": 10
        })

        assert result["status"] == "success"
        assert result["streak"] == 3
        assert result["attempts"] == 3  # Should reach 3 in exactly 3 attempts
        assert "best_config" in result

    @patch('packages.quantum.services.go_live_validation_service.BacktestEngine')
    @patch('packages.quantum.services.go_live_validation_service.OptionContractResolver')
    def test_train_exhausted_on_max_attempts(self, mock_resolver_class, mock_engine_class):
        """Training returns exhausted when max_attempts reached."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService

        mock_supabase = self._create_mock_supabase()

        # Setup backtest to always fail
        mock_engine = MagicMock()
        mock_bt_result = MagicMock()
        mock_bt_result.equity_curve = [{"equity": 9000}]  # -10% return (fails)
        mock_bt_result.trades = [{"exit_date": "2024-02-15", "pnl": -1000}]
        mock_engine.run_single.return_value = mock_bt_result
        mock_engine_class.return_value = mock_engine

        service = GoLiveValidationService(mock_supabase)

        result = service.train_historical("test-user", {
            "symbol": "SPY",
            "window_days": 30,
            "concurrent_runs": 1,
            "goal_return_pct": 10.0,
            "train": True,
            "train_target_streak": 3,
            "train_max_attempts": 5  # Low max for test speed
        })

        assert result["status"] == "exhausted"
        assert result["attempts"] == 5
        assert result["streak"] == 0

    @patch('packages.quantum.services.go_live_validation_service.BacktestEngine')
    @patch('packages.quantum.services.go_live_validation_service.OptionContractResolver')
    def test_train_streak_resets_on_failure(self, mock_resolver_class, mock_engine_class):
        """Streak resets to 0 when a run fails."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService

        mock_supabase = self._create_mock_supabase()

        # Setup backtest to alternate pass/fail
        mock_engine = MagicMock()
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] % 2 == 1:  # Odd calls pass
                result.equity_curve = [{"equity": 11000}]
                result.trades = [{"exit_date": "2024-02-15", "pnl": 1000}]
            else:  # Even calls fail
                result.equity_curve = [{"equity": 9000}]
                result.trades = [{"exit_date": "2024-02-15", "pnl": -1000}]
            return result

        mock_engine.run_single.side_effect = side_effect
        mock_engine_class.return_value = mock_engine

        service = GoLiveValidationService(mock_supabase)

        result = service.train_historical("test-user", {
            "symbol": "SPY",
            "window_days": 30,
            "concurrent_runs": 1,
            "goal_return_pct": 10.0,
            "train": True,
            "train_target_streak": 3,
            "train_max_attempts": 6
        })

        # Should exhaust because can never get 3 consecutive
        assert result["status"] == "exhausted"
        assert result["streak"] < 3

    @patch('packages.quantum.services.go_live_validation_service.BacktestEngine')
    @patch('packages.quantum.services.go_live_validation_service.OptionContractResolver')
    def test_train_history_records_attempts(self, mock_resolver_class, mock_engine_class):
        """History records each attempt with config snapshot."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService

        mock_supabase = self._create_mock_supabase()

        mock_engine = MagicMock()
        mock_bt_result = MagicMock()
        mock_bt_result.equity_curve = [{"equity": 11000}]
        mock_bt_result.trades = [{"exit_date": "2024-02-15", "pnl": 1000}]
        mock_engine.run_single.return_value = mock_bt_result
        mock_engine_class.return_value = mock_engine

        service = GoLiveValidationService(mock_supabase)

        result = service.train_historical("test-user", {
            "symbol": "SPY",
            "window_days": 30,
            "concurrent_runs": 1,
            "train": True,
            "train_target_streak": 2,
            "train_max_attempts": 10
        })

        assert "history" in result
        assert len(result["history"]) == 2
        for entry in result["history"]:
            assert "attempt" in entry
            assert "passed" in entry
            assert "config_snapshot" in entry


class TestConfigMutation:
    """Tests for _mutate_config method."""

    def test_mutate_return_below_goal_increases_risk(self):
        """return_below_goal failure increases risk tolerance."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService

        service = GoLiveValidationService(MagicMock())

        config = StrategyConfig(
            name="test",
            version=1,
            conviction_floor=0.55,
            take_profit_pct=0.05,
            stop_loss_pct=0.03,
            max_holding_days=10,
            max_risk_pct_portfolio=0.10,
            max_concurrent_positions=1,
            conviction_slope=0.2,
            max_risk_pct_per_trade=0.05,
            max_spread_bps=100,
            max_days_to_expiry=45,
            min_underlying_liquidity=1000000.0,
            regime_whitelist=[]
        )

        mutated = service._mutate_config(config, "return_below_goal", 5.0)

        # Should increase max_risk_pct_portfolio
        assert mutated.max_risk_pct_portfolio > config.max_risk_pct_portfolio

    def test_mutate_losing_segment_tightens_stop(self):
        """losing_segment failure tightens stop loss."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService

        service = GoLiveValidationService(MagicMock())

        config = StrategyConfig(
            name="test",
            version=1,
            conviction_floor=0.55,
            take_profit_pct=0.05,
            stop_loss_pct=0.03,
            max_holding_days=10,
            max_risk_pct_portfolio=0.10,
            max_concurrent_positions=1,
            conviction_slope=0.2,
            max_risk_pct_per_trade=0.05,
            max_spread_bps=100,
            max_days_to_expiry=45,
            min_underlying_liquidity=1000000.0,
            regime_whitelist=[]
        )

        mutated = service._mutate_config(config, "losing_segment", -5.0)

        # Should reduce stop_loss_pct (tighter stop)
        assert mutated.stop_loss_pct < config.stop_loss_pct

    def test_mutate_no_trades_lowers_conviction(self):
        """no_trades failure lowers conviction floor."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService

        service = GoLiveValidationService(MagicMock())

        config = StrategyConfig(
            name="test",
            version=1,
            conviction_floor=0.55,
            take_profit_pct=0.05,
            stop_loss_pct=0.03,
            max_holding_days=10,
            max_risk_pct_portfolio=0.10,
            max_concurrent_positions=1,
            conviction_slope=0.2,
            max_risk_pct_per_trade=0.05,
            max_spread_bps=100,
            max_days_to_expiry=45,
            min_underlying_liquidity=1000000.0,
            regime_whitelist=[]
        )

        mutated = service._mutate_config(config, "no_trades", 0.0)

        # Should lower conviction_floor
        assert mutated.conviction_floor < config.conviction_floor

    def test_guardrails_prevent_extreme_risk(self):
        """Guardrails prevent risk from exceeding 25%."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService

        service = GoLiveValidationService(MagicMock())

        config = StrategyConfig(
            name="test",
            version=1,
            conviction_floor=0.55,
            take_profit_pct=0.05,
            stop_loss_pct=0.03,
            max_holding_days=10,
            max_risk_pct_portfolio=0.24,  # Near max
            max_concurrent_positions=1,
            conviction_slope=0.2,
            max_risk_pct_per_trade=0.05,
            max_spread_bps=100,
            max_days_to_expiry=45,
            min_underlying_liquidity=1000000.0,
            regime_whitelist=[]
        )

        mutated = service._mutate_config(config, "return_below_goal", 5.0)

        # Should not exceed 0.25 guardrail
        assert mutated.max_risk_pct_portfolio <= 0.25

    def test_guardrails_prevent_extreme_conviction(self):
        """PR5: Guardrails prevent conviction from going below 0.05 (lowered from 0.35)."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService

        service = GoLiveValidationService(MagicMock())

        config = StrategyConfig(
            name="test",
            version=1,
            conviction_floor=0.06,  # Near new min of 0.05
            take_profit_pct=0.05,
            stop_loss_pct=0.03,
            max_holding_days=10,
            max_risk_pct_portfolio=0.10,
            max_concurrent_positions=1,
            conviction_slope=0.2,
            max_risk_pct_per_trade=0.05,
            max_spread_bps=100,
            max_days_to_expiry=45,
            min_underlying_liquidity=1000000.0,
            regime_whitelist=[]
        )

        mutated = service._mutate_config(config, "no_trades", 0.0)

        # PR5: Should not go below 0.05 guardrail (lowered from 0.35)
        assert mutated.conviction_floor >= 0.05

    def test_no_trades_mutation_escapes_old_deadlock(self):
        """PR5: no_trades mutation works even when conviction_floor <= 0.35."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService

        service = GoLiveValidationService(MagicMock())

        # Config with conviction_floor at old limit (0.35) - would NOT mutate before PR5
        config = StrategyConfig(
            name="test",
            version=1,
            conviction_floor=0.25,  # Below old 0.35 limit
            take_profit_pct=0.05,
            stop_loss_pct=0.03,
            max_holding_days=10,
            max_risk_pct_portfolio=0.10,
            max_concurrent_positions=1,
            conviction_slope=0.2,
            max_risk_pct_per_trade=0.05,
            max_spread_bps=200,  # At old max limit
            max_days_to_expiry=45,
            min_underlying_liquidity=1000000.0,
            regime_whitelist=[]
        )

        mutated = service._mutate_config(config, "no_trades", 0.0)

        # PR5: Should still mutate - lower conviction_floor below 0.25
        assert mutated.conviction_floor < config.conviction_floor, \
            "no_trades should reduce conviction_floor even when already <= 0.35"

    def test_no_trades_mutation_increases_spread_above_200(self):
        """PR5: no_trades can increase max_spread_bps above 200 (up to 400)."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService

        service = GoLiveValidationService(MagicMock())

        # Config with conviction_floor at minimum (0.05) - must mutate spread instead
        config = StrategyConfig(
            name="test",
            version=1,
            conviction_floor=0.05,  # At new minimum
            take_profit_pct=0.05,
            stop_loss_pct=0.03,
            max_holding_days=10,
            max_risk_pct_portfolio=0.10,
            max_concurrent_positions=1,
            conviction_slope=0.2,
            max_risk_pct_per_trade=0.05,
            max_spread_bps=200,  # At old limit, below new limit of 400
            max_days_to_expiry=45,
            min_underlying_liquidity=1000000.0,
            regime_whitelist=[]
        )

        mutated = service._mutate_config(config, "no_trades", 0.0)

        # PR5: Should increase max_spread_bps since conviction_floor is at min
        assert mutated.max_spread_bps > config.max_spread_bps, \
            "no_trades should increase max_spread_bps when conviction_floor at min"
        assert mutated.max_spread_bps <= 400, \
            "max_spread_bps should not exceed 400 guardrail"

    def test_no_trades_mutation_repeatedly_lowers_conviction(self):
        """PR5: Repeated no_trades mutations keep lowering conviction_floor."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService

        service = GoLiveValidationService(MagicMock())

        config = StrategyConfig(
            name="test",
            version=1,
            conviction_floor=0.55,
            take_profit_pct=0.05,
            stop_loss_pct=0.03,
            max_holding_days=10,
            max_risk_pct_portfolio=0.10,
            max_concurrent_positions=1,
            conviction_slope=0.2,
            max_risk_pct_per_trade=0.05,
            max_spread_bps=100,
            max_days_to_expiry=45,
            min_underlying_liquidity=1000000.0,
            regime_whitelist=[]
        )

        # Simulate multiple mutation rounds
        values = [config.conviction_floor]
        current = config
        for _ in range(10):
            current = service._mutate_config(current, "no_trades", 0.0)
            values.append(current.conviction_floor)

        # Should be strictly decreasing until hitting min
        for i in range(1, len(values)):
            if values[i-1] > 0.05:
                assert values[i] < values[i-1], \
                    f"conviction_floor should decrease: {values[i-1]} -> {values[i]}"

        # Final value should be at or near minimum
        assert current.conviction_floor <= 0.10, \
            "After 10 mutations, conviction_floor should be near minimum"


class TestStrategyPersistence:
    """Tests for strategy config persistence."""

    def test_persist_strategy_increment_versioning(self):
        """Increment versioning inserts new row."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService

        mock_supabase = MagicMock()
        service = GoLiveValidationService(mock_supabase)

        config = StrategyConfig(
            name="test",
            version=1,
            conviction_floor=0.55,
            take_profit_pct=0.05,
            stop_loss_pct=0.03,
            max_holding_days=10,
            max_risk_pct_portfolio=0.10,
            max_concurrent_positions=1,
            conviction_slope=0.2,
            max_risk_pct_per_trade=0.05,
            max_spread_bps=100,
            max_days_to_expiry=45,
            min_underlying_liquidity=1000000.0,
            regime_whitelist=[]
        )

        service._persist_strategy_config(
            "test-user", "my_strategy", config, 2, "increment"
        )

        # Should call insert
        mock_supabase.table.return_value.insert.assert_called()

    def test_persist_strategy_overwrite_versioning(self):
        """Overwrite versioning updates existing row."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService

        mock_supabase = MagicMock()
        # Simulate existing config found
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{"id": "123"}]

        service = GoLiveValidationService(mock_supabase)

        config = StrategyConfig(
            name="test",
            version=1,
            conviction_floor=0.55,
            take_profit_pct=0.05,
            stop_loss_pct=0.03,
            max_holding_days=10,
            max_risk_pct_portfolio=0.10,
            max_concurrent_positions=1,
            conviction_slope=0.2,
            max_risk_pct_per_trade=0.05,
            max_spread_bps=100,
            max_days_to_expiry=45,
            min_underlying_liquidity=1000000.0,
            regime_whitelist=[]
        )

        service._persist_strategy_config(
            "test-user", "my_strategy", config, 2, "overwrite"
        )

        # Should call update
        mock_supabase.table.return_value.update.assert_called()


class TestJobHandlerIntegration:
    """Tests for validation_eval job handler with train mode."""

    @patch('packages.quantum.jobs.handlers.validation_eval._get_supabase_client')
    @patch('packages.quantum.jobs.handlers.validation_eval.GoLiveValidationService')
    def test_job_calls_train_historical_when_train_true(self, mock_service_class, mock_get_client):
        """Job handler calls train_historical when train=True."""
        from packages.quantum.jobs.handlers.validation_eval import run

        mock_supabase = MagicMock()
        mock_get_client.return_value = mock_supabase

        mock_service = MagicMock()
        mock_service.train_historical.return_value = {"status": "success", "streak": 3}
        mock_service_class.return_value = mock_service

        result = run({
            "mode": "historical",
            "user_id": "test-user",
            "config": {
                "train": True,
                "train_target_streak": 3
            }
        })

        mock_service.train_historical.assert_called_once()
        assert result["mode"] == "train"
        assert result["status"] == "completed"

    @patch('packages.quantum.jobs.handlers.validation_eval._get_supabase_client')
    @patch('packages.quantum.jobs.handlers.validation_eval.GoLiveValidationService')
    def test_job_calls_eval_historical_when_train_false(self, mock_service_class, mock_get_client):
        """Job handler calls eval_historical when train=False."""
        from packages.quantum.jobs.handlers.validation_eval import run

        mock_supabase = MagicMock()
        mock_get_client.return_value = mock_supabase

        mock_service = MagicMock()
        mock_service.eval_historical.return_value = {"all_passed": True}
        mock_service_class.return_value = mock_service

        result = run({
            "mode": "historical",
            "user_id": "test-user",
            "config": {
                "train": False
            }
        })

        mock_service.eval_historical.assert_called_once()
        mock_service.train_historical.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
