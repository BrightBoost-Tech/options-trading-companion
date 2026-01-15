"""
Tests for PR5: Option scoring uses underlying price series.

Verifies:
1. When trading an option, scoring (trend/vol/rsi) uses underlying prices
2. Trade execution and PnL still use option prices
3. Metrics include scoring_symbol and traded_symbol for options
4. Stock mode remains unchanged (scoring uses stock prices)
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from packages.quantum.services.backtest_engine import BacktestEngine, BacktestRunResult
from packages.quantum.strategy_profiles import StrategyConfig, CostModelConfig


def make_test_config(conviction_floor: float = 0.1) -> StrategyConfig:
    """Creates a test StrategyConfig with low conviction floor for easy entry."""
    return StrategyConfig(
        name="test",
        version=1,
        conviction_floor=conviction_floor,
        take_profit_pct=0.10,
        stop_loss_pct=0.05,
        max_holding_days=30,
        max_risk_pct_portfolio=0.20,
        max_concurrent_positions=1,
        conviction_slope=0.2,
        max_risk_pct_per_trade=0.05,
        max_spread_bps=100,
        max_days_to_expiry=45,
        min_underlying_liquidity=1000000.0,
        regime_whitelist=[]
    )


def generate_dates(start: datetime, num_days: int) -> list:
    """Generate a list of date strings."""
    return [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(num_days)]


def generate_trending_up_prices(start: float, num_days: int, daily_gain: float = 0.005) -> list:
    """Generate prices trending upward."""
    prices = [start]
    for _ in range(num_days - 1):
        prices.append(prices[-1] * (1 + daily_gain))
    return prices


def generate_decaying_prices(start: float, num_days: int, daily_decay: float = 0.02) -> list:
    """Generate prices decaying (like option theta decay)."""
    prices = [start]
    for _ in range(num_days - 1):
        prices.append(prices[-1] * (1 - daily_decay))
    return prices


class TestOptionScoringUsesUnderlying:
    """Tests that option backtests use underlying prices for scoring."""

    @patch('packages.quantum.services.backtest_engine.PolygonService')
    def test_option_backtest_fetches_underlying_prices(self, mock_polygon_class):
        """When trading option, engine fetches underlying prices for scoring."""
        mock_polygon = MagicMock()
        mock_polygon_class.return_value = mock_polygon

        start_date = datetime(2024, 1, 1)
        dates = generate_dates(start_date, 100)

        # Option prices: decaying (theta decay)
        option_prices = generate_decaying_prices(5.0, 100, daily_decay=0.01)

        # Underlying prices: trending up
        underlying_prices = generate_trending_up_prices(450.0, 100, daily_gain=0.003)

        def mock_get_historical(symbol, days, to_date):
            if symbol.startswith("O:") or "240" in symbol:  # Option symbol
                return {"dates": dates, "prices": option_prices}
            else:  # Underlying (SPY)
                return {"dates": dates, "prices": underlying_prices}

        mock_polygon.get_historical_prices.side_effect = mock_get_historical

        engine = BacktestEngine(polygon_service=mock_polygon)

        result = engine.run_single(
            symbol="O:SPY240315C00450000",
            start_date="2024-02-01",
            end_date="2024-03-15",
            config=make_test_config(conviction_floor=0.1),
            cost_model=CostModelConfig(),
            seed=42,
            initial_equity=100000.0
        )

        # Verify underlying was fetched
        call_symbols = [call.args[0] for call in mock_polygon.get_historical_prices.call_args_list]
        assert "SPY" in call_symbols, "Should fetch underlying SPY prices for scoring"
        assert any("O:" in s or "240" in s for s in call_symbols), "Should fetch option prices for trading"

    @patch('packages.quantum.services.backtest_engine.PolygonService')
    def test_option_metrics_include_scoring_and_traded_symbols(self, mock_polygon_class):
        """Metrics include scoring_symbol and traded_symbol for options."""
        mock_polygon = MagicMock()
        mock_polygon_class.return_value = mock_polygon

        start_date = datetime(2024, 1, 1)
        dates = generate_dates(start_date, 100)

        option_prices = generate_decaying_prices(5.0, 100, daily_decay=0.005)
        underlying_prices = generate_trending_up_prices(450.0, 100, daily_gain=0.003)

        def mock_get_historical(symbol, days, to_date):
            if symbol.startswith("O:"):
                return {"dates": dates, "prices": option_prices}
            else:
                return {"dates": dates, "prices": underlying_prices}

        mock_polygon.get_historical_prices.side_effect = mock_get_historical

        engine = BacktestEngine(polygon_service=mock_polygon)

        result = engine.run_single(
            symbol="O:SPY240315C00450000",
            start_date="2024-02-01",
            end_date="2024-03-15",
            config=make_test_config(conviction_floor=0.1),
            cost_model=CostModelConfig(),
            seed=42,
            initial_equity=100000.0
        )

        # Check metrics include debug info
        assert result.metrics.get("scoring_symbol") == "SPY"
        assert result.metrics.get("traded_symbol") == "O:SPY240315C00450000"
        assert "underlying_bars" in result.metrics
        assert "option_bars" in result.metrics

    @patch('packages.quantum.services.backtest_engine.PolygonService')
    def test_option_with_underlying_trend_generates_trades(self, mock_polygon_class):
        """Option backtest generates trades when underlying is trending (not decaying option)."""
        mock_polygon = MagicMock()
        mock_polygon_class.return_value = mock_polygon

        start_date = datetime(2024, 1, 1)
        dates = generate_dates(start_date, 100)

        # Option prices: flat/slightly decaying (should NOT generate trend signal alone)
        option_prices = generate_decaying_prices(5.0, 100, daily_decay=0.002)

        # Underlying prices: strong uptrend (SHOULD generate bullish signal)
        underlying_prices = generate_trending_up_prices(450.0, 100, daily_gain=0.005)

        def mock_get_historical(symbol, days, to_date):
            if symbol.startswith("O:"):
                return {"dates": dates, "prices": option_prices}
            else:
                return {"dates": dates, "prices": underlying_prices}

        mock_polygon.get_historical_prices.side_effect = mock_get_historical

        engine = BacktestEngine(polygon_service=mock_polygon)

        result = engine.run_single(
            symbol="O:SPY240315C00450000",
            start_date="2024-02-01",
            end_date="2024-03-15",
            config=make_test_config(conviction_floor=0.1),  # Low threshold
            cost_model=CostModelConfig(),
            seed=42,
            initial_equity=100000.0
        )

        # With underlying uptrend and low conviction floor, should generate trades
        assert result.metrics.get("trades_count", 0) > 0, \
            "Should generate trades when underlying is trending up"

    @patch('packages.quantum.services.backtest_engine.PolygonService')
    def test_stock_mode_unchanged(self, mock_polygon_class):
        """Stock backtest still uses stock prices for scoring (not affected by PR5)."""
        mock_polygon = MagicMock()
        mock_polygon_class.return_value = mock_polygon

        start_date = datetime(2024, 1, 1)
        dates = generate_dates(start_date, 100)
        prices = generate_trending_up_prices(450.0, 100, daily_gain=0.003)

        mock_polygon.get_historical_prices.return_value = {"dates": dates, "prices": prices}

        engine = BacktestEngine(polygon_service=mock_polygon)

        result = engine.run_single(
            symbol="SPY",
            start_date="2024-02-01",
            end_date="2024-03-15",
            config=make_test_config(conviction_floor=0.1),
            cost_model=CostModelConfig(),
            seed=42,
            initial_equity=100000.0
        )

        # Stock mode should NOT have scoring_symbol in metrics
        assert "scoring_symbol" not in result.metrics, \
            "Stock mode should not add scoring_symbol to metrics"

        # Should only fetch one symbol (SPY), not an underlying
        assert mock_polygon.get_historical_prices.call_count == 1


class TestOptionPnLUsesOptionPrices:
    """Tests that trade execution and PnL use option prices (not underlying)."""

    @patch('packages.quantum.services.backtest_engine.PolygonService')
    def test_trade_uses_option_prices_for_pnl(self, mock_polygon_class):
        """Trade entry/exit prices are option prices, not underlying."""
        mock_polygon = MagicMock()
        mock_polygon_class.return_value = mock_polygon

        start_date = datetime(2024, 1, 1)
        dates = generate_dates(start_date, 100)

        # Option prices start at $5, trend to $6 (20% gain)
        option_prices = [5.0 + (i * 0.01) for i in range(100)]

        # Underlying prices (different values, should NOT appear in trades)
        underlying_prices = [450.0 + (i * 0.5) for i in range(100)]

        def mock_get_historical(symbol, days, to_date):
            if symbol.startswith("O:"):
                return {"dates": dates, "prices": option_prices}
            else:
                return {"dates": dates, "prices": underlying_prices}

        mock_polygon.get_historical_prices.side_effect = mock_get_historical

        engine = BacktestEngine(polygon_service=mock_polygon)

        result = engine.run_single(
            symbol="O:SPY240315C00450000",
            start_date="2024-02-01",
            end_date="2024-03-15",
            config=make_test_config(conviction_floor=0.1),
            cost_model=CostModelConfig(),
            seed=42,
            initial_equity=100000.0
        )

        if result.trades:
            trade = result.trades[0]
            # Entry/exit prices should be in option price range (~$5-6), not underlying (~$450)
            assert trade["entry_price"] < 10.0, \
                f"Entry price {trade['entry_price']} should be option price, not underlying"
            assert trade["exit_price"] < 10.0, \
                f"Exit price {trade['exit_price']} should be option price, not underlying"
            # Multiplier should be 100 for options
            assert trade["multiplier"] == 100


class TestExtractUnderlyingSymbol:
    """Tests for extract_underlying_symbol helper."""

    def test_extract_from_occ_with_prefix(self):
        """Extracts underlying from O: prefixed OCC symbol."""
        from packages.quantum.market_data import extract_underlying_symbol

        assert extract_underlying_symbol("O:SPY240315C00450000") == "SPY"
        assert extract_underlying_symbol("O:AAPL240119C00150000") == "AAPL"
        assert extract_underlying_symbol("O:MSFT240621P00400000") == "MSFT"

    def test_extract_from_occ_without_prefix(self):
        """Extracts underlying from OCC symbol without prefix."""
        from packages.quantum.market_data import extract_underlying_symbol

        assert extract_underlying_symbol("SPY240315C00450000") == "SPY"
        assert extract_underlying_symbol("AAPL240119C00150000") == "AAPL"

    def test_extract_returns_input_for_stock(self):
        """Returns input unchanged for stock symbols."""
        from packages.quantum.market_data import extract_underlying_symbol

        assert extract_underlying_symbol("SPY") == "SPY"
        assert extract_underlying_symbol("AAPL") == "AAPL"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
