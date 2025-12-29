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
        # Base 50.
        # Need Regime > 70 AND Vol > 70 to get 1.25x boost.
        context = {
            "deployable_capital": 2000.0,
            "max_loss_per_contract": 10.0,
            "base_score": 50.0,
            "agent_signals": {
                "regime": {"score": 90.0},
                "vol": {"score": 90.0}
            }
        }
        # Range 20-75.
        # Score 50 -> Factor 0.5.
        # Boost: 0.5 * 1.25 = 0.625.
        # Target = 20 + (55 * 0.625) = 20 + 34.375 = 54.375
        signal = self.agent.evaluate(context)
        target = signal.metadata["constraints"]["sizing.target_risk_usd"]
        self.assertAlmostEqual(target, 54.375, places=1)
        self.assertTrue(signal.score == 50.0)

    def test_confluence_conflict_decreases_risk(self):
        # NOT used in current implementation logic explicitly as "conflict" -> just lack of boost OR penalty.
        # BUT if we have liquidity penalty.
        # Base 90 -> Factor 0.9.
        # Liquidity 25 -> Penalty (25/50) = 0.5x.
        # Factor 0.9 * 0.5 = 0.45.
        context = {
            "deployable_capital": 2000.0,
            "max_loss_per_contract": 10.0,
            "base_score": 90.0,
            "agent_signals": {
                "liquidity": {"score": 25.0}
            }
        }
        # Range 20-75.
        # Target = 20 + (55 * 0.45) = 20 + 24.75 = 44.75
        signal = self.agent.evaluate(context)
        target = signal.metadata["constraints"]["sizing.target_risk_usd"]
        self.assertAlmostEqual(target, 44.75, places=1)

    def test_vol_surface_confluence(self):
        # Verify vol_surface key works.
        context = {
            "deployable_capital": 2000.0,
            "max_loss_per_contract": 10.0,
            "base_score": 50.0,
            "agent_signals": {
                "regime": {"score": 80.0},
                "vol_surface": {"score": 80.0} # Should trigger boost
            }
        }
        # Factor 0.5 * 1.25 = 0.625
        # Target = 20 + (55 * 0.625) = 54.375
        signal = self.agent.evaluate(context)
        target = signal.metadata["constraints"]["sizing.target_risk_usd"]
        self.assertAlmostEqual(target, 54.375, places=1)

    def test_event_risk_reduction(self):
        # Event score < 50 reduces sizing.
        context = {
            "deployable_capital": 2000.0,
            "max_loss_per_contract": 10.0,
            "base_score": 80.0,
            "agent_signals": {
                "event_risk": {"score": 25.0} # 0.5x penalty
            }
        }
        # Factor 0.8 * 0.5 = 0.4
        # Target = 20 + (55 * 0.4) = 20 + 22 = 42.0
        signal = self.agent.evaluate(context)
        target = signal.metadata["constraints"]["sizing.target_risk_usd"]
        self.assertAlmostEqual(target, 42.0, places=1)

    def test_liquidity_reduction(self):
        # Liquidity score < 50 reduces sizing.
        context = {
            "deployable_capital": 2000.0,
            "max_loss_per_contract": 10.0,
            "base_score": 80.0,
            "agent_signals": {
                "liquidity_agent": {"score": 0.4} # Normalized to 40. 40/50 = 0.8x penalty.
            }
        }
        # Factor 0.8 * 0.8 = 0.64
        # Target = 20 + (55 * 0.64) = 20 + 35.2 = 55.2
        signal = self.agent.evaluate(context)
        target = signal.metadata["constraints"]["sizing.target_risk_usd"]
        self.assertAlmostEqual(target, 55.2, places=1)

    def test_normalization(self):
        # Verify 0.8 -> 80
        context = {
            "deployable_capital": 2000.0,
            "max_loss_per_contract": 10.0,
            "base_score": 50.0,
            "agent_signals": {
                "regime": {"score": 0.8}, # 80
                "vol": {"score": 0.9} # 90
            }
        }
        # Both > 70 => Boost 1.25x
        # Factor 0.5 * 1.25 = 0.625
        # Target 54.375
        signal = self.agent.evaluate(context)
        target = signal.metadata["constraints"]["sizing.target_risk_usd"]
        self.assertAlmostEqual(target, 54.375, places=1)

    def test_veto_handling(self):
        # Test generic veto from a watched agent
        context = {
            "deployable_capital": 2000.0,
            "max_loss_per_contract": 10.0,
            "agent_signals": {
                "liquidity": {"score": 20, "veto": True}
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
