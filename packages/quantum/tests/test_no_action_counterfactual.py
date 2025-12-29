import pytest
from unittest.mock import MagicMock, AsyncMock, ANY
from datetime import datetime, timedelta, timezone
from packages.quantum.services.outcome_aggregator import OutcomeAggregator
from packages.quantum.market_data import PolygonService

# Mock Data
MOCK_SUGGESTION_SINGLE = {
    "id": "s1",
    "ticker": "O:AAPL230616C00150000",
    "direction": "long",
    "order_json": {
        "limit_price": 5.0,
        "contracts": 1
    },
    "created_at": "2023-06-01T14:30:00Z" # Thursday
}

MOCK_SUGGESTION_SPREAD = {
    "id": "s2",
    "ticker": "SPY Vertical",
    "direction": "long", # Overall spread direction
    "order_json": {
        "legs": [
            {"symbol": "O:SPY230616C00400000", "side": "buy", "quantity": 1},
            {"symbol": "O:SPY230616C00405000", "side": "sell", "quantity": 1}
        ]
    },
    "created_at": "2023-06-01T14:30:00Z"
}

MOCK_SUGGESTION_MISSING_TICKER = {
    "id": "s3",
    "ticker": None,
    "created_at": "2023-06-01T14:30:00Z"
}

@pytest.fixture
def aggregator():
    supabase = MagicMock()
    polygon = MagicMock(spec=PolygonService)
    return OutcomeAggregator(supabase, polygon)

def test_single_leg_counterfactual(aggregator):
    # Setup
    # Mock behavior: we have data for Thursday (T) and Friday (T+1)
    aggregator.polygon_service.get_historical_prices.return_value = {
        "prices": [5.0, 6.0], # T, T+1
        "dates": ["2023-06-01", "2023-06-02"]
    }

    # Act
    # Note: _calculate_counterfactual_pnl currently takes a list of suggestions
    pnl, avail = aggregator._calculate_counterfactual_pnl([MOCK_SUGGESTION_SINGLE])

    # Assert
    # Long 1 contract: (6.0 - 5.0) * 100 = 100.0
    assert avail is True
    assert pnl == 100.0

    # Check if to_date was passed correctly (created_at + 5 days)
    # 2023-06-01 + 5 days = 2023-06-06
    expected_to_date = datetime(2023, 6, 6, 14, 30, 0, tzinfo=timezone.utc)
    aggregator.polygon_service.get_historical_prices.assert_called_with("O:AAPL230616C00150000", days=10, to_date=expected_to_date)

def test_spread_counterfactual(aggregator):
    # Setup
    # Mock return values for different calls
    def get_prices(symbol, days=10, to_date=None):
        if symbol == "O:SPY230616C00400000": # Long Leg
            return {"prices": [10.0, 12.0], "dates": ["2023-06-01", "2023-06-02"]} # +2.0 gain
        elif symbol == "O:SPY230616C00405000": # Short Leg
            return {"prices": [8.0, 9.0], "dates": ["2023-06-01", "2023-06-02"]} # +1.0 loss (since short)
        return {}

    aggregator.polygon_service.get_historical_prices.side_effect = get_prices

    # Act
    pnl, avail = aggregator._calculate_counterfactual_pnl([MOCK_SUGGESTION_SPREAD])

    # Assert
    # Long Leg: (12 - 10) * 1 * 100 = +200
    # Short Leg: (9 - 8) * -1 * 100 = -100
    # Net: +100
    assert avail is True
    assert pnl == 100.0

    # Verify calls happened
    aggregator.polygon_service.get_historical_prices.assert_any_call("O:SPY230616C00400000", days=10, to_date=ANY)

def test_missing_data_returns_unavailable(aggregator):
    # Setup
    aggregator.polygon_service.get_historical_prices.return_value = {"prices": [], "dates": []}

    # Act
    pnl, avail = aggregator._calculate_counterfactual_pnl([MOCK_SUGGESTION_SINGLE])

    # Assert
    assert avail is False
    assert pnl == 0.0

def test_malformed_suggestion_handles_gracefully(aggregator):
    pnl, avail = aggregator._calculate_counterfactual_pnl([MOCK_SUGGESTION_MISSING_TICKER])
    assert avail is False
    assert pnl == 0.0
