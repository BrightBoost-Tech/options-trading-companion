import sys
import os
import unittest

# Ensure we can import from packages.quantum
sys.path.append(os.getcwd())

from packages.quantum.options_scanner import _map_single_leg_strategy

class TestSingleLegStrategyMapping(unittest.TestCase):
    def test_buy_call(self):
        leg = {"side": "buy", "type": "call"}
        self.assertEqual(_map_single_leg_strategy(leg), "long_call")

    def test_buy_put(self):
        leg = {"side": "buy", "type": "put"}
        self.assertEqual(_map_single_leg_strategy(leg), "long_put")

    def test_sell_call(self):
        leg = {"side": "sell", "type": "call"}
        self.assertEqual(_map_single_leg_strategy(leg), "short_call")

    def test_sell_put(self):
        leg = {"side": "sell", "type": "put"}
        self.assertEqual(_map_single_leg_strategy(leg), "short_put")

    def test_case_insensitive(self):
        leg = {"side": "BUY", "type": "CALL"}
        self.assertEqual(_map_single_leg_strategy(leg), "long_call")

    def test_invalid(self):
        leg = {"side": "invalid", "type": "call"}
        self.assertIsNone(_map_single_leg_strategy(leg))

        leg = {"side": "buy", "type": "invalid"}
        self.assertIsNone(_map_single_leg_strategy(leg))

        leg = {}
        self.assertIsNone(_map_single_leg_strategy(leg))

if __name__ == "__main__":
    unittest.main()
