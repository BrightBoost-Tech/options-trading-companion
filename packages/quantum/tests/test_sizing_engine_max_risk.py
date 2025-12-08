import pytest
from packages.quantum.services.sizing_engine import calculate_sizing

def test_calculate_sizing_aggressive_profile():
    """
    Test that 'AGGRESSIVE' profile uses 40% max risk.
    Scenario:
    - Buying power: 1000
    - Contract ask: 1.0 (Risk per contract = 1.0 * 100 = 100)
    - Profile: AGGRESSIVE (max_risk_pct = 0.40)

    Calculation:
    - Max dollar risk = 1000 * 0.40 = 400
    - Contracts = floor(400 / 100) = 4
    """
    buying_power = 1000.0
    contract_ask = 1.0
    ev_per_contract = 50.0 # dummy

    result = calculate_sizing(
        account_buying_power=buying_power,
        ev_per_contract=ev_per_contract,
        contract_ask=contract_ask,
        max_risk_pct=0.05, # Passed default, should be overridden
        profile="AGGRESSIVE"
    )

    # Expected contracts = 4
    assert result["contracts"] == 4, f"Expected 4 contracts, got {result['contracts']}. Reason: {result['reason']}"
    assert result["capital_required"] == 400.0

def test_calculate_sizing_balanced_profile():
    """
    Test that 'balanced' profile respects the passed max_risk_pct or defaults.
    Scenario:
    - Buying power: 1000
    - Contract ask: 1.0 (Risk per contract = 100)
    - Profile: balanced
    - max_risk_pct: 0.05 (Default in signature, but we pass it explicitly or rely on default)

    Calculation:
    - Max dollar risk = 1000 * 0.05 = 50
    - Contracts = floor(50 / 100) = 0
    """
    buying_power = 1000.0
    contract_ask = 1.0

    result = calculate_sizing(
        account_buying_power=buying_power,
        ev_per_contract=50.0,
        contract_ask=contract_ask,
        max_risk_pct=0.05,
        profile="balanced"
    )

    # Expected contracts = 0 because 50 < 100
    assert result["contracts"] == 0, f"Expected 0 contracts, got {result['contracts']}"

def test_calculate_sizing_explicit_risk_override():
    """
    Test that if we pass 0.40 but profile is NOT aggressive, it uses passed value?
    Actually the implementation sets default max_risk_pct=0.05 in header.
    But calls can pass override.
    However, if profile is AGGRESSIVE, it OVERRIDES whatever is passed.

    Let's test passing 0.10 with balanced.
    """
    buying_power = 1000.0
    contract_ask = 1.0

    result = calculate_sizing(
        account_buying_power=buying_power,
        ev_per_contract=50.0,
        contract_ask=contract_ask,
        max_risk_pct=0.10,
        profile="balanced"
    )

    # Max risk = 100. Contracts = 100 / 100 = 1
    assert result["contracts"] == 1
