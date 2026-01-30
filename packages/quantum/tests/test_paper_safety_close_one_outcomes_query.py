"""
Regression test: paper_safety_close_one idempotency query must use
a real column from learning_trade_outcomes_v3 (not "id" which doesn't exist).

The view has columns like closed_at, user_id, is_paper, etc. — but no id.
Using select("id") causes Postgres error 42703.
"""
import asyncio
import unittest
from unittest.mock import MagicMock, patch, call
import sys

# Bypass version check
with patch.dict(sys.modules, {"packages.quantum.check_version": MagicMock()}):
    from packages.quantum.public_tasks import task_paper_safety_close_one
    from packages.quantum.public_tasks_models import PaperSafetyCloseOnePayload


class TestSafetyCloseOutcomesQuery(unittest.TestCase):
    """Regression: idempotency query must select a valid view column."""

    def test_outcomes_query_uses_closed_at_not_id(self):
        """
        The idempotency check on learning_trade_outcomes_v3 must select
        'closed_at' (not 'id') and include limit(1).
        """
        payload = PaperSafetyCloseOnePayload(user_id="test-user-uuid")
        mock_auth = MagicMock()

        # Build a chain mock that records calls
        mock_chain = MagicMock()
        mock_chain.execute.return_value = MagicMock(data=[{"closed_at": "2024-01-10T12:00:00"}])
        for method in ["select", "eq", "neq", "gte", "lt", "in_", "order", "limit"]:
            setattr(mock_chain, method, MagicMock(return_value=mock_chain))

        mock_supabase = MagicMock()
        mock_supabase.table.return_value = mock_chain

        with patch(
            "packages.quantum.public_tasks._check_readiness_hardening_gates",
            return_value=None,
        ), patch(
            "packages.quantum.jobs.handlers.utils.get_admin_client",
            return_value=mock_supabase,
        ):
            result = asyncio.run(
                task_paper_safety_close_one(payload=payload, auth=mock_auth)
            )

        # Verify the function returned (no exception)
        self.assertIsInstance(result, dict)
        self.assertIn("status", result)

        # Find the call to table("learning_trade_outcomes_v3")
        table_calls = mock_supabase.table.call_args_list
        outcomes_table_called = any(
            c == call("learning_trade_outcomes_v3") for c in table_calls
        )
        self.assertTrue(outcomes_table_called, "Expected query to learning_trade_outcomes_v3")

        # Verify select was called with "closed_at" (NOT "id")
        select_calls = mock_chain.select.call_args_list
        select_args = [c.args[0] if c.args else None for c in select_calls]
        self.assertIn("closed_at", select_args, "Expected select('closed_at'), not select('id')")
        self.assertNotIn("id", select_args, "select('id') would fail — view has no id column")

        # Verify limit(1) was called for efficiency
        mock_chain.limit.assert_called_with(1)

        # With one outcome returned, should be "skipped"
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "outcome_exists_today")


if __name__ == "__main__":
    unittest.main()
