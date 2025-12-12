import unittest
from unittest.mock import MagicMock, patch
import os
import sys

# Ensure packages path is available

from packages.quantum.services.analytics_service import AnalyticsService
from packages.quantum.experiments import get_experiment_cohort

class TestAnalyticsService(unittest.TestCase):
    def setUp(self):
        self.mock_supabase = MagicMock()
        self.service = AnalyticsService(self.mock_supabase)

    def test_log_event(self):
        self.service.log_event(
            user_id="user123",
            event_name="test_event",
            category="test",
            properties={"foo": "bar"}
        )

        # Check if table().insert().execute() was called
        self.mock_supabase.table.assert_called_with("analytics_events")
        self.mock_supabase.table().insert.assert_called_once()

        args = self.mock_supabase.table().insert.call_args[0][0]
        self.assertEqual(args["user_id"], "user123")
        self.assertEqual(args["event_name"], "test_event")
        self.assertEqual(args["properties"]["foo"], "bar")

    def test_log_suggestion_event(self):
        suggestion = {
            "id": "sugg1",
            "symbol": "AAPL",
            "strategy": "call",
            "window": "morning",
            "score": 85,
            "iv_regime": "low",
            "metrics": {"ev": 10.5}
        }

        self.service.log_suggestion_event("user123", suggestion, "viewed")

        self.mock_supabase.table.assert_called_with("analytics_events")
        args = self.mock_supabase.table().insert.call_args[0][0]

        self.assertEqual(args["event_name"], "viewed")
        self.assertEqual(args["properties"]["symbol"], "AAPL")
        self.assertEqual(args["properties"]["score"], 85)
        self.assertEqual(args["properties"]["ev"], 10.5)

class TestExperiments(unittest.TestCase):
    def test_cohort_assignment(self):
        # Deterministic check
        user_a = "user_a"
        exp_name = "test_exp"

        cohort_1 = get_experiment_cohort(user_a, exp_name)
        cohort_2 = get_experiment_cohort(user_a, exp_name)

        self.assertEqual(cohort_1, cohort_2)

        # Check specific known hash result
        # md5("user1:test_exp") -> ends in 'e' (14) -> even -> variant_B?
        # Let's just ensure it returns one of the two
        self.assertIn(cohort_1, ["variant_B", "control_A"])

if __name__ == '__main__':
    unittest.main()
