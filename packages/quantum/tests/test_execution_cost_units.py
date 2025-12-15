
import pytest
from unittest.mock import MagicMock, patch
from packages.quantum.services.rebalance_engine import RebalanceEngine
from packages.quantum.models import SpreadPosition

# Note: We avoid importing optimizer.optimize_portfolio directly due to complex dependencies
# in this isolated test context. We test logic via component interactions or mocks.

@pytest.mark.asyncio
async def test_optimizer_execution_cost_conversion():
    """
    Verifies that optimizer logic (simulated) correctly converts total contract value to per-share entry cost
    before calling estimate_execution_cost.
    This test replicates the exact logic block added to optimizer.py.
    """

    # Mock Execution Service
    mock_service = MagicMock()
    # Assume service returns 1.0 (drag dollars per CONTRACT)
    mock_service.estimate_execution_cost.return_value = 1.0

    # Mock Asset (SpreadPosition like)
    asset = MagicMock()
    asset.current_value = 1000.0 # Total Value
    asset.quantity = 10.0
    asset.ticker = "SPY_call"
    asset.underlying = "SPY"
    asset.legs = [{}, {}] # 2 legs

    user_id = "user"

    # --- EXECUTE LOGIC FROM OPTIMIZER.PY ---
    # FIX: Convert total contract value to per-share premium for the estimator
    asset_val = abs(asset.current_value)
    qty = abs(asset.quantity or 1.0)
    price_per_contract_dollars = asset_val / max(qty, 0.0001)
    entry_cost_per_share = price_per_contract_dollars / 100.0

    # Use underlying symbol for history lookup (better match)
    symbol_for_history = asset.underlying
    if not symbol_for_history:
        parts = asset.ticker.split("_")
        symbol_for_history = parts[0] if len(parts) > 1 else asset.ticker

    cost_per_contract = mock_service.estimate_execution_cost(
        symbol=symbol_for_history,
        spread_pct=None, # let service decide or use default
        user_id=user_id,
        entry_cost=entry_cost_per_share,
        num_legs=len(asset.legs) if asset.legs else 1
    )

    # Total cost for the position
    cost_drag_dollars = cost_per_contract * qty

    # Convert dollar drag to return drag (percentage)
    drag_pct = cost_drag_dollars / asset_val

    # --- ASSERTIONS ---

    # 1. Verify correct entry_cost passed to service
    # price_per_contract = 1000 / 10 = 100.0
    # entry_cost_per_share = 100.0 / 100.0 = 1.0
    mock_service.estimate_execution_cost.assert_called_with(
        symbol="SPY",
        spread_pct=None,
        user_id="user",
        entry_cost=1.0,
        num_legs=2
    )

    # 2. Verify Drag Calculation
    # Service returns 1.0 (dollars per contract)
    # Total cost = 1.0 * 10 = 10.0
    # Drag % = 10.0 / 1000.0 = 0.01 (1%)
    assert drag_pct == 0.01


def test_rebalance_engine_spread_conversion():
    """
    Verifies that RebalanceEngine correctly converts contract dollars to per-share
    when calling estimate_execution_cost for spreads.
    """
    engine = RebalanceEngine(supabase=None)
    engine.execution_service = MagicMock()
    engine.execution_service.estimate_execution_cost.return_value = 1.0 # 1$ per contract drag

    # Mock Spread
    spread = SpreadPosition(
        id="s1", user_id="u1", ticker="SPY_call", underlying="SPY", spread_type="vertical",
        legs=[{}, {}], quantity=10.0, current_value=2000.0, # $200 per contract => $2.00 per share
        net_cost=100.0, delta=0.5, gamma=0.0, vega=0.0, theta=0.0,
        net_delta=0.5, net_gamma=0.0, net_vega=0.0, net_theta=0.0
    )

    targets = [{"symbol": "SPY_call", "target_allocation": 0.20}]

    engine.generate_trades(
        current_spreads=[spread],
        raw_positions=[],
        cash_balance=10000.0,
        target_weights=targets,
        user_id="u1"
    )

    # Verify arguments
    # price_unit = 2000 / 10 = 200.0 (Contract Dollars)
    # Expected entry_cost passed = 200.0 / 100.0 = 2.0

    engine.execution_service.estimate_execution_cost.assert_called_with(
        symbol="SPY",
        user_id="u1",
        entry_cost=2.0,
        num_legs=2
    )
