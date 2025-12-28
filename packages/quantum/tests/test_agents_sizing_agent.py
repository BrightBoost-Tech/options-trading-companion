import unittest
from packages.quantum.agents.agents.sizing_agent import SizingAgent
from packages.quantum.agents.core import AgentSignal

class TestSizingAgent(unittest.TestCase):
    def setUp(self):
        self.agent = SizingAgent()

    def test_milestones_small_account(self):
        # < 1000
        context = {
            "deployable_capital": 500.0,
            "max_loss_per_contract": 5.0, # $5 risk
            "base_score": 0.0, # Should hit min risk
        }
        # default min 10, max 35
        signal = self.agent.evaluate(context)
        constraints = signal.metadata["constraints"]

        self.assertEqual(constraints["sizing.min_risk_usd"], 10.0)
        self.assertEqual(constraints["sizing.max_risk_usd"], 35.0)
        self.assertEqual(constraints["sizing.target_risk_usd"], 10.0)
        self.assertEqual(constraints["sizing.recommended_contracts"], 2) # 10 / 5 = 2

    def test_milestones_medium_account(self):
        # 1000 - 5000
        context = {
            "deployable_capital": 2000.0,
            "max_loss_per_contract": 10.0,
            "base_score": 100.0, # Max risk
        }
        # default min 20, max 75
        signal = self.agent.evaluate(context)
        constraints = signal.metadata["constraints"]

        self.assertEqual(constraints["sizing.target_risk_usd"], 75.0)
        self.assertEqual(constraints["sizing.recommended_contracts"], 7) # floor(7.5) = 7

    def test_confluence_increases_risk(self):
        # Base 50, Agent 90 => Avg 70
        context = {
            "deployable_capital": 2000.0,
            "max_loss_per_contract": 10.0,
            "base_score": 50.0,
            "agent_signals": {
                "alpha": {"score": 90.0}
            }
        }
        # Range 20-75.
        # Score 70. Factor 0.7.
        # Target = 20 + (55 * 0.7) = 20 + 38.5 = 58.5
        signal = self.agent.evaluate(context)
        target = signal.metadata["constraints"]["sizing.target_risk_usd"]
        self.assertAlmostEqual(target, 58.5, places=1)
        self.assertTrue(signal.score == 70.0)

    def test_confluence_conflict_decreases_risk(self):
        # Base 90, Agent 10 => Avg 50
        context = {
            "deployable_capital": 2000.0,
            "max_loss_per_contract": 10.0,
            "base_score": 90.0,
            "agent_signals": {
                "alpha": {"score": 10.0}
            }
        }
        # Range 20-75.
        # Score 50. Factor 0.5.
        # Target = 20 + (55 * 0.5) = 20 + 27.5 = 47.5
        signal = self.agent.evaluate(context)
        target = signal.metadata["constraints"]["sizing.target_risk_usd"]
        self.assertAlmostEqual(target, 47.5, places=1)
        self.assertTrue(signal.score == 50.0)

    def test_veto_handling(self):
        context = {
            "deployable_capital": 2000.0,
            "max_loss_per_contract": 10.0,
            "agent_signals": {
                "risk_manager": {"score": 0, "veto": True}
            }
        }
        signal = self.agent.evaluate(context)
        self.assertTrue(signal.veto)
        self.assertEqual(signal.metadata["constraints"]["sizing.recommended_contracts"], 0)

    def test_missing_max_loss(self):
        context = {
            "deployable_capital": 2000.0,
            "max_loss_per_contract": 0.0,
        }
        signal = self.agent.evaluate(context)
        self.assertEqual(signal.metadata["constraints"]["sizing.recommended_contracts"], 1)

    def test_capital_safety_cap(self):
        # Target risk > capital
        # Say capital 100, min risk 50, max 250.
        # Score 100 -> target 250.
        # Should be capped at capital * 0.95 = 95.

        # Actually milestones for <1000 are 10-35.
        # Let's force a scenario or assume very small capital but high min/max config?
        # Or just use logic check.

        # If I have $20 capital. Min/Max 10-35.
        # Score 100 -> Target 35.
        # Cap should be 20 * 0.95 = 19.
        context = {
            "deployable_capital": 20.0,
            "max_loss_per_contract": 5.0,
            "base_score": 100.0
        }
        signal = self.agent.evaluate(context)
        target = signal.metadata["constraints"]["sizing.target_risk_usd"]
        self.assertEqual(target, 19.0)
        self.assertEqual(signal.metadata["constraints"]["sizing.recommended_contracts"], 3) # floor(19/5) = 3

if __name__ == '__main__':
    unittest.main()
