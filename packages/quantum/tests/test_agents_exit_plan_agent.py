import unittest
from packages.quantum.agents.agents.exit_plan_agent import ExitPlanAgent

class TestExitPlanAgent(unittest.TestCase):
    def setUp(self):
        self.agent = ExitPlanAgent()

    def test_credit_strategy_exit_plan(self):
        context = {"strategy_type": "IRON CONDOR"}
        signal = self.agent.evaluate(context)

        self.assertEqual(signal.agent_id, "exit_plan")
        self.assertEqual(signal.score, 100.0)

        # Check new constraints structure
        self.assertIn("constraints", signal.metadata)
        constraints = signal.metadata["constraints"]

        self.assertEqual(constraints["exit.profit_take_pct"], 0.50)
        self.assertEqual(constraints["exit.stop_loss_pct"], 2.00)
        self.assertEqual(constraints["exit.time_stop_days"], 45)
        self.assertIn("Profit Target: 50%", constraints["exit.plan_text"])
        self.assertIn("Stop Loss: 200%", constraints["exit.plan_text"])

    def test_debit_strategy_exit_plan(self):
        context = {"strategy_type": "LONG CALL VERTICAL"}
        signal = self.agent.evaluate(context)

        constraints = signal.metadata["constraints"]
        self.assertEqual(constraints["exit.profit_take_pct"], 0.50)
        self.assertEqual(constraints["exit.stop_loss_pct"], 0.50)
        self.assertEqual(constraints["exit.time_stop_days"], 45)

    def test_long_option_exit_plan(self):
        context = {"strategy_type": "BUY CALL"}
        signal = self.agent.evaluate(context)

        constraints = signal.metadata["constraints"]
        self.assertEqual(constraints["exit.profit_take_pct"], 1.00)
        self.assertEqual(constraints["exit.stop_loss_pct"], 0.50)
        self.assertEqual(constraints["exit.time_stop_days"], 30)

    def test_unknown_strategy_default(self):
        context = {"strategy_type": "MYSTERY STRATEGY"}
        signal = self.agent.evaluate(context)

        # Should default to mapped or fallback? The code defaults to 50/100/30
        constraints = signal.metadata["constraints"]
        self.assertEqual(constraints["exit.profit_take_pct"], 0.50)
        self.assertEqual(constraints["exit.stop_loss_pct"], 1.00)
        self.assertEqual(constraints["exit.time_stop_days"], 30)

        self.assertIn("Unknown strategy", str(signal.reasons))

if __name__ == "__main__":
    unittest.main()
