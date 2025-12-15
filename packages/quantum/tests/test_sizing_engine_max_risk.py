import pytest
from packages.quantum.services.sizing_engine import calculate_sizing

def test_aggressive_sizing_cap():
    """
    Verify that aggressive profile is capped at 5% (0.05).
    """
    # 1. Setup
    buying_power = 10000.0
    # Even if we pass 0.40 (40%), engine should clamp to 0.05 (5%)
    max_risk_pct = 0.40

    # 5% of 10000 is 500
    expected_risk_dollars = 500.0

    max_loss_per_contract = 100.0
    collateral_required_per_contract = 100.0

    # 2. Execute
    result = calculate_sizing(
        account_buying_power=buying_power,
        max_loss_per_contract=max_loss_per_contract,
        collateral_required_per_contract=collateral_required_per_contract,
        max_risk_pct=max_risk_pct,
        profile="AGGRESSIVE"
    )

    # 3. Assert
    # Contracts = floor(500 / 100) = 5
    assert result["contracts"] == 5
    assert result["capital_required"] == 500.0
    assert result["max_dollar_risk"] == 500.0
    assert "Sized for 5.0% risk" in result["reason"]

def test_balanced_sizing_cap():
    """
    Verify that balanced profile is capped at 2% (0.02).
    """
    # 1. Setup
    buying_power = 10000.0
    # Passing 0.10 (10%), should clamp to 0.02 (2%)
    max_risk_pct = 0.10

    # 2% of 10000 is 200
    expected_risk_dollars = 200.0

    max_loss_per_contract = 50.0
    collateral_required_per_contract = 50.0

    # 2. Execute
    result = calculate_sizing(
        account_buying_power=buying_power,
        max_loss_per_contract=max_loss_per_contract,
        collateral_required_per_contract=collateral_required_per_contract,
        max_risk_pct=max_risk_pct,
        profile="balanced"
    )

    # 3. Assert
    # Contracts = floor(200 / 50) = 4
    assert result["contracts"] == 4
    assert result["capital_required"] == 200.0
    assert result["max_dollar_risk"] == 200.0
    assert "Sized for 2.0% risk" in result["reason"]

def test_risk_budget_dollars_override():
    """
    Verify that risk_budget_dollars overrides profile caps.
    """
    # 1. Setup
    buying_power = 10000.0
    risk_budget_dollars = 1000.0 # 10% of equity, well above 2% or 5% caps

    max_loss_per_contract = 100.0
    collateral_required_per_contract = 100.0

    # 2. Execute
    # passing max_risk_pct=0.01 (irrelevant) and profile="balanced" (irrelevant)
    result = calculate_sizing(
        account_buying_power=buying_power,
        max_loss_per_contract=max_loss_per_contract,
        collateral_required_per_contract=collateral_required_per_contract,
        max_risk_pct=0.01,
        profile="balanced",
        risk_budget_dollars=risk_budget_dollars
    )

    # 3. Assert
    # Should use full 1000 dollars
    # Contracts = floor(1000 / 100) = 10
    assert result["contracts"] == 10
    assert result["capital_required"] == 1000.0
    assert result["max_dollar_risk"] == 1000.0
    assert result["risk_budget_dollars"] == 1000.0
    assert "Sized by budget" in result["reason"]

def test_collateral_constraint():
    """
    Verify that collateral limits the position size even if risk budget allows more.
    """
    buying_power = 10000.0
    # Risk budget allows 5 contracts (500 risk / 100 loss)
    # But collateral is high (3000 per contract)

    max_loss_per_contract = 100.0
    collateral_required_per_contract = 3000.0

    result = calculate_sizing(
        account_buying_power=buying_power,
        max_loss_per_contract=max_loss_per_contract,
        collateral_required_per_contract=collateral_required_per_contract,
        max_risk_pct=0.05, # 5% = $500 risk
        profile="AGGRESSIVE"
    )

    # By risk: floor(500 / 100) = 5 contracts
    # By collateral: floor(10000 / 3000) = 3 contracts
    # Final = min(5, 3) = 3

    assert result["contracts"] == 3
    assert result["reason"].endswith("(capped by buying power)")
