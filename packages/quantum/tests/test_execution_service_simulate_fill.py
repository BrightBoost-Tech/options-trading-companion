import pytest
from packages.quantum.services.execution_service import ExecutionService

def test_simulate_fill_v3_structure():
    """
    Verifies that simulate_fill returns the expected dictionary structure
    using the V3 Transaction Cost Model logic, without crashing.
    """
    # 1. Initialize Service (no supabase client needed for this method)
    svc = ExecutionService(supabase=None)

    # 2. Call simulate_fill
    # Symbol, Order Type, Price, Quantity, Side, Regime
    out = svc.simulate_fill(
        symbol="O:TEST240119C00100000",
        order_type="limit",
        price=1.00,
        quantity=2,
        side="buy",
        regime="NORMAL"
    )

    # 3. Assertions
    assert isinstance(out, dict)

    # Check required keys
    expected_keys = [
        "status", "filled_quantity", "fill_price", "slippage_paid",
        "commission_paid", "fill_probability", "execution_drag",
        "tcm_version", "quote_used_fallback"
    ]
    for k in expected_keys:
        assert k in out, f"Missing key: {k}"

    # Check values
    assert out["filled_quantity"] == 2
    assert out["status"] == "simulated"
    assert out["quote_used_fallback"] is True

    # Check numeric properties
    assert out["execution_drag"] >= 0
    assert 0.0 <= out["fill_probability"] <= 1.0
    assert out["fill_price"] > 0

    # Check that execution drag sums correctly
    # drag = slippage + fees + spread_cost (internal to estimate)
    # Note: simulate_fill returns:
    # execution_drag = expected_spread_cost_usd + expected_slippage_usd + fees_usd
    # slippage_paid = expected_slippage_usd
    # commission_paid = fees_usd

    # So execution_drag >= slippage_paid + commission_paid
    assert out["execution_drag"] >= out["slippage_paid"] + out["commission_paid"]

def test_simulate_fill_shock_regime():
    """
    Verifies behavior in SHOCK regime (conservative model).
    """
    svc = ExecutionService(supabase=None)

    out = svc.simulate_fill(
        symbol="O:SHOCK240119P00100000",
        order_type="market",
        price=2.00,
        quantity=1,
        side="sell",
        regime="SHOCK"
    )

    # In SHOCK regime, spread is wider (0.02) and model is conservative
    assert out["execution_drag"] > 0
    assert out["fill_probability"] <= 1.0 # Should be conservative, possibly < 1.0 if not market?
    # For market order, fill prob is 1.0 usually, but let's check config propagation
    # actually V3TCM.estimate returns fill_prob=1.0 for market orders even in conservative mode?
    # Let's check V3TCM logic:
    # if market: fill_prob = 1.0
    # then adjust: if conservative: fill_prob *= 0.8 => 0.8

    assert out["fill_probability"] == 0.8
