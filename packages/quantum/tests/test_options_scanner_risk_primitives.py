import pytest
import math
from packages.quantum.options_scanner import _compute_risk_primitives_usd

def test_long_call_risk_primitives():
    # legs=[{"premium":1.50,"strike":100,"side":"buy","type":"call"}], total_cost=1.50, current_price=100
    legs = [{"premium": 1.50, "strike": 100.0, "side": "buy", "type": "call"}]
    total_cost = 1.50
    current_price = 100.0

    result = _compute_risk_primitives_usd(legs, total_cost, current_price)

    assert result["max_loss_per_contract"] == 150.0
    assert result["collateral_required_per_contract"] == 150.0
    assert result["max_profit_per_contract"] == float("inf")

def test_debit_call_spread_risk_primitives():
    # debit call spread (buy 100C sell 105C debit 2.00):
    # legs=[buy strike 100 premium 3.00, sell strike 105 premium 1.00], total_cost=+2.00, current_price=100
    # width=5
    # Expect:
    #   max_loss=200
    #   max_profit=(5-2)*100=300
    #   collateral_required=200

    legs = [
        {"premium": 3.00, "strike": 100.0, "side": "buy", "type": "call"},
        {"premium": 1.00, "strike": 105.0, "side": "sell", "type": "call"}
    ]
    total_cost = 2.00
    current_price = 100.0

    result = _compute_risk_primitives_usd(legs, total_cost, current_price)

    assert result["max_loss_per_contract"] == 200.0
    assert result["max_profit_per_contract"] == 300.0
    assert result["collateral_required_per_contract"] == 200.0

def test_credit_put_spread_risk_primitives():
    # credit put spread (sell 100P buy 95P credit 1.25):
    # legs=[sell strike 100 premium 2.00, buy strike 95 premium 0.75], total_cost=-1.25
    # width=5
    # Expect:
    #   max_loss=(5-1.25)*100=375
    #   max_profit=125
    #   collateral_required=500

    legs = [
        {"premium": 2.00, "strike": 100.0, "side": "sell", "type": "put"},
        {"premium": 0.75, "strike": 95.0, "side": "buy", "type": "put"}
    ]
    total_cost = -1.25
    current_price = 100.0

    result = _compute_risk_primitives_usd(legs, total_cost, current_price)

    assert result["max_loss_per_contract"] == 375.0
    assert result["max_profit_per_contract"] == 125.0
    assert result["collateral_required_per_contract"] == 500.0

def test_short_put_risk_primitives():
    # Short put: Sell 100P premium 2.00
    # max_profit = 200
    # max_loss = (100 - 2) * 100 = 9800
    # collateral = 100 * 100 = 10000 (cash secured)

    legs = [{"premium": 2.00, "strike": 100.0, "side": "sell", "type": "put"}]
    total_cost = -2.00
    current_price = 100.0

    result = _compute_risk_primitives_usd(legs, total_cost, current_price)

    assert result["max_profit_per_contract"] == 200.0
    assert result["max_loss_per_contract"] == 9800.0
    assert result["collateral_required_per_contract"] == 10000.0

def test_long_put_risk_primitives():
    # Long put: Buy 100P premium 2.00
    # max_loss = 200
    # max_profit = (100 - 2) * 100 = 9800
    # collateral = 200 (cost)

    legs = [{"premium": 2.00, "strike": 100.0, "side": "buy", "type": "put"}]
    total_cost = 2.00
    current_price = 100.0

    result = _compute_risk_primitives_usd(legs, total_cost, current_price)

    assert result["max_loss_per_contract"] == 200.0
    assert result["max_profit_per_contract"] == 9800.0
    assert result["collateral_required_per_contract"] == 200.0
