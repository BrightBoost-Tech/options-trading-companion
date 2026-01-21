"""
Tests for run_market_hours_ops_v4 orchestrator job handler.

Tests:
1. PREOPEN mode runs marks refresh + seed review
2. INTRADAY mode runs marks refresh only
3. CLOSE mode runs marks refresh with higher caps
4. WEEKEND mode skips marks refresh, runs seed review only
5. Invalid mode returns error
6. Errors in sub-jobs are captured
"""

import unittest
from unittest.mock import MagicMock, patch


class TestMarketHoursOpsV4(unittest.TestCase):
    """Tests for run_market_hours_ops_v4 orchestrator."""

    @patch("packages.quantum.jobs.handlers.run_market_hours_ops_v4.report_seed_review_v4")
    @patch("packages.quantum.jobs.handlers.run_market_hours_ops_v4.refresh_ledger_marks_v4")
    def test_preopen_mode_runs_both_jobs(self, mock_marks, mock_review):
        """PREOPEN mode runs both marks refresh and seed review."""
        from packages.quantum.jobs.handlers.run_market_hours_ops_v4 import run

        # Mock successful results
        mock_marks.run.return_value = {
            "success": True,
            "total_legs_marked": 10,
            "total_groups_updated": 5
        }
        mock_review.run.return_value = {
            "status": "completed",
            "count": 3
        }

        result = run({"mode": "PREOPEN"})

        # Verify both jobs were called
        mock_marks.run.assert_called_once()
        mock_review.run.assert_called_once()

        # Verify marks payload has PREOPEN defaults
        marks_payload = mock_marks.run.call_args[0][0]
        self.assertEqual(marks_payload["source"], "MARKET")
        self.assertEqual(marks_payload["max_symbols_per_user"], 50)
        self.assertEqual(marks_payload["batch_size"], 25)

        # Verify review payload
        review_payload = mock_review.run.call_args[0][0]
        self.assertEqual(review_payload["limit"], 50)
        self.assertFalse(review_payload["include_resolved"])

        self.assertTrue(result["success"])
        self.assertEqual(result["mode"], "PREOPEN")

    @patch("packages.quantum.jobs.handlers.run_market_hours_ops_v4.report_seed_review_v4")
    @patch("packages.quantum.jobs.handlers.run_market_hours_ops_v4.refresh_ledger_marks_v4")
    def test_intraday_mode_skips_seed_review(self, mock_marks, mock_review):
        """INTRADAY mode runs marks refresh only, skips seed review."""
        from packages.quantum.jobs.handlers.run_market_hours_ops_v4 import run

        mock_marks.run.return_value = {
            "success": True,
            "total_legs_marked": 10
        }

        result = run({"mode": "INTRADAY"})

        # Verify marks was called
        mock_marks.run.assert_called_once()

        # Verify seed review was NOT called
        mock_review.run.assert_not_called()

        # Verify result
        self.assertTrue(result["success"])
        self.assertEqual(result["mode"], "INTRADAY")
        self.assertEqual(result["seed_review_result"]["skipped"], True)

    @patch("packages.quantum.jobs.handlers.run_market_hours_ops_v4.report_seed_review_v4")
    @patch("packages.quantum.jobs.handlers.run_market_hours_ops_v4.refresh_ledger_marks_v4")
    def test_close_mode_uses_eod_source(self, mock_marks, mock_review):
        """CLOSE mode uses EOD source and higher caps."""
        from packages.quantum.jobs.handlers.run_market_hours_ops_v4 import run

        mock_marks.run.return_value = {
            "success": True,
            "total_legs_marked": 10
        }

        result = run({"mode": "CLOSE"})

        # Verify marks payload has CLOSE defaults
        marks_payload = mock_marks.run.call_args[0][0]
        self.assertEqual(marks_payload["source"], "EOD")
        self.assertEqual(marks_payload["max_symbols_per_user"], 100)
        self.assertEqual(marks_payload["batch_size"], 50)

        # Seed review not called (include_seed_review=False for CLOSE)
        mock_review.run.assert_not_called()

        self.assertEqual(result["mode"], "CLOSE")

    @patch("packages.quantum.jobs.handlers.run_market_hours_ops_v4.report_seed_review_v4")
    @patch("packages.quantum.jobs.handlers.run_market_hours_ops_v4.refresh_ledger_marks_v4")
    def test_weekend_mode_skips_marks_runs_review(self, mock_marks, mock_review):
        """WEEKEND mode skips marks refresh, runs seed review with include_resolved=True."""
        from packages.quantum.jobs.handlers.run_market_hours_ops_v4 import run

        mock_review.run.return_value = {
            "status": "completed",
            "count": 5
        }

        result = run({"mode": "WEEKEND"})

        # Verify marks was NOT called (market closed)
        mock_marks.run.assert_not_called()

        # Verify seed review WAS called with audit settings
        mock_review.run.assert_called_once()
        review_payload = mock_review.run.call_args[0][0]
        self.assertEqual(review_payload["limit"], 100)
        self.assertTrue(review_payload["include_resolved"])

        # Verify result
        self.assertTrue(result["success"])
        self.assertEqual(result["mode"], "WEEKEND")
        self.assertEqual(result["marks_result"]["skipped"], True)

    @patch("packages.quantum.jobs.handlers.run_market_hours_ops_v4.report_seed_review_v4")
    @patch("packages.quantum.jobs.handlers.run_market_hours_ops_v4.refresh_ledger_marks_v4")
    def test_invalid_mode_returns_error(self, mock_marks, mock_review):
        """Invalid mode returns error without running jobs."""
        from packages.quantum.jobs.handlers.run_market_hours_ops_v4 import run

        result = run({"mode": "INVALID"})

        # No jobs should be called
        mock_marks.run.assert_not_called()
        mock_review.run.assert_not_called()

        self.assertFalse(result["success"])
        self.assertIn("Invalid mode", result["error"])

    @patch("packages.quantum.jobs.handlers.run_market_hours_ops_v4.report_seed_review_v4")
    @patch("packages.quantum.jobs.handlers.run_market_hours_ops_v4.refresh_ledger_marks_v4")
    def test_default_mode_is_intraday(self, mock_marks, mock_review):
        """Default mode is INTRADAY when not specified."""
        from packages.quantum.jobs.handlers.run_market_hours_ops_v4 import run

        mock_marks.run.return_value = {"success": True}

        result = run({})  # No mode specified

        self.assertEqual(result["mode"], "INTRADAY")

    @patch("packages.quantum.jobs.handlers.run_market_hours_ops_v4.report_seed_review_v4")
    @patch("packages.quantum.jobs.handlers.run_market_hours_ops_v4.refresh_ledger_marks_v4")
    def test_marks_error_captured(self, mock_marks, mock_review):
        """Errors from marks refresh are captured in result."""
        from packages.quantum.jobs.handlers.run_market_hours_ops_v4 import run

        mock_marks.run.return_value = {
            "success": False,
            "error": "API rate limit exceeded"
        }

        result = run({"mode": "INTRADAY"})

        self.assertFalse(result["success"])
        self.assertIn("Marks refresh failed", result["errors"][0])

    @patch("packages.quantum.jobs.handlers.run_market_hours_ops_v4.report_seed_review_v4")
    @patch("packages.quantum.jobs.handlers.run_market_hours_ops_v4.refresh_ledger_marks_v4")
    def test_marks_exception_captured(self, mock_marks, mock_review):
        """Exceptions from marks refresh are captured."""
        from packages.quantum.jobs.handlers.run_market_hours_ops_v4 import run

        mock_marks.run.side_effect = Exception("Connection timeout")

        result = run({"mode": "INTRADAY"})

        self.assertFalse(result["success"])
        self.assertIn("Marks refresh exception", result["errors"][0])
        self.assertEqual(result["marks_result"]["success"], False)

    @patch("packages.quantum.jobs.handlers.run_market_hours_ops_v4.report_seed_review_v4")
    @patch("packages.quantum.jobs.handlers.run_market_hours_ops_v4.refresh_ledger_marks_v4")
    def test_review_error_captured(self, mock_marks, mock_review):
        """Errors from seed review are captured in result."""
        from packages.quantum.jobs.handlers.run_market_hours_ops_v4 import run

        mock_marks.run.return_value = {"success": True}
        mock_review.run.return_value = {
            "status": "failed",
            "error": "Database timeout"
        }

        result = run({"mode": "PREOPEN"})

        self.assertFalse(result["success"])
        self.assertIn("Seed review failed", result["errors"][0])

    @patch("packages.quantum.jobs.handlers.run_market_hours_ops_v4.report_seed_review_v4")
    @patch("packages.quantum.jobs.handlers.run_market_hours_ops_v4.refresh_ledger_marks_v4")
    def test_user_id_passed_through(self, mock_marks, mock_review):
        """user_id is passed through to sub-jobs."""
        from packages.quantum.jobs.handlers.run_market_hours_ops_v4 import run

        mock_marks.run.return_value = {"success": True}
        mock_review.run.return_value = {"status": "completed", "count": 0}

        run({"mode": "PREOPEN", "user_id": "user-123"})

        marks_payload = mock_marks.run.call_args[0][0]
        review_payload = mock_review.run.call_args[0][0]

        self.assertEqual(marks_payload["user_id"], "user-123")
        self.assertEqual(review_payload["user_id"], "user-123")

    @patch("packages.quantum.jobs.handlers.run_market_hours_ops_v4.report_seed_review_v4")
    @patch("packages.quantum.jobs.handlers.run_market_hours_ops_v4.refresh_ledger_marks_v4")
    def test_payload_overrides(self, mock_marks, mock_review):
        """Payload values override mode defaults."""
        from packages.quantum.jobs.handlers.run_market_hours_ops_v4 import run

        mock_marks.run.return_value = {"success": True}

        run({
            "mode": "PREOPEN",
            "max_symbols_per_user": 200,
            "batch_size": 100,
            "max_users": 5
        })

        marks_payload = mock_marks.run.call_args[0][0]
        self.assertEqual(marks_payload["max_symbols_per_user"], 200)
        self.assertEqual(marks_payload["batch_size"], 100)
        self.assertEqual(marks_payload["max_users"], 5)


class TestConvenienceFunctions(unittest.TestCase):
    """Tests for mode-specific convenience functions."""

    @patch("packages.quantum.jobs.handlers.run_market_hours_ops_v4.report_seed_review_v4")
    @patch("packages.quantum.jobs.handlers.run_market_hours_ops_v4.refresh_ledger_marks_v4")
    def test_run_preopen(self, mock_marks, mock_review):
        """run_preopen convenience function."""
        from packages.quantum.jobs.handlers.run_market_hours_ops_v4 import run_preopen

        mock_marks.run.return_value = {"success": True}
        mock_review.run.return_value = {"status": "completed"}

        result = run_preopen(max_users=10, user_id="user-1")

        self.assertEqual(result["mode"], "PREOPEN")
        marks_payload = mock_marks.run.call_args[0][0]
        self.assertEqual(marks_payload["max_users"], 10)

    @patch("packages.quantum.jobs.handlers.run_market_hours_ops_v4.report_seed_review_v4")
    @patch("packages.quantum.jobs.handlers.run_market_hours_ops_v4.refresh_ledger_marks_v4")
    def test_run_intraday(self, mock_marks, mock_review):
        """run_intraday convenience function."""
        from packages.quantum.jobs.handlers.run_market_hours_ops_v4 import run_intraday

        mock_marks.run.return_value = {"success": True}

        result = run_intraday()

        self.assertEqual(result["mode"], "INTRADAY")

    @patch("packages.quantum.jobs.handlers.run_market_hours_ops_v4.report_seed_review_v4")
    @patch("packages.quantum.jobs.handlers.run_market_hours_ops_v4.refresh_ledger_marks_v4")
    def test_run_close(self, mock_marks, mock_review):
        """run_close convenience function."""
        from packages.quantum.jobs.handlers.run_market_hours_ops_v4 import run_close

        mock_marks.run.return_value = {"success": True}

        result = run_close()

        self.assertEqual(result["mode"], "CLOSE")

    @patch("packages.quantum.jobs.handlers.run_market_hours_ops_v4.report_seed_review_v4")
    @patch("packages.quantum.jobs.handlers.run_market_hours_ops_v4.refresh_ledger_marks_v4")
    def test_run_weekend(self, mock_marks, mock_review):
        """run_weekend convenience function."""
        from packages.quantum.jobs.handlers.run_market_hours_ops_v4 import run_weekend

        mock_review.run.return_value = {"status": "completed"}

        result = run_weekend(seed_review_limit=200)

        self.assertEqual(result["mode"], "WEEKEND")
        mock_marks.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
