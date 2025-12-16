import pytest
from packages.quantum.services.risk_budget_engine import _risk_usage_usd, RiskBudgetEngine

def test_credit_spread_risk():
    """
    Test 1 (credit spread):
    pos = {
      "instrument_type": "option",
      "quantity": 2,
      "max_loss_per_contract": 375.0,
      "cost_basis": -1.25
    }
    Expect _risk_usage_usd(pos) == 750.0
    """
    pos = {
      "instrument_type": "option",
      "quantity": 2,
      "max_loss_per_contract": 375.0,
      "cost_basis": -1.25
    }
    usage = _risk_usage_usd(pos)
    assert usage == 750.0, f"Expected 750.0, got {usage}"

def test_long_option_risk():
    """
    Test 2 (long option):
    pos={"instrument_type":"option","quantity":3,"cost_basis":1.50}
    Expect usage == 1.50*100*3 == 450
    """
    pos = {"instrument_type": "option", "quantity": 3, "cost_basis": 1.50}
    usage = _risk_usage_usd(pos)
    # Note: user example says 1.50*100*3 = 450.
    # float math might be slightly off, but 450.0 should be exact for these numbers.
    assert usage == 450.0, f"Expected 450.0, got {usage}"

def test_collateral_fallback():
    """
    Test 3 (collateral fallback):
    pos={"instrument_type":"option","quantity":1,"collateral_required_per_contract":500.0}
    Expect usage == 500
    """
    pos = {"instrument_type": "option", "quantity": 1, "collateral_required_per_contract": 500.0}
    usage = _risk_usage_usd(pos)
    assert usage == 500.0, f"Expected 500.0, got {usage}"

def test_risk_budget_engine_compute():
    """
    Test that RiskBudgetEngine.compute uses the helper correctly.
    """
    class MockSupabase:
        pass

    engine = RiskBudgetEngine(MockSupabase())

    # 1 option position with defined risk
    # deployable capital 10000
    # pos value: 0 (simplified)
    # risk usage: 750

    pos = {
      "asset_type": "OPTION",
      "quantity": 2,
      "max_loss_per_contract": 375.0,
      "cost_basis": -1.25,
      "current_price": 1.0
    }

    # Total equity = 10000 + (1.0 * 2 * 100) = 10200
    # Normal regime cap = 0.40 * 10200 = 4080
    # Usage = 750
    # Remaining = 4080 - 750 = 3330

    res = engine.compute("user_123", 10000.0, "normal", [pos])

    assert res["current_usage"] == 750.0
    assert res["total_equity"] == 10200.0
    assert res["max_allocation"] == 4080.0
    assert res["remaining"] == 3330.0
