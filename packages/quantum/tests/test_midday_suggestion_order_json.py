import pytest
from packages.quantum.services.workflow_orchestrator import build_midday_order_json

def test_midday_order_json_structure():
    """
    Verifies that build_midday_order_json correctly constructs the order_json
    with a 'legs' array, even if the internal_cand is later stripped.
    """
    # 1. Setup mock candidate with 2 legs
    cand = {
        "symbol": "SPY",
        "suggested_entry": 1.25,
        "strategy": "vertical_spread",
        "legs": [
            {"symbol": "O:SPY250101C00500000", "side": "buy"},
            {"symbol": "O:SPY250101C00505000", "side": "sell"}
        ]
    }
    contracts = 3

    # 2. Build order_json
    order_json = build_midday_order_json(cand, contracts)

    # 3. Assertions
    # a) Structure checks
    assert order_json["order_type"] == "multi_leg"
    assert order_json["limit_price"] == 1.25
    assert order_json["contracts"] == 3
    assert order_json["strategy"] == "vertical_spread"

    # b) Leg checks
    assert "legs" in order_json
    legs = order_json["legs"]
    assert len(legs) == 2

    # Check Leg 1
    assert legs[0]["symbol"] == "O:SPY250101C00500000"
    assert legs[0]["side"] == "buy"
    assert legs[0]["quantity"] == 3

    # Check Leg 2
    assert legs[1]["symbol"] == "O:SPY250101C00505000"
    assert legs[1]["side"] == "sell"
    assert legs[1]["quantity"] == 3

def test_single_leg_fallback():
    """
    Verifies that single leg orders are marked correctly.
    """
    cand = {
        "symbol": "AAPL",
        "suggested_entry": 0.50,
        "strategy": "long_call",
        "legs": [
            {"symbol": "O:AAPL250101C00150000", "side": "buy"}
        ]
    }
    contracts = 1

    order_json = build_midday_order_json(cand, contracts)

    assert order_json["order_type"] == "single_leg"
    assert len(order_json["legs"]) == 1
    assert order_json["legs"][0]["quantity"] == 1

def test_no_legs_fallback():
    """
    Verifies behavior when legs are missing (should produce empty legs list).
    """
    cand = {
        "symbol": "MSFT",
        "suggested_entry": 2.00,
        "strategy": "stock",
        "legs": []
    }
    contracts = 10

    order_json = build_midday_order_json(cand, contracts)

    assert order_json["order_type"] == "single_leg" # Logic: len(legs) > 1 -> multi, else single. 0 is not > 1.
    assert len(order_json["legs"]) == 0
