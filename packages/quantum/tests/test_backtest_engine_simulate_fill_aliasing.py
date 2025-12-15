import sys
import os
import unittest
import random
from unittest.mock import MagicMock

# Add packages/quantum to path so we can import modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from packages.quantum.services.backtest_engine import BacktestEngine
from packages.quantum.strategy_profiles import CostModelConfig
# Import the V3 model directly to verify it matches expectations
from packages.quantum.execution.transaction_cost_model import TransactionCostModel as V3TCM_Direct

class TestBacktestEngineAliasing(unittest.TestCase):
    def test_backtest_engine_simulate_fill_wrapper(self):
        """
        Tests that BacktestEngine._simulate_fill can be called without error,
        proving that the V3TCM aliasing in backtest_engine.py is working.
        """
        # Mock PolygonService to avoid initialization issues
        mock_polygon = MagicMock()
        engine = BacktestEngine(polygon_service=mock_polygon)

        cost_model = CostModelConfig(spread_slippage_bps=5)
        rng = random.Random(123)

        # Call the method on the engine.
        # Note: BacktestEngine._simulate_fill takes (price, side, cost_model, rng)
        # and wraps V3TCM.simulate_fill.
        fill_price = engine._simulate_fill(2.0, "buy", cost_model, rng)

        # Ensure it returns a float and doesn't crash due to NameError or TypeError
        self.assertIsInstance(fill_price, float)
        self.assertGreater(fill_price, 0)

    def test_v3_tcm_explicit_contract(self):
        """
        Verifies the V3 TransactionCostModel logic with the specific parameters
        requested in the task description.
        """
        order = {
            "requested_qty": 1,
            "filled_qty": 0,
            "order_type": "market",
            "side": "buy",
            "requested_price": 2.0,
            "avg_fill_price": 0.0
        }
        quote = {
            "bid_price": 1.9,
            "ask_price": 2.1
        }
        cost_model = CostModelConfig(spread_slippage_bps=5)
        seed_val = 123

        # Call the static method directly
        res = V3TCM_Direct.simulate_fill(order, quote, cost_model, seed=seed_val)

        # Assert returned dict includes keys: status, filled_qty, avg_fill_price
        self.assertIn("status", res)
        self.assertIn("filled_qty", res)
        self.assertIn("avg_fill_price", res)

        # Assert filled_qty == 1 for market order
        self.assertEqual(res["filled_qty"], 1)

if __name__ == '__main__':
    unittest.main()
