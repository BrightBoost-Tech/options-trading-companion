import unittest
from packages.quantum.agents.agents.vol_surface_agent import VolSurfaceAgent

class TestVolSurfaceAgent(unittest.TestCase):
    def setUp(self):
        self.agent = VolSurfaceAgent()

    def test_high_iv_rank(self):
        context = {"iv_rank": 75}
        signal = self.agent.evaluate(context)

        self.assertEqual(signal.agent_id, "vol_surface")
        self.assertEqual(signal.score, 100.0)
        self.assertEqual(signal.metadata["vol.bias"], "sell_premium")
        self.assertTrue(signal.metadata["vol.require_defined_risk"])
        self.assertIn("High IV Rank (75.0) detected", signal.reasons)

    def test_low_iv_rank(self):
        context = {"iv_rank": 20}
        signal = self.agent.evaluate(context)

        self.assertEqual(signal.score, 100.0)
        self.assertEqual(signal.metadata["vol.bias"], "buy_premium")
        self.assertFalse(signal.metadata["vol.require_defined_risk"])
        self.assertIn("Low IV Rank (20.0) detected", signal.reasons)

    def test_neutral_iv_rank(self):
        context = {"iv_rank": 45}
        signal = self.agent.evaluate(context)

        self.assertEqual(signal.score, 100.0)
        self.assertEqual(signal.metadata["vol.bias"], "neutral")
        self.assertFalse(signal.metadata["vol.require_defined_risk"])
        self.assertIn("Neutral IV Rank (45.0) detected", signal.reasons)

    def test_boundary_conditions(self):
        # 60 exactly -> sell
        signal_60 = self.agent.evaluate({"iv_rank": 60})
        self.assertEqual(signal_60.metadata["vol.bias"], "sell_premium")

        # 30 exactly -> buy
        signal_30 = self.agent.evaluate({"iv_rank": 30})
        self.assertEqual(signal_30.metadata["vol.bias"], "buy_premium")

    def test_missing_iv_rank(self):
        context = {}
        signal = self.agent.evaluate(context)

        self.assertEqual(signal.score, 50.0)
        self.assertEqual(signal.metadata["vol.bias"], "neutral")
        self.assertIn("Missing iv_rank in context", signal.reasons)

    def test_invalid_iv_rank(self):
        context = {"iv_rank": "not_a_number"}
        signal = self.agent.evaluate(context)

        self.assertEqual(signal.score, 50.0)
        self.assertEqual(signal.metadata["vol.bias"], "neutral")
        self.assertIn("Invalid iv_rank value: not_a_number", signal.reasons)

if __name__ == "__main__":
    unittest.main()
