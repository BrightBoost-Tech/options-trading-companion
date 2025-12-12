import unittest
from unittest.mock import MagicMock
from datetime import datetime, timezone

# Adjust path if needed for import
import sys
import os

from packages.quantum.analytics.drift_auditor import audit_plan_vs_execution

class TestDriftAuditor(unittest.TestCase):
    def setUp(self):
        self.mock_supabase = MagicMock()
        self.user_id = "test_user_123"

    def test_disciplined_execution(self):
        """Case 1: Suggestion matches holding -> disciplined_execution"""

        # Suggestion: Buy 10 AAPL at 150
        suggestion = {
            "id": "sugg_1",
            "symbol": "AAPL",
            "direction": "long",
            "order_json": {"limit_price": 150, "quantity": 10},
            "created_at": datetime.now(timezone.utc).isoformat()
        }

        # Snapshot: 10 AAPL at 151
        snapshot = {
            "holdings": [{
                "symbol": "AAPL",
                "quantity": 10,
                "current_price": 151,
                "current_value": 1510
            }]
        }

        audit_plan_vs_execution(self.user_id, snapshot, [suggestion], self.mock_supabase)

        # Check insert call
        self.mock_supabase.table.assert_called_with("execution_drift_logs")
        self.mock_supabase.table().insert.assert_called()

        args = self.mock_supabase.table().insert.call_args[0][0]
        # args should be a list of logs
        self.assertEqual(len(args), 1)
        log = args[0]
        self.assertEqual(log["tag"], "disciplined_execution")
        self.assertEqual(log["symbol"], "AAPL")

    def test_impulse_trade(self):
        """Case 2: Position exists with no suggestion -> impulse_trade"""

        snapshot = {
            "holdings": [{
                "symbol": "TSLA",
                "quantity": 5,
                "current_price": 200,
                "current_value": 1000
            }]
        }

        # No suggestions
        suggestions = []

        audit_plan_vs_execution(self.user_id, snapshot, suggestions, self.mock_supabase)

        # Check insert call
        args = self.mock_supabase.table().insert.call_args[0][0]
        self.assertEqual(len(args), 1)
        log = args[0]
        self.assertEqual(log["tag"], "impulse_trade")
        self.assertEqual(log["symbol"], "TSLA")

    def test_size_violation(self):
        """Case 3: Position size > threshold vs suggestion -> size_violation"""

        # Suggestion: Buy 10 AAPL (~$1500)
        suggestion = {
            "id": "sugg_2",
            "symbol": "AAPL",
            "direction": "long",
            "order_json": {"limit_price": 150, "quantity": 10},
            "created_at": datetime.now(timezone.utc).isoformat()
        }

        # Snapshot: 30 AAPL (~$4500) -> 3x suggested, > 1.5x threshold
        snapshot = {
            "holdings": [{
                "symbol": "AAPL",
                "quantity": 30,
                "current_price": 150,
                "current_value": 4500
            }]
        }

        audit_plan_vs_execution(self.user_id, snapshot, [suggestion], self.mock_supabase)

        args = self.mock_supabase.table().insert.call_args[0][0]
        self.assertEqual(len(args), 1)
        log = args[0]
        self.assertEqual(log["tag"], "size_violation")
        self.assertEqual(log["details_json"]["actual_size"], 4500)
        self.assertEqual(log["details_json"]["suggested_size"], 1500)

    def test_option_symbol_matching(self):
        """Test matching underlying for options"""

        # Suggestion: SPY Call Spread
        suggestion = {
            "id": "sugg_3",
            "symbol": "SPY",
            "ticker": "SPY 12/20 Call",
            "direction": "long",
            "order_json": {"limit_price": 2.0, "quantity": 1},
        }

        # Holding: Specific Option
        snapshot = {
            "holdings": [{
                "symbol": "O:SPY231220C00450000",
                "quantity": 1,
                "current_price": 2.1,
                "current_value": 210
            }]
        }

        audit_plan_vs_execution(self.user_id, snapshot, [suggestion], self.mock_supabase)

        args = self.mock_supabase.table().insert.call_args[0][0]
        log = args[0]
        self.assertEqual(log["tag"], "disciplined_execution")
        self.assertEqual(log["symbol"], "O:SPY231220C00450000")

if __name__ == '__main__':
    unittest.main()
