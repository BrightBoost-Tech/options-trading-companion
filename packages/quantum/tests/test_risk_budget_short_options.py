import unittest
import sys
import os

# Ensure packages can be imported
sys.path.append(os.getcwd())

from packages.quantum.services.risk_budget_engine import _risk_usage_usd

class TestRiskBudgetShortOptions(unittest.TestCase):
    def test_long_option(self):
        # long option -> premium risk
        pos = {
            "instrument_type": "option",
            "quantity": 2,
            "side": "buy",
            "cost_basis": 1.50,
            "strike": 100,
            "option_type": "call"
        }
        # Expected: 1.50 * 100 * 2 = 300
        self.assertAlmostEqual(_risk_usage_usd(pos), 300.0)

    def test_short_put_no_explicit_risk(self):
        # short put -> strike risk (approx assignment)
        pos = {
            "instrument_type": "option",
            "quantity": 1,
            "side": "sell",
            "option_type": "put",
            "strike": 100,
            "cost_basis": -1.20
        }
        # Expected: 100 * 100 * 1 = 10000
        self.assertAlmostEqual(_risk_usage_usd(pos), 10000.0)

    def test_short_call_with_underlying(self):
        # short call -> max(underlying, strike) risk
        pos = {
            "instrument_type": "option",
            "quantity": 1,
            "side": "sell",
            "option_type": "call",
            "strike": 100,
            "cost_basis": -1.20
        }
        # Underlying 120 > Strike 100 -> Risk based on 120
        # Expected: 120 * 100 * 1 = 12000
        self.assertAlmostEqual(_risk_usage_usd(pos, underlying_price=120.0), 12000.0)

    def test_short_call_below_strike(self):
        # short call, underlying below strike
        pos = {
            "instrument_type": "option",
            "quantity": 1,
            "side": "sell",
            "option_type": "call",
            "strike": 100,
            "cost_basis": -1.20
        }
        # Underlying 90 < Strike 100 -> Risk based on 100 (conservative floor)
        # Expected: 100 * 100 * 1 = 10000
        self.assertAlmostEqual(_risk_usage_usd(pos, underlying_price=90.0), 10000.0)

    def test_short_call_fallback_no_underlying(self):
        # short call, no underlying provided
        pos = {
            "instrument_type": "option",
            "quantity": 1,
            "side": "sell",
            "option_type": "call",
            "strike": 100,
            "cost_basis": -1.20
        }
        # Fallback to strike
        # Expected: 100 * 100 * 1 = 10000
        self.assertAlmostEqual(_risk_usage_usd(pos, underlying_price=None), 10000.0)

    def test_explicit_max_loss_priority(self):
        # If max_loss provided, use it regardless of other logic
        pos = {
             "instrument_type": "option",
             "quantity": 1,
             "side": "sell",
             "option_type": "put",
             "strike": 100,
             "max_loss_per_contract": 500
        }
        # Expected: 500 * 1 = 500 (spread logic usually provides this)
        self.assertAlmostEqual(_risk_usage_usd(pos), 500.0)

    def test_collateral_priority(self):
        # If collateral provided, use it
        pos = {
             "instrument_type": "option",
             "quantity": 1,
             "side": "sell",
             "option_type": "put",
             "strike": 100,
             "collateral_required_per_contract": 2000
        }
        # Expected: 2000 * 1 = 2000
        self.assertAlmostEqual(_risk_usage_usd(pos), 2000.0)

    def test_quantity_absolute_handling(self):
        # Ensure negative quantity (common in short pos) is treated as positive magnitude
        pos = {
            "instrument_type": "option",
            "quantity": -2,
            "side": "sell",
            "option_type": "put",
            "strike": 50
        }
        # Expected: 50 * 100 * 2 = 10000
        self.assertAlmostEqual(_risk_usage_usd(pos), 10000.0)

if __name__ == '__main__':
    unittest.main()
