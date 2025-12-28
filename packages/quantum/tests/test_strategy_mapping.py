
import os
import sys
import unittest
from packages.quantum.analytics.loss_minimizer import LossMinimizer
from packages.quantum.common_enums import StrategyType

class TestStrategyMapping(unittest.TestCase):

    def test_get_strategy_type_canonical(self):
        # Direct match
        self.assertEqual(
            LossMinimizer.get_strategy_type("short_put_credit_spread"),
            StrategyType.SHORT_PUT_CREDIT_SPREAD
        )
        self.assertEqual(
            LossMinimizer.get_strategy_type("iron_condor"),
            StrategyType.IRON_CONDOR
        )

    def test_get_strategy_type_heuristics(self):
        # Loose matching
        self.assertEqual(
            LossMinimizer.get_strategy_type("Credit Put Spread"),
            StrategyType.SHORT_PUT_CREDIT_SPREAD
        )
        self.assertEqual(
            LossMinimizer.get_strategy_type("credit_put_spread"),
            StrategyType.SHORT_PUT_CREDIT_SPREAD
        )
        self.assertEqual(
            LossMinimizer.get_strategy_type("Iron Condor"),
            StrategyType.IRON_CONDOR
        )
        self.assertEqual(
            LossMinimizer.get_strategy_type("ironcondor"),
            StrategyType.IRON_CONDOR
        )
        self.assertEqual(
            LossMinimizer.get_strategy_type("Short Call Credit Spread"),
            StrategyType.SHORT_CALL_CREDIT_SPREAD
        )

    def test_get_strategy_type_unknown(self):
        self.assertEqual(
            LossMinimizer.get_strategy_type("random_strategy"),
            StrategyType.UNKNOWN
        )
        self.assertEqual(
            LossMinimizer.get_strategy_type(""),
            StrategyType.UNKNOWN
        )

if __name__ == "__main__":
    unittest.main()
