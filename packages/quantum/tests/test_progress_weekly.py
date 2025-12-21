
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime
from packages.quantum.dashboard_endpoints import get_weekly_progress

class TestWeeklyProgress(unittest.IsolatedAsyncioTestCase):
    async def test_empty_snapshot(self):
        # Mock Supabase client
        mock_supabase = MagicMock()
        mock_query = MagicMock()
        mock_supabase.table.return_value = mock_query
        mock_query.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.limit.return_value = mock_query

        # Mock execute result -> empty list
        mock_response = MagicMock()
        mock_response.data = []
        mock_query.execute.return_value = mock_response

        # Call function
        result = await get_weekly_progress(user_id="test_user", supabase=mock_supabase)

        # Assertions
        self.assertEqual(result["status"], "empty")
        self.assertEqual(result["user_id"], "test_user")
        self.assertIn("No snapshot yet", result["message"])

    async def test_existing_snapshot(self):
        # Mock Supabase client
        mock_supabase = MagicMock()
        mock_query = MagicMock()
        mock_supabase.table.return_value = mock_query
        mock_query.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.limit.return_value = mock_query

        # Mock execute result -> list with 1 item
        mock_snapshot = {
            "id": "123",
            "user_id": "test_user",
            "week_id": "2025-W01",
            "status": "complete"
        }
        mock_response = MagicMock()
        mock_response.data = [mock_snapshot]
        mock_query.execute.return_value = mock_response

        # Call function
        result = await get_weekly_progress(user_id="test_user", supabase=mock_supabase)

        # Assertions
        self.assertEqual(result, mock_snapshot)

if __name__ == '__main__':
    unittest.main()
