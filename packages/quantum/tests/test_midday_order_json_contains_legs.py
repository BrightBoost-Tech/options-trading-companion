from packages.quantum.services.workflow_orchestrator import build_midday_order_json
import pytest

def test_midday_order_json_single_leg():
    cand = {
        "symbol": "AAPL",
        "suggested_entry": 150.0,
        "strategy": "long_call",
        "legs": [
            {"symbol": "AAPL 230519C00150000", "side": "buy"}
        ]
    }
    contracts = 1

    order_json = build_midday_order_json(cand, contracts)

    assert order_json["order_type"] == "single_leg"
    assert order_json["contracts"] == 1
    assert order_json["limit_price"] == 150.0
    assert len(order_json["legs"]) == 1
    assert order_json["legs"][0]["symbol"] == "AAPL 230519C00150000"
    assert order_json["legs"][0]["quantity"] == 1
    assert order_json["underlying"] == "AAPL"

def test_midday_order_json_multi_leg():
    cand = {
        "symbol": "SPY",
        "suggested_entry": 2.50,
        "strategy": "bull_put_spread",
        "legs": [
            {"symbol": "SPY 230519P00400000", "side": "buy"},
            {"symbol": "SPY 230519P00405000", "side": "sell"}
        ]
    }
    contracts = 5

    order_json = build_midday_order_json(cand, contracts)

    assert order_json["order_type"] == "multi_leg"
    assert order_json["contracts"] == 5
    assert len(order_json["legs"]) == 2

    leg1 = order_json["legs"][0]
    assert leg1["symbol"] == "SPY 230519P00400000"
    assert leg1["quantity"] == 5

    leg2 = order_json["legs"][1]
    assert leg2["symbol"] == "SPY 230519P00405000"
    assert leg2["quantity"] == 5

def test_midday_order_json_missing_legs():
    cand = {
        "symbol": "TSLA",
        "suggested_entry": 200.0,
        "strategy": "stock"
    }
    contracts = 10

    order_json = build_midday_order_json(cand, contracts)

    assert order_json["order_type"] == "single_leg" # Or single_leg if legs are empty? Logic says if len(leg_orders) > 1 else "single_leg"
    assert order_json["contracts"] == 10
    assert order_json["legs"] == []
