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
    """Tests for the report_seed_review_v4 job handler (legacy path)."""

    @patch("packages.quantum.jobs.handlers.report_seed_review_v4._get_supabase_client")
    def test_returns_empty_when_no_needs_review(self, mock_get_client):
        """Returns empty list when no needs_review entries exist."""
        from packages.quantum.jobs.handlers.report_seed_review_v4 import run

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Mock RPC to fail (test legacy path)
        mock_client.rpc.return_value.execute.side_effect = Exception("RPC not available")

        # Mock empty legacy query result
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )

        result = run({})

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["rows"], [])
        self.assertIn("No positions requiring review", result["message"])
        self.assertEqual(result["source"], "legacy")

    @patch("packages.quantum.jobs.handlers.report_seed_review_v4._get_supabase_client")
    def test_returns_expected_rows_legacy_path(self, mock_get_client):
        """Returns enriched rows for needs_review entries (legacy path)."""
        from packages.quantum.jobs.handlers.report_seed_review_v4 import run

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Mock RPC to fail (test legacy path)
        mock_client.rpc.return_value.execute.side_effect = Exception("RPC not available")

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
        self.assertEqual(result["source"], "legacy")

        row = result["rows"][0]
        self.assertEqual(row["user_id"], "user-1")
        self.assertEqual(row["symbol"], "AAPL240119C00150000")
        self.assertEqual(row["inferred_side"], "LONG")
        self.assertEqual(row["group_status"], "OPEN")

    @patch("packages.quantum.jobs.handlers.report_seed_review_v4._get_supabase_client")
    def test_respects_limit_parameter_legacy(self, mock_get_client):
        """Respects limit parameter in legacy query."""
        from packages.quantum.jobs.handlers.report_seed_review_v4 import run

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Mock RPC to fail (test legacy path)
        mock_client.rpc.return_value.execute.side_effect = Exception("RPC not available")

        # Mock empty result
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )

        run({"limit": 50})

        # Verify limit was applied
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.assert_called_with(50)

    @patch("packages.quantum.jobs.handlers.report_seed_review_v4._get_supabase_client")
    def test_filters_by_user_id_legacy(self, mock_get_client):
        """Filters results by user_id when provided (legacy path)."""
        from packages.quantum.jobs.handlers.report_seed_review_v4 import run

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Mock RPC to fail (test legacy path)
        mock_client.rpc.return_value.execute.side_effect = Exception("RPC not available")

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
    def test_caps_limit_at_500_legacy(self, mock_get_client):
        """Caps limit at 500 to prevent huge queries (legacy path)."""
        from packages.quantum.jobs.handlers.report_seed_review_v4 import run

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Mock RPC to fail (test legacy path)
        mock_client.rpc.return_value.execute.side_effect = Exception("RPC not available")

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

        # Mock RPC to return empty (valid response)
        mock_client.rpc.return_value.execute.return_value = MagicMock(data=[])

        result = get_needs_review_report(user_id="user-1", include_resolved=True, limit=50)

        self.assertEqual(result["status"], "completed")
        # Verify RPC was called with correct params
        mock_client.rpc.assert_called_with("rpc_seed_needs_review_v4", {
            "p_user_id": "user-1",
            "p_include_resolved": True,
            "p_limit": 50
        })


class TestRPCPath(unittest.TestCase):
    """Tests for v1.2 RPC-based query path."""

    @patch("packages.quantum.jobs.handlers.report_seed_review_v4._get_supabase_client")
    def test_rpc_path_invoked_when_available(self, mock_get_client):
        """RPC path is preferred when available and returns data."""
        from packages.quantum.jobs.handlers.report_seed_review_v4 import run

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Mock RPC to return enriched data
        mock_rpc_data = [
            {
                "event_id": "event-1",
                "user_id": "user-1",
                "group_id": "group-1",
                "leg_id": "leg-1",
                "created_at": "2024-01-15T10:00:00Z",
                "symbol": "AAPL240119C00150000",
                "underlying": "AAPL",
                "inferred_side": "LONG",
                "qty_current": 10,
                "group_status": "OPEN",
                "strategy_key": "SEED_V4",
                "opened_at": "2024-01-15T10:00:00Z",
                "side_inference": {"side_inferred": "default_long"},
                "note": "Could not determine side"
            }
        ]

        # Mock RPC call
        mock_client.rpc.return_value.execute.return_value = MagicMock(data=mock_rpc_data)

        result = run({})

        # Verify RPC was called
        mock_client.rpc.assert_called_once_with("rpc_seed_needs_review_v4", {
            "p_include_resolved": False,
            "p_limit": 100
        })

        # Verify result uses RPC source
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["source"], "rpc")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["rows"][0]["event_id"], "event-1")

    @patch("packages.quantum.jobs.handlers.report_seed_review_v4._get_supabase_client")
    def test_rpc_path_with_user_id(self, mock_get_client):
        """RPC path passes user_id parameter correctly."""
        from packages.quantum.jobs.handlers.report_seed_review_v4 import run

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Mock RPC to return empty data
        mock_client.rpc.return_value.execute.return_value = MagicMock(data=[])

        run({"user_id": "user-123", "include_resolved": True, "limit": 50})

        # Verify RPC was called with correct params
        mock_client.rpc.assert_called_once_with("rpc_seed_needs_review_v4", {
            "p_user_id": "user-123",
            "p_include_resolved": True,
            "p_limit": 50
        })

    @patch("packages.quantum.jobs.handlers.report_seed_review_v4._get_supabase_client")
    def test_fallback_to_legacy_when_rpc_fails(self, mock_get_client):
        """Falls back to legacy PostgREST query when RPC fails."""
        from packages.quantum.jobs.handlers.report_seed_review_v4 import run

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Mock RPC to raise exception (RPC not deployed yet)
        mock_client.rpc.return_value.execute.side_effect = Exception("function rpc_seed_needs_review_v4 does not exist")

        # Mock legacy query path
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )

        result = run({})

        # Verify RPC was attempted
        mock_client.rpc.assert_called_once()

        # Verify result uses legacy source
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["source"], "legacy")

    @patch("packages.quantum.jobs.handlers.report_seed_review_v4._get_supabase_client")
    def test_fallback_to_legacy_when_rpc_returns_none(self, mock_get_client):
        """Falls back to legacy query when RPC returns None data."""
        from packages.quantum.jobs.handlers.report_seed_review_v4 import run

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Mock RPC to return None data
        mock_client.rpc.return_value.execute.return_value = MagicMock(data=None)

        # Mock legacy query path
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )

        result = run({})

        # Verify result uses legacy source after fallback
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["source"], "legacy")

    @patch("packages.quantum.jobs.handlers.report_seed_review_v4._get_supabase_client")
    def test_rpc_empty_result_returns_correctly(self, mock_get_client):
        """RPC returning empty list is handled correctly (not treated as failure)."""
        from packages.quantum.jobs.handlers.report_seed_review_v4 import run

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Mock RPC to return empty list (valid response, just no data)
        mock_client.rpc.return_value.execute.return_value = MagicMock(data=[])

        result = run({})

        # Should return success with RPC source (empty list is valid)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["source"], "rpc")
        self.assertEqual(result["count"], 0)
        self.assertIn("No positions requiring review", result["message"])


if __name__ == "__main__":
    unittest.main()
