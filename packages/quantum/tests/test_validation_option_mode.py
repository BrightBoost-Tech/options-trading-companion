"""
Tests for PR3: Wire options mode into /validation/run payload.

Verifies:
1. HistoricalRunConfig accepts instrument_type="option" with option parameters
2. GoLiveValidationService.eval_historical resolves option contracts
3. Backtest is invoked with option ticker (O: prefix)
4. Suite records include trades_count and return_pct fields
"""
import pytest
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch, PropertyMock

from packages.quantum.validation_endpoints import HistoricalRunConfig, ValidationRunRequest


class TestHistoricalRunConfigOptionFields:
    """Tests for HistoricalRunConfig with option fields."""

    def test_default_is_stock(self):
        """Default instrument_type is 'stock'."""
        config = HistoricalRunConfig()
        assert config.instrument_type == "stock"
        assert config.option_right is None
        assert config.option_dte == 30
        assert config.option_moneyness == "atm"

    def test_option_instrument_type_valid(self):
        """instrument_type='option' is accepted with option params."""
        config = HistoricalRunConfig(
            symbol="SPY",
            instrument_type="option",
            option_right="call",
            option_dte=45,
            option_moneyness="otm_5pct"
        )
        assert config.instrument_type == "option"
        assert config.option_right == "call"
        assert config.option_dte == 45
        assert config.option_moneyness == "otm_5pct"

    def test_option_put_valid(self):
        """option_right='put' is valid."""
        config = HistoricalRunConfig(
            instrument_type="option",
            option_right="put",
            option_moneyness="itm_5pct"
        )
        assert config.option_right == "put"
        assert config.option_moneyness == "itm_5pct"

    def test_backward_compatible_stock_mode(self):
        """Stock mode (default) remains backward compatible."""
        config = HistoricalRunConfig(
            symbol="SPY",
            window_days=90,
            concurrent_runs=3,
            goal_return_pct=10.0
        )
        # Should work exactly as before
        assert config.symbol == "SPY"
        assert config.window_days == 90
        assert config.instrument_type == "stock"

    def test_config_serializes_to_dict(self):
        """Config serializes to dict including new option fields."""
        config = HistoricalRunConfig(
            symbol="AAPL",
            instrument_type="option",
            option_right="call",
            option_dte=30,
            option_moneyness="atm"
        )
        d = config.dict()
        assert d["instrument_type"] == "option"
        assert d["option_right"] == "call"
        assert d["option_dte"] == 30
        assert d["option_moneyness"] == "atm"


class TestValidationRunRequestWithOptions:
    """Tests for ValidationRunRequest with option mode."""

    def test_historical_option_request(self):
        """ValidationRunRequest with historical option mode."""
        request = ValidationRunRequest(
            mode="historical",
            historical=HistoricalRunConfig(
                symbol="SPY",
                instrument_type="option",
                option_right="call",
                option_dte=30
            )
        )
        assert request.mode == "historical"
        assert request.historical.instrument_type == "option"
        assert request.historical.option_right == "call"


class TestEvalHistoricalOptionMode:
    """Tests for GoLiveValidationService.eval_historical with option mode."""

    @patch('packages.quantum.services.go_live_validation_service.OptionContractResolver')
    @patch('packages.quantum.services.go_live_validation_service.BacktestEngine')
    def test_option_resolver_called_for_option_mode(self, mock_engine_class, mock_resolver_class):
        """OptionContractResolver is used when instrument_type='option'."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService

        # Setup mocks
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

        # Setup resolver mock - PR6: Now uses resolve_contract_with_coverage
        mock_resolver = MagicMock()
        mock_resolver.resolve_contract_with_coverage.return_value = "O:SPY240315C00450000"
        mock_resolver_class.return_value = mock_resolver

        # Setup backtest engine mock
        mock_engine = MagicMock()
        mock_bt_result = MagicMock()
        mock_bt_result.equity_curve = [{"equity": 10500}]
        mock_bt_result.trades = [{"exit_date": "2024-02-15", "pnl": 500}]
        mock_engine.run_single.return_value = mock_bt_result
        mock_engine_class.return_value = mock_engine

        service = GoLiveValidationService(mock_supabase)

        # Run with option mode (PR7: use_rolling_contracts=False to test static mode)
        result = service.eval_historical("test-user", {
            "symbol": "SPY",
            "instrument_type": "option",
            "option_right": "call",
            "option_dte": 30,
            "option_moneyness": "atm",
            "window_days": 30,
            "concurrent_runs": 1,
            "use_rolling_contracts": False  # PR7: Test static mode
        })

        # Verify resolver was instantiated and called (PR6: now uses resolve_contract_with_coverage)
        mock_resolver_class.assert_called_once()
        assert mock_resolver.resolve_contract_with_coverage.called

        # Verify backtest was called with option symbol
        call_args = mock_engine.run_single.call_args
        assert call_args is not None
        # The symbol argument should be the resolved option symbol
        assert call_args.kwargs.get("symbol") == "O:SPY240315C00450000" or \
               (call_args.args and "O:" in str(call_args.args))

    @patch('packages.quantum.services.go_live_validation_service.OptionContractResolver')
    @patch('packages.quantum.services.go_live_validation_service.BacktestEngine')
    def test_stock_mode_does_not_use_resolver(self, mock_engine_class, mock_resolver_class):
        """OptionContractResolver is NOT used when instrument_type='stock'."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService

        # Setup mocks
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

        # Setup backtest engine mock
        mock_engine = MagicMock()
        mock_bt_result = MagicMock()
        mock_bt_result.equity_curve = [{"equity": 10500}]
        mock_bt_result.trades = [{"exit_date": "2024-02-15", "pnl": 500}]
        mock_engine.run_single.return_value = mock_bt_result
        mock_engine_class.return_value = mock_engine

        service = GoLiveValidationService(mock_supabase)

        # Run with stock mode (default)
        result = service.eval_historical("test-user", {
            "symbol": "SPY",
            "instrument_type": "stock",  # Explicit stock
            "window_days": 30,
            "concurrent_runs": 1
        })

        # Resolver should not be instantiated
        mock_resolver_class.assert_not_called()

        # Backtest should be called with stock symbol
        call_args = mock_engine.run_single.call_args
        assert call_args is not None
        symbol_used = call_args.kwargs.get("symbol", call_args.args[0] if call_args.args else None)
        assert symbol_used == "SPY"

    @patch('packages.quantum.services.go_live_validation_service.OptionContractResolver')
    @patch('packages.quantum.services.go_live_validation_service.BacktestEngine')
    def test_suite_records_include_required_fields(self, mock_engine_class, mock_resolver_class):
        """Suite records include trades_count and return_pct fields."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService

        # Setup mocks
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

        # Setup resolver mock - PR6: Now uses resolve_contract_with_coverage
        mock_resolver = MagicMock()
        mock_resolver.resolve_contract_with_coverage.return_value = "O:SPY240315C00450000"
        mock_resolver_class.return_value = mock_resolver

        # Setup backtest engine mock
        mock_engine = MagicMock()
        mock_bt_result = MagicMock()
        mock_bt_result.equity_curve = [{"equity": 11000}]  # 10% gain
        mock_bt_result.trades = [
            {"exit_date": "2024-02-10", "pnl": 500},
            {"exit_date": "2024-02-20", "pnl": 500}
        ]
        mock_engine.run_single.return_value = mock_bt_result
        mock_engine_class.return_value = mock_engine

        service = GoLiveValidationService(mock_supabase)

        result = service.eval_historical("test-user", {
            "symbol": "SPY",
            "instrument_type": "option",
            "option_right": "call",
            "option_dte": 30,
            "window_days": 30,
            "concurrent_runs": 1
        })

        # Verify result structure
        assert "suites" in result
        assert len(result["suites"]) > 0

        suite = result["suites"][0]
        assert "trades_count" in suite
        assert "return_pct" in suite
        assert suite["trades_count"] == 2
        assert suite["return_pct"] == 10.0  # (11000 - 10000) / 10000 * 100

    @patch('packages.quantum.services.go_live_validation_service.OptionContractResolver')
    @patch('packages.quantum.services.go_live_validation_service.BacktestEngine')
    def test_option_symbol_included_in_suite_record(self, mock_engine_class, mock_resolver_class):
        """Suite record includes the resolved option symbol."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService

        # Setup mocks
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

        # Setup resolver mock - PR6: Now uses resolve_contract_with_coverage
        mock_resolver = MagicMock()
        mock_resolver.resolve_contract_with_coverage.return_value = "O:AAPL240315C00175000"
        mock_resolver_class.return_value = mock_resolver

        # Setup backtest engine mock
        mock_engine = MagicMock()
        mock_bt_result = MagicMock()
        mock_bt_result.equity_curve = [{"equity": 10500}]
        mock_bt_result.trades = [{"exit_date": "2024-02-15", "pnl": 500}]
        mock_engine.run_single.return_value = mock_bt_result
        mock_engine_class.return_value = mock_engine

        service = GoLiveValidationService(mock_supabase)

        result = service.eval_historical("test-user", {
            "symbol": "AAPL",
            "instrument_type": "option",
            "option_right": "call",
            "option_dte": 30,
            "window_days": 30,
            "concurrent_runs": 1,
            "use_rolling_contracts": False  # PR7: Test static mode
        })

        # Verify suite record includes the option symbol
        assert "suites" in result
        suite = result["suites"][0]
        assert "symbol" in suite
        assert suite["symbol"] == "O:AAPL240315C00175000"


class TestOptionModeFallback:
    """Tests for fallback behavior when option resolution fails."""

    @patch('packages.quantum.services.go_live_validation_service.OptionContractResolver')
    @patch('packages.quantum.services.go_live_validation_service.BacktestEngine')
    def test_fallback_to_underlying_when_no_option_found(self, mock_engine_class, mock_resolver_class):
        """Falls back to underlying symbol when option cannot be resolved."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService

        # Setup mocks
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

        # Resolver returns None (no option found with sufficient coverage)
        # PR6: Now uses resolve_contract_with_coverage
        mock_resolver = MagicMock()
        mock_resolver.resolve_contract_with_coverage.return_value = None
        mock_resolver_class.return_value = mock_resolver

        # Setup backtest engine mock
        mock_engine = MagicMock()
        mock_bt_result = MagicMock()
        mock_bt_result.equity_curve = [{"equity": 10500}]
        mock_bt_result.trades = [{"exit_date": "2024-02-15", "pnl": 500}]
        mock_engine.run_single.return_value = mock_bt_result
        mock_engine_class.return_value = mock_engine

        service = GoLiveValidationService(mock_supabase)

        result = service.eval_historical("test-user", {
            "symbol": "SPY",
            "instrument_type": "option",
            "option_right": "call",
            "window_days": 30,
            "concurrent_runs": 1
        })

        # Backtest should be called with underlying symbol as fallback
        call_args = mock_engine.run_single.call_args
        symbol_used = call_args.kwargs.get("symbol", call_args.args[0] if call_args.args else None)
        # Falls back to underlying when resolver returns None
        assert symbol_used == "SPY"


class TestPR10RuntimeKnobsInSchema:
    """PR10: Tests for runtime knobs exposed in HistoricalRunConfig schema."""

    def test_default_values(self):
        """New fields have correct default values."""
        config = HistoricalRunConfig()
        assert config.use_rolling_contracts is True
        assert config.strict_option_mode is False
        assert config.segment_tolerance_pct == 0.0

    def test_accepts_custom_values(self):
        """New fields accept custom values."""
        config = HistoricalRunConfig(
            use_rolling_contracts=False,
            strict_option_mode=True,
            segment_tolerance_pct=5.0
        )
        assert config.use_rolling_contracts is False
        assert config.strict_option_mode is True
        assert config.segment_tolerance_pct == 5.0

    def test_dict_includes_new_fields(self):
        """dict() includes the new PR7/PR8 runtime knob fields."""
        config = HistoricalRunConfig(
            symbol="SPY",
            use_rolling_contracts=False,
            strict_option_mode=True,
            segment_tolerance_pct=3.5
        )
        d = config.dict()
        assert "use_rolling_contracts" in d
        assert "strict_option_mode" in d
        assert "segment_tolerance_pct" in d
        assert d["use_rolling_contracts"] is False
        assert d["strict_option_mode"] is True
        assert d["segment_tolerance_pct"] == 3.5

    def test_full_payload_with_all_knobs(self):
        """Full ValidationRunRequest with all runtime knobs."""
        request = ValidationRunRequest(
            mode="historical",
            historical=HistoricalRunConfig(
                symbol="AAPL",
                instrument_type="option",
                option_right="call",
                option_dte=45,
                use_rolling_contracts=True,
                strict_option_mode=True,
                segment_tolerance_pct=2.0,
                train=True,
                train_target_streak=5
            )
        )
        assert request.historical.use_rolling_contracts is True
        assert request.historical.strict_option_mode is True
        assert request.historical.segment_tolerance_pct == 2.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
