"""
Tests for report_seed_review_v4 job handler.

Tests:
1. Returns expected rows for needs_review entries
2. Respects limit parameter
3. Filters by user_id
4. Handles include_resolved flag
"""

import unittest
from unittest.mock import MagicMock, patch


class TestReportSeedReviewV4Handler(unittest.TestCase):
    """Tests for the report_seed_review_v4 job handler."""

    @patch("packages.quantum.jobs.handlers.report_seed_review_v4._get_supabase_client")
    def test_returns_empty_when_no_needs_review(self, mock_get_client):
        """Returns empty list when no needs_review entries exist."""
        from packages.quantum.jobs.handlers.report_seed_review_v4 import run

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Mock empty query result
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )

        result = run({})

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["rows"], [])
        self.assertIn("No positions requiring review", result["message"])

    @patch("packages.quantum.jobs.handlers.report_seed_review_v4._get_supabase_client")
    def test_returns_expected_rows(self, mock_get_client):
        """Returns enriched rows for needs_review entries."""
        from packages.quantum.jobs.handlers.report_seed_review_v4 import run

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Mock events query
        mock_events = [
            {
                "id": "event-1",
                "user_id": "user-1",
                "group_id": "group-1",
                "leg_id": "leg-1",
                "event_type": "CASH_ADJ",
                "meta_json": {
                    "opening_balance": True,
                    "needs_review": True,
                    "side_inference": {"side_inferred": "default_long"},
                    "note": "Could not determine side"
                },
                "created_at": "2024-01-15T10:00:00Z"
            }
        ]

        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=mock_events
        )

        # Mock open groups check
        mock_client.table.return_value.select.return_value.in_.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"id": "group-1"}]
        )

        # Mock legs query
        mock_client.table.return_value.select.return_value.in_.return_value.execute.side_effect = [
            MagicMock(data=[{
                "id": "leg-1",
                "symbol": "AAPL240119C00150000",
                "side": "LONG",
                "qty_current": 10,
                "underlying": "AAPL"
            }]),
            MagicMock(data=[{
                "id": "group-1",
                "strategy_key": "SEED_V4",
                "status": "OPEN",
                "opened_at": "2024-01-15T10:00:00Z"
            }])
        ]

        result = run({})

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["count"], 1)
        self.assertEqual(len(result["rows"]), 1)

        row = result["rows"][0]
        self.assertEqual(row["user_id"], "user-1")
        self.assertEqual(row["symbol"], "AAPL240119C00150000")
        self.assertEqual(row["inferred_side"], "LONG")
        self.assertEqual(row["group_status"], "OPEN")

    @patch("packages.quantum.jobs.handlers.report_seed_review_v4._get_supabase_client")
    def test_respects_limit_parameter(self, mock_get_client):
        """Respects limit parameter in query."""
        from packages.quantum.jobs.handlers.report_seed_review_v4 import run

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Mock empty result
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )

        run({"limit": 50})

        # Verify limit was applied
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.assert_called_with(50)

    @patch("packages.quantum.jobs.handlers.report_seed_review_v4._get_supabase_client")
    def test_filters_by_user_id(self, mock_get_client):
        """Filters results by user_id when provided."""
        from packages.quantum.jobs.handlers.report_seed_review_v4 import run

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Mock empty result
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )

        run({"user_id": "user-123"})

        # Verify user_id filter was applied (3 eq calls: opening_balance, needs_review, user_id)
        eq_calls = mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.call_args_list
        # The third eq should be for user_id
        self.assertTrue(any("user-123" in str(call) for call in eq_calls))

    @patch("packages.quantum.jobs.handlers.report_seed_review_v4._get_supabase_client")
    def test_caps_limit_at_500(self, mock_get_client):
        """Caps limit at 500 to prevent huge queries."""
        from packages.quantum.jobs.handlers.report_seed_review_v4 import run

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )

        run({"limit": 1000})

        # Verify limit was capped to 500
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.assert_called_with(500)

    @patch("packages.quantum.jobs.handlers.report_seed_review_v4._get_supabase_client")
    def test_returns_error_when_db_unavailable(self, mock_get_client):
        """Returns error when database is unavailable."""
        from packages.quantum.jobs.handlers.report_seed_review_v4 import run

        mock_get_client.return_value = None

        result = run({})

        self.assertEqual(result["status"], "failed")
        self.assertIn("Database unavailable", result["error"])


class TestConvenienceFunction(unittest.TestCase):
    """Tests for the get_needs_review_report convenience function."""

    @patch("packages.quantum.jobs.handlers.report_seed_review_v4._get_supabase_client")
    def test_convenience_function_calls_run(self, mock_get_client):
        """Convenience function properly calls run with payload."""
        from packages.quantum.jobs.handlers.report_seed_review_v4 import get_needs_review_report

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )

        result = get_needs_review_report(user_id="user-1", include_resolved=True, limit=50)

        self.assertEqual(result["status"], "completed")


if __name__ == "__main__":
    unittest.main()
