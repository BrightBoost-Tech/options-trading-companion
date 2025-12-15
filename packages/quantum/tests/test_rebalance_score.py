
import pytest
from unittest.mock import MagicMock
from packages.quantum.services.rebalance_engine import RebalanceEngine
from packages.quantum.models import SpreadPosition
from datetime import datetime, timezone

def test_rebalance_engine_no_fake_ev():
    """
    Ensures that RebalanceEngine does not calculate a fake EV
    and instead uses RebalanceScore logic.
    """
    engine = RebalanceEngine(supabase=None)

    # Mock Inputs
    spread = SpreadPosition(
        id="test-id",
        user_id="test-user",
        ticker="SPY",
        underlying="SPY",
        spread_type="debit_call", # fixed literal
        legs=[],
        quantity=1.0,
        current_value=1000.0,
        net_cost=900.0, # required
        delta=0.5, # required alias for net_delta
        gamma=0.01,
        vega=10.0,
        theta=-5.0,
        net_delta=0.5, # pydantic model might map fields, but let's provide required ones
        net_gamma=0.01,
        net_vega=10.0,
        net_theta=-5.0
    )

    current_spreads = [spread]
    raw_positions = [{"symbol": "SPY", "current_value": 1000.0, "quantity": 1.0}]
    cash = 10000.0

    # Target: Increase SPY to 20%
    # Portfolio value = 11000. 20% = 2200. Diff = 1200.
    targets = [{"symbol": "SPY", "target_allocation": 0.20}]

    conviction_map = {"SPY": 0.8} # High conviction
    regime_context = {"current_regime": "normal"}

    trades = engine.generate_trades(
        current_spreads=current_spreads,
        raw_positions=raw_positions,
        cash_balance=cash,
        target_weights=targets,
        conviction_map=conviction_map,
        regime_context=regime_context,
        user_id="test_user"
    )

    assert len(trades) == 1
    trade = trades[0]

    # Assertions
    assert trade["symbol"] == "SPY"
    assert trade["side"] == "increase"

    # CHECK: EV MUST BE NONE (No fake EV)
    assert trade["ev"] is None

    # CHECK: Rebalance Score presence
    assert "rebalance_score" in trade
    assert "score_components" in trade
    assert trade["score"] == trade["rebalance_score"]

    # Verify logic:
    # Score = Conviction(0.8)*100 - Cost - Regime
    # Cost (fallback) = 0.05 / Price (approx 1000/1 = 1000 per unit?)
    # Price unit is current_value/qty = 1000/1 = 1000.
    # Cost ROI = 0.05 / 1000 = 0.00005 (negligible)
    # Regime penalty = 0 (normal)
    # Risk penalty = 0 (target 0.20 is not > 0.20)

    score = trade["rebalance_score"]
    assert score > 75.0 # Should be close to 80
    assert score <= 80.0

def test_rebalance_score_cost_sensitivity():
    """
    Verifies that higher execution cost lowers the score.
    """
    engine = RebalanceEngine(supabase=None)

    # Mock Execution Service inside engine to control cost
    mock_exec_service = MagicMock()
    engine.execution_service = mock_exec_service

    # Scenario 1: Low Cost
    mock_exec_service.estimate_execution_cost.return_value = 0.05 # 5 cents

    # SpreadPosition required fields
    spread_args = dict(
        id="test-abc",
        user_id="user",
        ticker="ABC",
        underlying="ABC",
        spread_type="other", # 'stock' not valid, using 'other'
        legs=[],
        quantity=1.0,
        current_value=100.0,
        net_cost=90.0,
        delta=1.0,
        gamma=0.0,
        vega=0.0,
        theta=0.0,
        net_delta=1.0,
        net_gamma=0.0,
        net_vega=0.0,
        net_theta=0.0
    )
    spread = SpreadPosition(**spread_args)

    raw_positions = [{"symbol": "ABC", "current_value": 100.0, "current_price": 100.0}]
    cash = 1000.0
    targets = [{"symbol": "ABC", "target_allocation": 0.20}] # Buy more

    # Run 1
    trades1 = engine.generate_trades(
        current_spreads=[spread],
        raw_positions=raw_positions,
        cash_balance=cash,
        target_weights=targets,
        conviction_map={"ABC": 0.8}
    )
    score1 = trades1[0]["rebalance_score"]

    # Scenario 2: High Cost
    mock_exec_service.estimate_execution_cost.return_value = 5.0 # $5.00 cost per share (huge spread)

    # Run 2
    trades2 = engine.generate_trades(
        current_spreads=[spread],
        raw_positions=raw_positions,
        cash_balance=cash,
        target_weights=targets,
        conviction_map={"ABC": 0.8}
    )
    score2 = trades2[0]["rebalance_score"]

    print(f"Score1 (Low Cost): {score1}, Score2 (High Cost): {score2}")

    assert score1 > score2

    # Check penalty calculation
    # Cost ROI 1: 0.05 / 100 = 0.0005. Penalty = 0.0005 * 500 = 0.25 points. Score ~ 79.75.
    # Cost ROI 2: 5.0 / 100 = 0.05. Penalty = 0.05 * 500 = 25 points. Score ~ 55.

    assert score1 > 79.0
    assert score2 < 60.0

def test_rebalance_score_regime_penalty():
    """
    Verifies that PANIC regime adds penalty.
    """
    engine = RebalanceEngine(supabase=None)

    spread_args = dict(
        id="test-spy",
        user_id="user",
        ticker="SPY",
        underlying="SPY",
        spread_type="other",
        legs=[],
        quantity=1.0,
        current_value=100.0,
        net_cost=90.0,
        delta=1.0,
        gamma=0.0,
        vega=0.0,
        theta=0.0,
        net_delta=1.0,
        net_gamma=0.0,
        net_vega=0.0,
        net_theta=0.0
    )
    spread = SpreadPosition(**spread_args)

    raw_positions = [{"symbol": "SPY", "current_value": 100.0, "current_price": 100.0}]
    targets = [{"symbol": "SPY", "target_allocation": 0.20}] # Buy

    # Run Normal
    trades_norm = engine.generate_trades(
        current_spreads=[spread],
        raw_positions=raw_positions,
        cash_balance=1000.0,
        target_weights=targets,
        conviction_map={"SPY": 0.5},
        regime_context={"current_regime": "normal"}
    )

    # Run Panic
    trades_panic = engine.generate_trades(
        current_spreads=[spread],
        raw_positions=raw_positions,
        cash_balance=1000.0,
        target_weights=targets,
        conviction_map={"SPY": 0.5},
        regime_context={"current_regime": "panic"}
    )

    assert trades_norm[0]["rebalance_score"] > trades_panic[0]["rebalance_score"]
    # Panic penalty is 15.0
    assert abs((trades_norm[0]["rebalance_score"] - trades_panic[0]["rebalance_score"]) - 15.0) < 1.0


def test_rebalance_engine_stock_no_exec_call():
    """
    Verifies that RebalanceEngine uses STOCK_SPREAD_BPS for stocks
    and does NOT call estimate_execution_cost.
    """
    engine = RebalanceEngine(supabase=None)
    engine.execution_service = MagicMock()

    # Mock Stock Position
    raw_positions = [{
        "symbol": "AAPL",
        "current_value": 1500.0,
        "current_price": 150.0,
        "quantity": 10
    }]
    current_spreads = [] # No spreads
    cash = 10000.0
    targets = [{"symbol": "AAPL", "target_allocation": 0.20}]

    # Execute
    trades = engine.generate_trades(
        current_spreads=current_spreads,
        raw_positions=raw_positions,
        cash_balance=cash,
        target_weights=targets,
        user_id="test_user"
    )

    # Assert estimate_execution_cost was NOT called for AAPL
    engine.execution_service.estimate_execution_cost.assert_not_called()

    # Verify score calculation used the stock logic
    # Stock Logic:
    # stock_spread_pct = 5 / 10000 = 0.0005
    # exec_cost_per_unit = 150.0 * 0.0005 * 0.5 = 0.0375
    # cost_roi = 0.0375 / 150.0 = 0.00025
    # penalty = 0.00025 * 500 = 0.125

    trade = trades[0]
    components = trade["score_components"]
    assert abs(components["execution_cost_penalty"] - 0.125) < 0.0001
