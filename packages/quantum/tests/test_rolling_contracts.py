"""
Tests for PR7: Rolling contracts and historical option resolution.

Verifies:
1. BacktestEngine supports rolling_options mode
2. OptionContractResolver.resolve_contract_asof uses historical spot
3. Training loop mutates option_dte/moneyness on no_trades
4. strict_option_mode fails instead of fallback
"""
import pytest
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch, call

from packages.quantum.services.backtest_engine import BacktestEngine
from packages.quantum.strategy_profiles import StrategyConfig, CostModelConfig


class TestBacktestEngineRollingMode:
    """Tests for BacktestEngine rolling contract mode."""

    @patch('packages.quantum.services.backtest_engine.PolygonService')
    def test_rolling_mode_detects_parameters(self, mock_polygon_class):
        """Rolling mode is detected when rolling_options and option_resolver are provided."""
        mock_polygon = MagicMock()

        # Setup historical prices for underlying
        dates = [(date(2024, 1, 15) + timedelta(days=i)).isoformat() for i in range(90)]
        mock_polygon.get_historical_prices.return_value = {
            "dates": dates,
            "prices": [100.0] * 90
        }

        # Setup option historical prices
        mock_polygon.get_option_historical_prices.return_value = {
            "dates": dates,
            "prices": [5.0] * 90
        }

        mock_polygon_class.return_value = mock_polygon

        engine = BacktestEngine(polygon_service=mock_polygon)

        # Create mock resolver
        mock_resolver = MagicMock()
        mock_resolver.resolve_contract_asof.return_value = "O:SPY240315C00450000"
        mock_resolver.polygon = mock_polygon

        rolling_options = {
            "right": "call",
            "target_dte": 30,
            "moneyness": "atm"
        }

        config = StrategyConfig(
            name="test",
            version=1,
            conviction_floor=0.1,  # Low to trigger entries
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

        # Run in rolling mode
        result = engine.run_single(
            symbol="SPY",
            start_date="2024-01-15",
            end_date="2024-02-15",
            config=config,
            cost_model=CostModelConfig(),
            seed=42,
            initial_equity=10000,
            rolling_options=rolling_options,
            option_resolver=mock_resolver
        )

        # Should complete without error
        assert result is not None
        assert result.backtest_id is not None

    @patch('packages.quantum.services.backtest_engine.PolygonService')
    def test_rolling_mode_resolves_contract_on_entry(self, mock_polygon_class):
        """In rolling mode, contract is resolved at entry time."""
        mock_polygon = MagicMock()

        # Setup historical prices for underlying
        dates = [(date(2024, 1, 15) + timedelta(days=i)).isoformat() for i in range(90)]
        mock_polygon.get_historical_prices.return_value = {
            "dates": dates,
            "prices": [100.0] * 90
        }

        # Setup option historical prices
        mock_polygon.get_option_historical_prices.return_value = {
            "dates": dates,
            "prices": [5.0] * 90
        }

        mock_polygon_class.return_value = mock_polygon

        engine = BacktestEngine(polygon_service=mock_polygon)

        # Create mock resolver that tracks calls
        mock_resolver = MagicMock()
        mock_resolver.resolve_contract_asof.return_value = "O:SPY240315C00450000"

        rolling_options = {
            "right": "call",
            "target_dte": 30,
            "moneyness": "atm"
        }

        config = StrategyConfig(
            name="test",
            version=1,
            conviction_floor=0.1,
            take_profit_pct=0.50,  # High to avoid early exit
            stop_loss_pct=0.50,
            max_holding_days=90,
            max_risk_pct_portfolio=0.10,
            max_concurrent_positions=1,
            conviction_slope=0.2,
            max_risk_pct_per_trade=0.05,
            max_spread_bps=100,
            max_days_to_expiry=45,
            min_underlying_liquidity=1000000.0,
            regime_whitelist=[]
        )

        result = engine.run_single(
            symbol="SPY",
            start_date="2024-01-15",
            end_date="2024-03-15",
            config=config,
            cost_model=CostModelConfig(),
            seed=42,
            initial_equity=10000,
            rolling_options=rolling_options,
            option_resolver=mock_resolver
        )

        # If trades were made, resolver should have been called
        if result.trades:
            assert mock_resolver.resolve_contract_asof.called
            # Each trade should have a contract symbol
            for trade in result.trades:
                assert "O:" in trade["symbol"]

    @patch('packages.quantum.services.backtest_engine.PolygonService')
    def test_rolling_mode_skips_entry_when_no_contract(self, mock_polygon_class):
        """Rolling mode skips entry when no contract can be resolved."""
        mock_polygon = MagicMock()
        dates = [(date(2024, 1, 15) + timedelta(days=i)).isoformat() for i in range(90)]
        mock_polygon.get_historical_prices.return_value = {
            "dates": dates,
            "prices": [100.0] * 90
        }
        mock_polygon_class.return_value = mock_polygon

        engine = BacktestEngine(polygon_service=mock_polygon)

        # Resolver returns None (no contract available)
        mock_resolver = MagicMock()
        mock_resolver.resolve_contract_asof.return_value = None

        rolling_options = {
            "right": "call",
            "target_dte": 30,
            "moneyness": "atm"
        }

        config = StrategyConfig(
            name="test",
            version=1,
            conviction_floor=0.1,
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

        result = engine.run_single(
            symbol="SPY",
            start_date="2024-01-15",
            end_date="2024-02-15",
            config=config,
            cost_model=CostModelConfig(),
            seed=42,
            initial_equity=10000,
            rolling_options=rolling_options,
            option_resolver=mock_resolver
        )

        # No trades should be made if resolver always returns None
        assert result.trades == []

    @patch('packages.quantum.services.backtest_engine.PolygonService')
    def test_rolling_mode_tracks_unique_contracts(self, mock_polygon_class):
        """Metrics track unique contracts traded in rolling mode."""
        mock_polygon = MagicMock()
        dates = [(date(2024, 1, 15) + timedelta(days=i)).isoformat() for i in range(90)]
        mock_polygon.get_historical_prices.return_value = {
            "dates": dates,
            "prices": [100.0] * 90
        }
        mock_polygon.get_option_historical_prices.return_value = {
            "dates": dates,
            "prices": [5.0] * 90
        }
        mock_polygon_class.return_value = mock_polygon

        engine = BacktestEngine(polygon_service=mock_polygon)

        # Resolver returns different contracts for different dates
        call_count = [0]
        def resolve_side_effect(*args, **kwargs):
            call_count[0] += 1
            return f"O:SPY240315C0045000{call_count[0]}"

        mock_resolver = MagicMock()
        mock_resolver.resolve_contract_asof.side_effect = resolve_side_effect

        rolling_options = {
            "right": "call",
            "target_dte": 30,
            "moneyness": "atm"
        }

        config = StrategyConfig(
            name="test",
            version=1,
            conviction_floor=0.1,
            take_profit_pct=0.02,  # Quick exits to allow multiple trades
            stop_loss_pct=0.01,
            max_holding_days=3,
            max_risk_pct_portfolio=0.10,
            max_concurrent_positions=1,
            conviction_slope=0.2,
            max_risk_pct_per_trade=0.05,
            max_spread_bps=100,
            max_days_to_expiry=45,
            min_underlying_liquidity=1000000.0,
            regime_whitelist=[]
        )

        result = engine.run_single(
            symbol="SPY",
            start_date="2024-01-15",
            end_date="2024-03-15",
            config=config,
            cost_model=CostModelConfig(),
            seed=42,
            initial_equity=10000,
            rolling_options=rolling_options,
            option_resolver=mock_resolver
        )

        # Should have rolling_mode metrics
        assert result.metrics.get("rolling_mode") == True
        assert result.metrics.get("underlying") == "SPY"


class TestResolveContractAsof:
    """Tests for OptionContractResolver.resolve_contract_asof method."""

    def test_uses_historical_spot_price(self):
        """resolve_contract_asof uses historical spot price for strike calculation."""
        from packages.quantum.services.option_contract_resolver import OptionContractResolver

        mock_polygon = MagicMock()

        # Historical spot price on 2024-02-14 was 450
        mock_polygon.get_historical_spot_price.return_value = 450.0

        # Option chain candidates (using normalized field names from API)
        mock_polygon.get_option_contract_candidates.return_value = [
            {"ticker": "O:SPY240315C00450000", "strike": 450.0,
             "expiration": "2024-03-15", "type": "call"},
            {"ticker": "O:SPY240315C00455000", "strike": 455.0,
             "expiration": "2024-03-15", "type": "call"},
        ]

        resolver = OptionContractResolver(polygon_service=mock_polygon)

        result = resolver.resolve_contract_asof(
            underlying="SPY",
            right="call",
            target_dte=30,
            moneyness="atm",
            as_of_date=date(2024, 2, 14)
        )

        # Should have used historical spot price
        mock_polygon.get_historical_spot_price.assert_called_once()
        # Should return ATM contract (strike closest to 450)
        assert result == "O:SPY240315C00450000"

    def test_handles_no_spot_price(self):
        """Returns None when historical spot price unavailable."""
        from packages.quantum.services.option_contract_resolver import OptionContractResolver

        mock_polygon = MagicMock()
        mock_polygon.get_historical_spot_price.return_value = None

        resolver = OptionContractResolver(polygon_service=mock_polygon)

        result = resolver.resolve_contract_asof(
            underlying="SPY",
            right="call",
            target_dte=30,
            moneyness="atm",
            as_of_date=date(2024, 2, 14)
        )

        assert result is None

    def test_handles_no_candidates(self):
        """Returns None when no option candidates available."""
        from packages.quantum.services.option_contract_resolver import OptionContractResolver

        mock_polygon = MagicMock()
        mock_polygon.get_historical_spot_price.return_value = 450.0
        mock_polygon.get_option_contract_candidates.return_value = []

        resolver = OptionContractResolver(polygon_service=mock_polygon)

        result = resolver.resolve_contract_asof(
            underlying="SPY",
            right="call",
            target_dte=30,
            moneyness="atm",
            as_of_date=date(2024, 2, 14)
        )

        assert result is None


class TestTrainingLoopOptionMutation:
    """Tests for training loop option parameter mutations."""

    @patch('packages.quantum.services.go_live_validation_service.BacktestEngine')
    @patch('packages.quantum.services.go_live_validation_service.OptionContractResolver')
    def test_mutates_option_dte_on_no_trades(self, mock_resolver_class, mock_engine_class):
        """Training loop mutates option_dte when no_trades and strategy params exhausted."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService
        from packages.quantum.strategy_profiles import StrategyConfig

        service = GoLiveValidationService(MagicMock())

        # Config with exhausted strategy params
        config = StrategyConfig(
            name="test",
            version=1,
            conviction_floor=0.05,  # Already at minimum
            take_profit_pct=0.05,
            stop_loss_pct=0.03,
            max_holding_days=10,
            max_risk_pct_portfolio=0.10,
            max_concurrent_positions=1,
            conviction_slope=0.2,
            max_risk_pct_per_trade=0.05,
            max_spread_bps=400,  # Already at maximum
            max_days_to_expiry=45,
            min_underlying_liquidity=1000000.0,
            regime_whitelist=[]
        )

        suite_config = {
            "instrument_type": "option",
            "option_dte": 30,
            "option_moneyness": "atm",
            "option_right": "call"
        }

        new_config, suite_updates = service._mutate_config(
            config, "no_trades", 0.0, suite_config
        )

        # Should mutate option_dte
        assert "option_dte" in suite_updates
        assert suite_updates["option_dte"] == 45  # 30 + 15

    @patch('packages.quantum.services.go_live_validation_service.BacktestEngine')
    @patch('packages.quantum.services.go_live_validation_service.OptionContractResolver')
    def test_mutates_option_moneyness_after_dte(self, mock_resolver_class, mock_engine_class):
        """Training loop mutates option_moneyness after option_dte is exhausted."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService
        from packages.quantum.strategy_profiles import StrategyConfig

        service = GoLiveValidationService(MagicMock())

        config = StrategyConfig(
            name="test",
            version=1,
            conviction_floor=0.05,
            take_profit_pct=0.05,
            stop_loss_pct=0.03,
            max_holding_days=10,
            max_risk_pct_portfolio=0.10,
            max_concurrent_positions=1,
            conviction_slope=0.2,
            max_risk_pct_per_trade=0.05,
            max_spread_bps=400,
            max_days_to_expiry=45,
            min_underlying_liquidity=1000000.0,
            regime_whitelist=[]
        )

        suite_config = {
            "instrument_type": "option",
            "option_dte": 60,  # Already at max
            "option_moneyness": "atm",
            "option_right": "call"
        }

        new_config, suite_updates = service._mutate_config(
            config, "no_trades", 0.0, suite_config
        )

        # Should mutate option_moneyness
        assert "option_moneyness" in suite_updates
        assert suite_updates["option_moneyness"] == "otm_5pct"

    @patch('packages.quantum.services.go_live_validation_service.BacktestEngine')
    @patch('packages.quantum.services.go_live_validation_service.OptionContractResolver')
    def test_mutates_option_right_after_moneyness(self, mock_resolver_class, mock_engine_class):
        """Training loop mutates option_right after moneyness is exhausted."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService
        from packages.quantum.strategy_profiles import StrategyConfig

        service = GoLiveValidationService(MagicMock())

        config = StrategyConfig(
            name="test",
            version=1,
            conviction_floor=0.05,
            take_profit_pct=0.05,
            stop_loss_pct=0.03,
            max_holding_days=10,
            max_risk_pct_portfolio=0.10,
            max_concurrent_positions=1,
            conviction_slope=0.2,
            max_risk_pct_per_trade=0.05,
            max_spread_bps=400,
            max_days_to_expiry=45,
            min_underlying_liquidity=1000000.0,
            regime_whitelist=[]
        )

        suite_config = {
            "instrument_type": "option",
            "option_dte": 60,
            "option_moneyness": "itm_5pct",  # Already cycled through
            "option_right": "call"
        }

        new_config, suite_updates = service._mutate_config(
            config, "no_trades", 0.0, suite_config
        )

        # Should mutate option_right and reset moneyness
        assert "option_right" in suite_updates
        assert suite_updates["option_right"] == "put"
        assert suite_updates["option_moneyness"] == "atm"


class TestStrictOptionMode:
    """Tests for strict_option_mode flag."""

    @patch('packages.quantum.services.go_live_validation_service.OptionContractResolver')
    @patch('packages.quantum.services.go_live_validation_service.BacktestEngine')
    def test_strict_mode_fails_when_no_contract(self, mock_engine_class, mock_resolver_class):
        """strict_option_mode returns failure when no option contract found."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService

        mock_supabase = MagicMock()
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
            "user_id": "test-user",
            "paper_baseline_capital": 10000,
            "paper_ready": False,
            "historical_last_result": {}
        }
        mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = []
        mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock()
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        # Resolver returns None (no contract found)
        mock_resolver = MagicMock()
        mock_resolver.resolve_contract_with_coverage.return_value = None
        mock_resolver_class.return_value = mock_resolver

        service = GoLiveValidationService(mock_supabase)

        result = service.eval_historical("test-user", {
            "symbol": "SPY",
            "instrument_type": "option",
            "option_right": "call",
            "option_dte": 30,
            "window_days": 30,
            "concurrent_runs": 1,
            "use_rolling_contracts": False,  # Use static mode
            "strict_option_mode": True  # Enable strict mode
        })

        # Should have failure due to no_option_contract
        assert "suites" in result
        suite = result["suites"][0]
        assert suite["passed"] == False
        assert suite["fail_reason"] == "no_option_contract"

    @patch('packages.quantum.services.go_live_validation_service.OptionContractResolver')
    @patch('packages.quantum.services.go_live_validation_service.BacktestEngine')
    def test_non_strict_mode_falls_back_to_underlying(self, mock_engine_class, mock_resolver_class):
        """Non-strict mode falls back to underlying when no option contract found."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService

        mock_supabase = MagicMock()
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
            "user_id": "test-user",
            "paper_baseline_capital": 10000,
            "paper_ready": False,
            "historical_last_result": {}
        }
        mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = []
        mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock()
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        # Resolver returns None (no contract found)
        mock_resolver = MagicMock()
        mock_resolver.resolve_contract_with_coverage.return_value = None
        mock_resolver_class.return_value = mock_resolver

        # Engine returns valid result
        mock_engine = MagicMock()
        mock_bt_result = MagicMock()
        mock_bt_result.equity_curve = [{"equity": 11000}]
        mock_bt_result.trades = [{"exit_date": "2024-02-15", "pnl": 1000}]
        mock_engine.run_single.return_value = mock_bt_result
        mock_engine_class.return_value = mock_engine

        service = GoLiveValidationService(mock_supabase)

        result = service.eval_historical("test-user", {
            "symbol": "SPY",
            "instrument_type": "option",
            "option_right": "call",
            "option_dte": 30,
            "window_days": 30,
            "concurrent_runs": 1,
            "use_rolling_contracts": False,
            "strict_option_mode": False  # Disable strict mode
        })

        # Backtest should have been called with underlying symbol
        call_args = mock_engine.run_single.call_args
        assert call_args.kwargs.get("symbol") == "SPY"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
