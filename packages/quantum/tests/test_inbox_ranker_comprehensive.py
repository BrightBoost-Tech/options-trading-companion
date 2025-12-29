import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

# Mock dependencies before import
import sys
sys.modules["packages.quantum.security"] = MagicMock()
sys.modules["packages.quantum.services.journal_service"] = MagicMock()
sys.modules["packages.quantum.analytics.progress_engine"] = MagicMock()
sys.modules["packages.quantum.market_data"] = MagicMock()
sys.modules["packages.quantum.execution.transaction_cost_model"] = MagicMock()
sys.modules["supabase"] = MagicMock()
sys.modules["postgrest.exceptions"] = MagicMock()

# Import ranker directly
from packages.quantum.inbox.ranker import rank_suggestions, calculate_yield_on_risk

class TestInboxRanker(unittest.TestCase):
    def test_calculate_yield_on_risk(self):
        # Case 1: All denoms present, picks max_loss_total
        s1 = {
            "ev": 10.0,
            "sizing_metadata": {
                "max_loss_total": 100.0,
                "capital_required_total": 200.0
            }
        }
        self.assertAlmostEqual(calculate_yield_on_risk(s1), 0.1)

        # Case 2: Fallback to capital_required_total
        s2 = {
            "ev": 20.0,
            "sizing_metadata": {
                "capital_required_total": 50.0
            }
        }
        self.assertAlmostEqual(calculate_yield_on_risk(s2), 0.4)

        # Case 3: Fallback to capital_required
        s3 = {
            "ev": 5.0,
            "sizing_metadata": {
                "capital_required": 25.0
            }
        }
        self.assertAlmostEqual(calculate_yield_on_risk(s3), 0.2)

        # Case 4: Zero EV
        s4 = {"ev": 0.0, "sizing_metadata": {"max_loss_total": 100.0}}
        self.assertAlmostEqual(calculate_yield_on_risk(s4), 0.0)

        # Case 5: Missing Sizing, Fallback denom 1.0
        s5 = {"ev": 7.0}
        self.assertAlmostEqual(calculate_yield_on_risk(s5), 7.0)

        # Case 6: Zero Denom -> 1.0
        s6 = {"ev": 10.0, "sizing_metadata": {"max_loss_total": 0.0}}
        self.assertAlmostEqual(calculate_yield_on_risk(s6), 10.0)

    def test_rank_suggestions_sorting(self):
        s1 = {"id": "A", "ev": 10.0, "sizing_metadata": {"max_loss_total": 100.0}, "created_at": "2023-01-01T10:00:00Z"} # 0.1
        s2 = {"id": "B", "ev": 50.0, "sizing_metadata": {"max_loss_total": 100.0}, "created_at": "2023-01-01T10:00:00Z"} # 0.5

        ranked = rank_suggestions([s1, s2])
        self.assertEqual(ranked[0]["id"], "B")
        self.assertEqual(ranked[1]["id"], "A")

    def test_rank_suggestions_tiebreak(self):
        # Tie break by created_at desc (newer first)
        s1 = {"id": "Old", "ev": 10.0, "sizing_metadata": {"max_loss_total": 100.0}, "created_at": "2023-01-01T10:00:00Z"} # 0.1
        s2 = {"id": "New", "ev": 10.0, "sizing_metadata": {"max_loss_total": 100.0}, "created_at": "2023-01-02T10:00:00Z"} # 0.1

        ranked = rank_suggestions([s1, s2])
        self.assertEqual(ranked[0]["id"], "New")
        self.assertEqual(ranked[1]["id"], "Old")

if __name__ == '__main__':
    unittest.main()
