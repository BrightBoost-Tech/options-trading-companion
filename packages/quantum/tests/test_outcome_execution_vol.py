import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime
from packages.quantum.services.outcome_aggregator import OutcomeAggregator
from packages.quantum.market_data import PolygonService

# Mock data for tests
MOCK_EXECUTION_OPTION = {
    "id": "exec-1",
    "symbol": "O:SPY241220C00450000",
    "quantity": 1,
    "fill_price": 5.0,
    "suggestion_id": "sugg-1"
}

MOCK_EXECUTION_EQUITY = {
    "id": "exec-2",
    "symbol": "SPY",
    "quantity": 10,
    "fill_price": 400.0,
    "suggestion_id": "sugg-2"
}

MOCK_PRICES_OPTION = {
    "prices": [5.0, 5.2, 5.1, 5.3, 5.5],
    "returns": [0.04, -0.019, 0.039, 0.037]
}

MOCK_PRICES_UNDERLYING = {
    "prices": [440.0, 442.0, 441.0, 443.0, 445.0],
    "returns": [0.0045, -0.0022, 0.0045, 0.0045]
}

@pytest.fixture
def mock_supabase():
    return MagicMock()

@pytest.fixture
def mock_polygon():
    service = MagicMock(spec=PolygonService)
    return service

def test_execution_vol_option_success(mock_supabase, mock_polygon):
    """
    Test that an option execution correctly computes realized volatility
    by fetching the underlying symbol's history.
    """
    aggregator = OutcomeAggregator(mock_supabase, mock_polygon)

    # Mock Polygon responses
    def side_effect(symbol, days=5):
        # The code requests days=5 for option, days=10 for underlying
        if "O:" in symbol:
            return MOCK_PRICES_OPTION
        else:
            return MOCK_PRICES_UNDERLYING

    mock_polygon.get_historical_prices.side_effect = side_effect

    # Run calculation
    pnl, vol = aggregator._calculate_execution_pnl([MOCK_EXECUTION_OPTION])

    # Verify PnL: (Current 5.5 - Fill 5.0) * 1 * 100 = 50.0
    assert pnl == pytest.approx(50.0)

    # Verify Vol: Should be > 0 because we have underlying data
    assert vol is not None
    assert vol > 0.0

    # Ensure it tried to fetch SPY (underlying) with 10 days
    mock_polygon.get_historical_prices.assert_any_call("SPY", days=10)

def test_execution_vol_equity_success(mock_supabase, mock_polygon):
    """
    Test that an equity execution computes vol directly on the symbol.
    """
    aggregator = OutcomeAggregator(mock_supabase, mock_polygon)

    mock_polygon.get_historical_prices.return_value = MOCK_PRICES_UNDERLYING

    pnl, vol = aggregator._calculate_execution_pnl([MOCK_EXECUTION_EQUITY])

    # PnL: (445 - 400) * 10 = 450
    assert pnl == pytest.approx(450.0)

    # Vol > 0
    assert vol is not None
    assert vol > 0.0

    # Should fetch SPY directly with 10 days for vol (and 5 for pnl logic, but we mocked return)
    # The code calls (sym, 5) then (underlying, 10). Underlying of SPY is SPY.
    # So it calls get_historical_prices twice for SPY.
    # mock_polygon.get_historical_prices.assert_called_with("SPY", days=10) # This checks ONLY last call or strict?
    # assert_called_with checks the LAST call.
    # Since (SPY, 10) is the second call, this should pass.
    mock_polygon.get_historical_prices.assert_called_with("SPY", days=10)

def test_execution_vol_missing_data(mock_supabase, mock_polygon):
    """
    Test fallback when underlying data is missing.
    """
    aggregator = OutcomeAggregator(mock_supabase, mock_polygon)

    # Raise error or return empty for underlying
    def side_effect(symbol, days=5):
        if "O:" in symbol:
            return MOCK_PRICES_OPTION
        raise ValueError("No data")

    mock_polygon.get_historical_prices.side_effect = side_effect

    pnl, vol = aggregator._calculate_execution_pnl([MOCK_EXECUTION_OPTION])

    # PnL still calculates if option data works
    assert pnl == pytest.approx(50.0)

    # Vol should be None
    assert vol is None
