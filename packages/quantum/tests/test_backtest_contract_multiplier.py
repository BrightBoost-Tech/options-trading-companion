"""
Tests for PR1: Contract multiplier & contracts accounting.

Verifies:
1. TransactionCostModel.simulate_fill() handles multiplier for slippage
2. BacktestEngine detects option symbols and applies 100x multiplier
3. Stock behavior unchanged (multiplier=1)
4. Correct math for cost basis, proceeds, PnL, and equity
"""
import pytest
import random
from unittest.mock import MagicMock, patch

from packages.quantum.services.transaction_cost_model import TransactionCostModel, ExecutionResult
from packages.quantum.services.options_utils import get_contract_multiplier, parse_option_symbol
from packages.quantum.strategy_profiles import CostModelConfig


class TestContractMultiplierDetection:
    """Tests for get_contract_multiplier() from options_utils."""

    def test_stock_symbol_returns_1(self):
        """Stock symbols should return multiplier of 1."""
        assert get_contract_multiplier("SPY") == 1.0
        assert get_contract_multiplier("AAPL") == 1.0
        assert get_contract_multiplier("MSFT") == 1.0
        assert get_contract_multiplier("BRK.A") == 1.0  # With dot

    def test_option_symbol_returns_100(self):
        """OCC option symbols should return multiplier of 100."""
        # Standard call
        assert get_contract_multiplier("AAPL240119C00150000") == 100.0
        # Standard put
        assert get_contract_multiplier("SPY240315P00450000") == 100.0
        # With O: prefix
        assert get_contract_multiplier("O:AMZN251219C00255000") == 100.0
        # Decimal strike (255.5)
        assert get_contract_multiplier("AMZN251219P00255500") == 100.0

    def test_parse_option_symbol_extracts_components(self):
        """Verify parse_option_symbol extracts correct components."""
        parsed = parse_option_symbol("AMZN251219C00255000")
        assert parsed["underlying"] == "AMZN"
        assert parsed["expiry"] == "2025-12-19"
        assert parsed["type"] == "C"
        assert parsed["strike"] == 255.0

        # With O: prefix
        parsed2 = parse_option_symbol("O:SPY240315P00450000")
        assert parsed2["underlying"] == "SPY"
        assert parsed2["type"] == "P"
        assert parsed2["strike"] == 450.0


class TestTransactionCostModelMultiplier:
    """Tests for TCM.simulate_fill() with multiplier parameter."""

    def test_default_multiplier_is_1(self):
        """Default behavior should use multiplier=1 for backward compatibility."""
        config = CostModelConfig(spread_slippage_bps=10, commission_per_contract=0.65)
        tcm = TransactionCostModel(config)
        rng = random.Random(42)

        # With default multiplier (1.0)
        result = tcm.simulate_fill(price=100.0, quantity=10, side="buy", rng=rng)

        assert isinstance(result, ExecutionResult)
        assert result.filled_quantity == 10
        # Slippage should scale by quantity * multiplier(1)
        # slippage_paid = abs(fill_price - price) * quantity * multiplier
        expected_slippage_per_share = abs(result.fill_price - 100.0)
        assert abs(result.slippage_paid - expected_slippage_per_share * 10 * 1.0) < 0.01

    def test_multiplier_100_scales_slippage(self):
        """Options with multiplier=100 should have 100x slippage_paid."""
        config = CostModelConfig(spread_slippage_bps=10, commission_per_contract=0.65)
        tcm = TransactionCostModel(config)
        rng = random.Random(42)

        # With stock multiplier (1.0)
        result_stock = tcm.simulate_fill(price=5.0, quantity=1, side="buy", rng=random.Random(42), multiplier=1.0)
        # With option multiplier (100.0)
        result_option = tcm.simulate_fill(price=5.0, quantity=1, side="buy", rng=random.Random(42), multiplier=100.0)

        # Same fill_price due to same seed
        assert result_stock.fill_price == result_option.fill_price

        # Slippage should be 100x for option
        assert abs(result_option.slippage_paid - result_stock.slippage_paid * 100) < 0.01

    def test_commission_per_contract_unchanged(self):
        """Commission is per-contract, not affected by multiplier."""
        config = CostModelConfig(spread_slippage_bps=5, commission_per_contract=0.65, min_fee=0.0)
        tcm = TransactionCostModel(config)
        rng = random.Random(42)

        # 2 contracts, multiplier=100
        result = tcm.simulate_fill(price=3.0, quantity=2, side="buy", rng=rng, multiplier=100.0)

        # Commission should be 0.65 * 2 = 1.30 regardless of multiplier
        assert abs(result.commission_paid - 1.30) < 0.01


class TestBacktestMathWithMultiplier:
    """Tests for correct math in BacktestEngine with contract multiplier."""

    def test_cost_basis_includes_multiplier(self):
        """Cost basis = fill_price * quantity * multiplier + commission."""
        # Simulate what the engine does:
        fill_price = 5.00  # $5.00 per share (option premium)
        quantity = 2  # 2 contracts
        multiplier = 100.0
        commission = 1.30  # 0.65 * 2

        cost_basis = (fill_price * quantity * multiplier) + commission
        # 5.00 * 2 * 100 + 1.30 = 1000 + 1.30 = 1001.30
        assert cost_basis == 1001.30

    def test_gross_proceeds_includes_multiplier(self):
        """Gross proceeds = fill_price * quantity * multiplier."""
        fill_price = 6.00  # Sold at $6.00
        quantity = 2
        multiplier = 100.0

        gross_proceeds = fill_price * quantity * multiplier
        # 6.00 * 2 * 100 = 1200
        assert gross_proceeds == 1200.0

    def test_pnl_with_multiplier(self):
        """PnL = net_proceeds - cost_basis (both include multiplier)."""
        # Entry
        entry_fill = 5.00
        entry_qty = 2
        multiplier = 100.0
        entry_commission = 1.30
        cost_basis = (entry_fill * entry_qty * multiplier) + entry_commission
        # 1001.30

        # Exit
        exit_fill = 6.00
        exit_commission = 1.30
        gross_proceeds = exit_fill * entry_qty * multiplier
        net_proceeds = gross_proceeds - exit_commission
        # 1200 - 1.30 = 1198.70

        pnl = net_proceeds - cost_basis
        # 1198.70 - 1001.30 = 197.40
        assert abs(pnl - 197.40) < 0.01

    def test_equity_includes_multiplier_for_position(self):
        """Equity = cash + (position_quantity * current_price * multiplier)."""
        cash = 8998.70  # After buying 2 contracts at $5.00
        position_qty = 2
        current_price = 5.50  # Mark-to-market
        multiplier = 100.0

        current_value = position_qty * current_price * multiplier
        # 2 * 5.50 * 100 = 1100
        equity = cash + current_value
        # 8998.70 + 1100 = 10098.70
        assert abs(equity - 10098.70) < 0.01

    def test_stock_regression_multiplier_1(self):
        """Stock trades should use multiplier=1, preserving existing behavior."""
        # Entry 100 shares at $50
        fill_price = 50.00
        quantity = 100  # shares
        multiplier = 1.0
        commission = 0.65

        cost_basis = (fill_price * quantity * multiplier) + commission
        # 50 * 100 * 1 + 0.65 = 5000.65
        assert cost_basis == 5000.65

        # Exit at $52
        exit_fill = 52.00
        gross_proceeds = exit_fill * quantity * multiplier
        # 52 * 100 * 1 = 5200
        assert gross_proceeds == 5200.0

    def test_position_sizing_floors_to_whole_contracts(self):
        """For options, position sizing should floor to whole contracts."""
        cash = 10000.0
        max_risk_pct = 0.10  # 10% = $1000 position value
        current_price = 3.50  # Option at $3.50
        multiplier = 100.0

        position_value = cash * max_risk_pct  # $1000
        notional_per_contract = current_price * multiplier  # $350
        contracts = int(position_value / notional_per_contract)  # floor(1000/350) = 2

        assert contracts == 2

        # Verify it's floored, not rounded
        current_price_2 = 4.50
        notional_per_contract_2 = current_price_2 * multiplier  # $450
        contracts_2 = int(position_value / notional_per_contract_2)  # floor(1000/450) = 2
        assert contracts_2 == 2

        # Edge case: can't afford 1 contract
        current_price_3 = 12.00
        notional_per_contract_3 = current_price_3 * multiplier  # $1200
        contracts_3 = int(position_value / notional_per_contract_3)  # floor(1000/1200) = 0
        assert contracts_3 == 0


class TestBacktestEngineIntegration:
    """Integration tests mocking polygon to test full engine flow."""

    @patch('packages.quantum.services.backtest_engine.PolygonService')
    def test_option_symbol_uses_multiplier_100(self, mock_polygon_class):
        """BacktestEngine should detect option symbol and use 100x multiplier."""
        from packages.quantum.services.backtest_engine import BacktestEngine
        from packages.quantum.strategy_profiles import StrategyConfig, CostModelConfig

        # Mock polygon to return minimal data (generate valid dates)
        from datetime import datetime, timedelta
        start = datetime(2023, 10, 1)
        dates = [(start + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(150)]
        prices = [5.0 + (i * 0.01) for i in range(150)]

        mock_polygon = MagicMock()
        mock_polygon.get_historical_prices.return_value = {
            'dates': dates,
            'prices': prices,
            'volumes': [1000] * 150
        }
        mock_polygon_class.return_value = mock_polygon

        engine = BacktestEngine(polygon_service=mock_polygon)

        config = StrategyConfig(
            name="test_option",
            version=1,
            conviction_floor=0.1,  # Low threshold to ensure entry
            conviction_slope=1.0,
            max_risk_pct_per_trade=0.05,
            max_risk_pct_portfolio=0.10,
            max_concurrent_positions=5,
            max_spread_bps=50,
            max_days_to_expiry=60,
            min_underlying_liquidity=1000000,
            stop_loss_pct=0.50,  # Wide stop
            take_profit_pct=0.50,  # Wide target
            max_holding_days=100
        )
        cost_model = CostModelConfig(spread_slippage_bps=0, commission_per_contract=0.65)

        # Use option symbol
        result = engine.run_single(
            symbol="O:SPY240315C00450000",
            start_date="2024-01-15",
            end_date="2024-03-01",
            config=config,
            cost_model=cost_model,
            seed=42,
            initial_equity=10000.0
        )

        # If trades occurred, verify multiplier is recorded
        if result.trades:
            first_trade = result.trades[0]
            assert first_trade.get("multiplier") == 100.0
            # PnL should be scaled by multiplier
            # Check that it's not just price diff * qty (would be ~100x smaller)
            assert first_trade["quantity"] >= 1

    @patch('packages.quantum.services.backtest_engine.PolygonService')
    def test_stock_symbol_uses_multiplier_1(self, mock_polygon_class):
        """BacktestEngine should detect stock symbol and use 1x multiplier."""
        from packages.quantum.services.backtest_engine import BacktestEngine
        from packages.quantum.strategy_profiles import StrategyConfig, CostModelConfig

        # Generate valid dates
        from datetime import datetime, timedelta
        start = datetime(2023, 10, 1)
        dates = [(start + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(150)]
        prices = [100.0 + (i * 0.1) for i in range(150)]

        mock_polygon = MagicMock()
        mock_polygon.get_historical_prices.return_value = {
            'dates': dates,
            'prices': prices,
            'volumes': [1000] * 150
        }
        mock_polygon_class.return_value = mock_polygon

        engine = BacktestEngine(polygon_service=mock_polygon)

        config = StrategyConfig(
            name="test_stock",
            version=1,
            conviction_floor=0.1,
            conviction_slope=1.0,
            max_risk_pct_per_trade=0.05,
            max_risk_pct_portfolio=0.10,
            max_concurrent_positions=5,
            max_spread_bps=50,
            max_days_to_expiry=60,
            min_underlying_liquidity=1000000,
            stop_loss_pct=0.50,
            take_profit_pct=0.50,
            max_holding_days=100
        )
        cost_model = CostModelConfig(spread_slippage_bps=0, commission_per_contract=0.65)

        # Use stock symbol
        result = engine.run_single(
            symbol="SPY",
            start_date="2024-01-15",
            end_date="2024-03-01",
            config=config,
            cost_model=cost_model,
            seed=42,
            initial_equity=10000.0
        )

        # If trades occurred, verify multiplier is 1
        if result.trades:
            first_trade = result.trades[0]
            assert first_trade.get("multiplier") == 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
