import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta

# Mock dependencies before import
import sys
sys.modules["security"] = MagicMock()
sys.modules["security.get_current_user_id"] = MagicMock(return_value="test_user")
sys.modules["security.secrets_provider"] = MagicMock()

# Now import the router and app logic
from strategy_endpoints import router, _run_simulation_job, StrategyConfig, BacktestRequest

def test_strategy_config_model():
    """Verify StrategyConfig model validation."""
    config = StrategyConfig(
        name="TestStrategy",
        version=1,
        description="A test strategy",
        conviction_floor=0.5,
        conviction_slope=1.0,
        max_risk_pct_per_trade=0.02,
        max_risk_pct_portfolio=0.25,
        max_concurrent_positions=5,
        max_spread_bps=20,
        max_days_to_expiry=45,
        min_underlying_liquidity=1000000,
        take_profit_pct=0.5,
        stop_loss_pct=0.5,
        max_holding_days=10
    )
    assert config.name == "TestStrategy"
    # StrategyConfig does NOT have a 'params' dict field.
    # It has direct fields.
    assert config.conviction_floor == 0.5

@patch("strategy_endpoints.get_supabase")
def test_list_strategy_backtests(mock_get_supabase):
    """Test listing backtests."""
    mock_supabase = MagicMock()
    mock_get_supabase.return_value = mock_supabase

    # Setup mock return
    mock_execute = MagicMock()
    mock_execute.data = [
        {"id": "bt_1", "strategy_name": "TestStrat", "win_rate": 0.6, "total_pnl": 100.0}
    ]

    # Mock chain: table().select().eq().eq().order().range().execute()
    mock_supabase.table.return_value \
        .select.return_value \
        .eq.return_value \
        .eq.return_value \
        .order.return_value \
        .range.return_value \
        .execute.return_value = mock_execute

    from strategy_endpoints import list_strategy_backtests

    result = list_strategy_backtests(
        name="TestStrat",
        limit=10,
        offset=0,
        user_id="test_user"
    )

    assert "backtests" in result
    assert len(result["backtests"]) == 1
    assert result["backtests"][0]["id"] == "bt_1"

@patch("strategy_endpoints.get_supabase")
def test_list_recent_backtests(mock_get_supabase):
    mock_supabase = MagicMock()
    mock_get_supabase.return_value = mock_supabase

    mock_execute = MagicMock()
    mock_execute.data = [{"id": "recent_1"}]

    mock_supabase.table.return_value \
        .select.return_value \
        .eq.return_value \
        .order.return_value \
        .limit.return_value \
        .execute.return_value = mock_execute

    from strategy_endpoints import list_recent_backtests

    result = list_recent_backtests(limit=5, user_id="test_user")

    assert "recent_backtests" in result
    assert result["recent_backtests"][0]["id"] == "recent_1"

@patch("strategy_endpoints.get_supabase")
@patch("strategy_endpoints.HistoricalCycleService")
def test_run_simulation_job(mock_service_cls, mock_get_supabase):
    """Test the internal simulation job runner."""
    mock_supabase = MagicMock()
    mock_get_supabase.return_value = mock_supabase

    mock_service = MagicMock()
    mock_service_cls.return_value = mock_service

    # Mock run_cycle to return a trade then stop
    mock_service.run_cycle.side_effect = [
        {"status": "normal_exit", "pnl": 50.0, "nextCursor": "2023-01-05"}, # Trade 1
        {"status": "eof", "nextCursor": "2023-01-05"} # Stop
    ]

    req = BacktestRequest(
        start_date="2023-01-01",
        end_date="2023-01-10",
        ticker="SPY",
        param_grid={}
    )
    config = StrategyConfig(
        name="Test",
        version=1,
        conviction_floor=0.5,
        conviction_slope=1.0,
        max_risk_pct_per_trade=0.02,
        max_risk_pct_portfolio=0.25,
        max_concurrent_positions=5,
        max_spread_bps=20,
        max_days_to_expiry=45,
        min_underlying_liquidity=1000000,
        take_profit_pct=0.5,
        stop_loss_pct=0.5,
        max_holding_days=10
    )

    result = _run_simulation_job(
        user_id="test_user",
        request=req,
        strategy_name="Test",
        config=config
    )

    # Check if insert was called
    mock_supabase.table("strategy_backtests").insert.assert_called()
    args = mock_supabase.table("strategy_backtests").insert.call_args[0][0]

    assert args["strategy_name"] == "Test"
    assert args["win_rate"] == 1.0 # 1 win / 1 trade
    assert args["total_pnl"] == 50.0
