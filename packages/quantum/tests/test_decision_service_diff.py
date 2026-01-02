import unittest
from unittest.mock import MagicMock
from datetime import datetime, timedelta, timezone
from packages.quantum.services.decision_service import DecisionService

class TestDecisionServiceDiff(unittest.TestCase):
    def setUp(self):
        self.mock_supabase = MagicMock()
        self.service = DecisionService(self.mock_supabase)

    def test_aggregate_stats(self):
        # Create mock suggestions
        suggestions = [
            {
                "decision_lineage": {
                    "active_constraints": {"max_risk": 0.05, "min_liquidity": 1000},
                    "agents_involved": [{"name": "RiskAgent"}, "TrendAgent"],
                    "strategy_chosen": "DebitSpread",
                    "sizing_source": "Kelly"
                }
            },
            {
                "decision_lineage": {
                    "active_constraints": {"max_risk": 0.05, "sector_limit": "Tech"}, # Same max_risk value
                    "agents_involved": ["RiskAgent"],
                    "strategy_chosen": "DebitSpread",
                    "sizing_source": "Kelly"
                }
            },
            {
                "decision_lineage": {
                    "active_constraints": {"max_risk": 0.10}, # Different value
                    "agents_involved": ["RiskAgent"],
                    "strategy_chosen": "CreditSpread",
                    "sizing_source": "Fixed"
                }
            },
            {
                "decision_lineage": None # Unknown lineage
            }
        ]

        stats = self.service._aggregate_stats(suggestions)

        # Verify sample size
        self.assertEqual(stats["sample_size"], 4)

        # Verify unknown_lineage_pct (1/4 = 25%)
        self.assertEqual(stats["unknown_lineage_pct"], 25.0)

        # Verify active_constraints freq
        # max_risk: 0.05 appears twice. 2/4 = 50.0
        self.assertEqual(stats["active_constraints"]["max_risk: 0.05"], 50.0)
        # max_risk: 0.10 appears once. 1/4 = 25.0
        self.assertEqual(stats["active_constraints"]["max_risk: 0.1"], 25.0)
        # min_liquidity: 1000 appears once. 1/4 = 25.0
        self.assertEqual(stats["active_constraints"]["min_liquidity: 1000"], 25.0)

    def test_calculate_diff(self):
        current_stats = {
            "sample_size": 100,
            "active_constraints": {
                "max_risk: 0.05": 50.0,
                "min_liquidity: 1000": 100.0
            },
            "unique_constraints": ["max_risk: 0.05", "min_liquidity: 1000"],
            "agent_dominance": {"RiskAgent": 80.0},
            "strategy_frequency": {"DebitSpread": 60.0}
        }

        previous_stats = {
            "sample_size": 100,
            "active_constraints": {
                "max_risk: 0.05": 50.0,
                "sector_limit: Tech": 20.0
            },
            "unique_constraints": ["max_risk: 0.05", "sector_limit: Tech"],
            "agent_dominance": {"RiskAgent": 70.0},
            "strategy_frequency": {"DebitSpread": 50.0}
        }

        diff = self.service._calculate_diff(current_stats, previous_stats)

        # Check added/removed
        # "min_liquidity: 1000" is in current (>0) but not previous (0) -> Added
        self.assertIn("min_liquidity: 1000", diff["added_constraints"])

        # "sector_limit: Tech" is in previous (>0) but not current (0) -> Removed
        self.assertIn("sector_limit: Tech", diff["removed_constraints"])

        # Check shifts
        # RiskAgent: 80 - 70 = +10
        self.assertEqual(diff["agent_shifts"]["RiskAgent"], 10.0)

        # Check prevalence
        # min_liquidity: 0 -> 100
        self.assertEqual(diff["constraint_prevalence_shifts"]["min_liquidity: 1000"], 100.0)

if __name__ == '__main__':
    unittest.main()
