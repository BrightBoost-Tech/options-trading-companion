"""
Regression test: paper_safety_close_one must not raise NameError for timedelta.

This test exercises the code path that uses `timedelta` (line ~1329 in public_tasks.py)
to ensure the import is present. The original bug was:
  from datetime import datetime, timezone  # missing timedelta
"""
import asyncio
import unittest
from unittest.mock import MagicMock, patch
import sys

# Bypass version check
with patch.dict(sys.modules, {"packages.quantum.check_version": MagicMock()}):
    from packages.quantum.public_tasks import task_paper_safety_close_one
    from packages.quantum.public_tasks_models import PaperSafetyCloseOnePayload


class TestSafetyCloseTimedelta(unittest.TestCase):
    """Regression: timedelta must be importable in public_tasks.py."""

    def test_no_nameerror_on_timedelta(self):
        """
        Call the safety-close endpoint with mocked gates and DB client.

        The code must reach `today_end = today_start + timedelta(days=1)` without
        raising NameError.
        """
        payload = PaperSafetyCloseOnePayload(user_id="test-user-uuid")
        mock_auth = MagicMock()

        # Mock supabase client to return empty results for all queries
        mock_supabase = MagicMock()
        mock_chain = MagicMock()
        mock_chain.execute.return_value = MagicMock(data=[])
        for method in ["select", "eq", "neq", "gte", "lt", "in_", "order", "limit"]:
            setattr(mock_chain, method, MagicMock(return_value=mock_chain))
        mock_supabase.table.return_value = mock_chain

        with patch(
            "packages.quantum.public_tasks._check_readiness_hardening_gates",
            return_value=None,  # Gates pass
        ), patch(
            "packages.quantum.jobs.handlers.utils.get_admin_client",
            return_value=mock_supabase,
        ):
            # Should not raise NameError: name 'timedelta' is not defined
            result = asyncio.run(
                task_paper_safety_close_one(payload=payload, auth=mock_auth)
            )

        # Should return a dict with status (not an exception)
        self.assertIsInstance(result, dict)
        self.assertIn("status", result)
        # With empty data, expect either skipped or ok (no positions)
        self.assertIn(result["status"], ("skipped", "ok"))


if __name__ == "__main__":
    unittest.main()
