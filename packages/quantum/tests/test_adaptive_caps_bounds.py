
import unittest
from packages.quantum.services.risk_engine import RiskEngine

class TestAdaptiveCapsBounds(unittest.TestCase):
    def test_apply_adaptive_caps_clamps_bounds(self):
        """
        Test RiskEngine.apply_adaptive_caps clamps bounds when policy max_position_pct is lower.
        base = {"max_position_pct":0.40, "bounds":[(0.0,0.40),(0.0,0.10)]}
        policy = {"max_position_pct":0.20, "ban_structures":[]}
        Expect: adjusted["max_position_pct"]==0.20
        Expect: adjusted["bounds"]==[(0.0,0.20),(0.0,0.10)]
        """
        base = {
            "max_position_pct": 0.40,
            "bounds": [(0.0, 0.40), (0.0, 0.10)]
        }
        policy = {
            "max_position_pct": 0.20,
            "ban_structures": []
        }

        adjusted = RiskEngine.apply_adaptive_caps(policy, base)

        self.assertEqual(adjusted["max_position_pct"], 0.20)
        # Verify bounds are clamped
        # First asset was 0.40, should be clamped to 0.20
        # Second asset was 0.10, should stay 0.10 (since 0.10 < 0.20)
        self.assertEqual(adjusted["bounds"][0], (0.0, 0.20))
        self.assertEqual(adjusted["bounds"][1], (0.0, 0.10))

    def test_apply_adaptive_caps_no_change_if_policy_looser(self):
        """
        If policy is looser (e.g. 0.50) than base (0.40), it should keep base.
        """
        base = {
            "max_position_pct": 0.40,
            "bounds": [(0.0, 0.40)]
        }
        policy = {
            "max_position_pct": 0.50,
            "ban_structures": []
        }

        adjusted = RiskEngine.apply_adaptive_caps(policy, base)

        self.assertEqual(adjusted["max_position_pct"], 0.40)
        self.assertEqual(adjusted["bounds"][0], (0.0, 0.40))

if __name__ == '__main__':
    unittest.main()
