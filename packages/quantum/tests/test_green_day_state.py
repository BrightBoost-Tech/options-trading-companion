"""
Tests for paper green day evaluation in GoLiveValidationService.

Verifies:
1. Positive realized day increments paper_green_days once
2. Zero/negative day does not increment
3. Rerun same day is idempotent (no double-count)
4. Chicago date boundaries behave correctly (CST/CDT)
5. Existing readiness behavior (paper_consecutive_passes) is unaffected
"""

import unittest
from unittest.mock import MagicMock, patch
import sys

# Bypass version check
with patch.dict(sys.modules, {"packages.quantum.check_version": MagicMock()}):
    from packages.quantum.services.go_live_validation_service import (
        GoLiveValidationService,
        chicago_day_window_utc,
    )
from datetime import datetime, timezone, timedelta


def _make_state(
    user_id="test-user-uuid",
    paper_green_days=0,
    paper_last_green_day_date=None,
    paper_last_daily_realized_pnl=None,
    paper_last_green_day_evaluated_at=None,
    paper_consecutive_passes=5,
    paper_ready=False,
):
    """Build a minimal v3_go_live_state dict with green day fields."""
    return {
        "user_id": user_id,
        "paper_window_start": "2024-01-01T00:00:00+00:00",
        "paper_window_end": "2024-01-22T00:00:00+00:00",
        "paper_baseline_capital": 100000,
        "paper_consecutive_passes": paper_consecutive_passes,
        "paper_ready": paper_ready,
        "paper_streak_days": 0,
        "paper_last_checkpoint_at": None,
        "paper_checkpoint_window_days": 14,
        "paper_green_days": paper_green_days,
        "paper_last_green_day_date": paper_last_green_day_date,
        "paper_last_daily_realized_pnl": paper_last_daily_realized_pnl,
        "paper_last_green_day_evaluated_at": paper_last_green_day_evaluated_at,
    }


def _make_chain_mock():
    """Create a chainable Supabase query mock."""
    chain = MagicMock()
    chain.execute.return_value = MagicMock(data=None)
    for method in ["select", "eq", "neq", "gte", "lt", "lte", "in_", "order",
                    "limit", "single", "update", "insert"]:
        setattr(chain, method, MagicMock(return_value=chain))
    return chain


class TestGreenDayPositiveDay(unittest.TestCase):
    """Positive realized day increments paper_green_days once."""

    def setUp(self):
        self.mock_client = MagicMock()
        self.service = GoLiveValidationService(self.mock_client)
        self.user_id = "test-user-uuid"

    def test_positive_pnl_increments_green_days(self):
        """A day with positive realized PnL should increment paper_green_days."""
        state = _make_state(paper_green_days=3)

        self.service.get_or_create_state = MagicMock(return_value=state)
        self.service._fetch_paper_daily_realized_pnl = MagicMock(return_value=150.0)

        update_chain = _make_chain_mock()
        self.mock_client.table = MagicMock(return_value=update_chain)

        # Wednesday Jan 10, 2024, 20:00 UTC = 2:00 PM Chicago CST
        now = datetime(2024, 1, 10, 20, 0, 0, tzinfo=timezone.utc)
        result = self.service.eval_paper_green_day(self.user_id, now=now)

        self.assertTrue(result["green_day"])
        self.assertEqual(result["paper_green_days"], 4)
        self.assertEqual(result["daily_realized_pnl"], 150.0)
        self.assertEqual(result["evaluated_trading_date"], "2024-01-10")
        self.assertEqual(result["paper_last_green_day_date"], "2024-01-10")
        self.assertFalse(result["already_evaluated"])


class TestGreenDayNonPositiveDay(unittest.TestCase):
    """Zero/negative day does not increment."""

    def setUp(self):
        self.mock_client = MagicMock()
        self.service = GoLiveValidationService(self.mock_client)
        self.user_id = "test-user-uuid"

    def test_zero_pnl_no_increment(self):
        """Zero P&L should not increment paper_green_days."""
        state = _make_state(paper_green_days=3)

        self.service.get_or_create_state = MagicMock(return_value=state)
        self.service._fetch_paper_daily_realized_pnl = MagicMock(return_value=0.0)

        update_chain = _make_chain_mock()
        self.mock_client.table = MagicMock(return_value=update_chain)

        now = datetime(2024, 1, 10, 20, 0, 0, tzinfo=timezone.utc)
        result = self.service.eval_paper_green_day(self.user_id, now=now)

        self.assertFalse(result["green_day"])
        self.assertEqual(result["paper_green_days"], 3)  # unchanged

    def test_negative_pnl_no_increment(self):
        """Negative P&L should not increment paper_green_days."""
        state = _make_state(paper_green_days=5)

        self.service.get_or_create_state = MagicMock(return_value=state)
        self.service._fetch_paper_daily_realized_pnl = MagicMock(return_value=-200.0)

        update_chain = _make_chain_mock()
        self.mock_client.table = MagicMock(return_value=update_chain)

        now = datetime(2024, 1, 10, 20, 0, 0, tzinfo=timezone.utc)
        result = self.service.eval_paper_green_day(self.user_id, now=now)

        self.assertFalse(result["green_day"])
        self.assertEqual(result["paper_green_days"], 5)  # unchanged

    def test_negative_day_preserves_last_green_date(self):
        """A non-green day should keep the previous paper_last_green_day_date."""
        state = _make_state(
            paper_green_days=3,
            paper_last_green_day_date="2024-01-09",
        )

        self.service.get_or_create_state = MagicMock(return_value=state)
        self.service._fetch_paper_daily_realized_pnl = MagicMock(return_value=-50.0)

        update_chain = _make_chain_mock()
        self.mock_client.table = MagicMock(return_value=update_chain)

        now = datetime(2024, 1, 10, 20, 0, 0, tzinfo=timezone.utc)
        result = self.service.eval_paper_green_day(self.user_id, now=now)

        self.assertEqual(result["paper_last_green_day_date"], "2024-01-09")


class TestGreenDayIdempotency(unittest.TestCase):
    """Rerun same day is idempotent — no double increment."""

    def setUp(self):
        self.mock_client = MagicMock()
        self.service = GoLiveValidationService(self.mock_client)
        self.user_id = "test-user-uuid"

    def test_rerun_same_day_returns_already_evaluated(self):
        """Second run on the same trading date should return already_evaluated=True."""
        state = _make_state(
            paper_green_days=4,
            paper_last_green_day_date="2024-01-10",
            paper_last_daily_realized_pnl=150.0,
            paper_last_green_day_evaluated_at="2024-01-10",
        )

        self.service.get_or_create_state = MagicMock(return_value=state)
        # _fetch should NOT be called — patching to detect unexpected calls
        self.service._fetch_paper_daily_realized_pnl = MagicMock(
            side_effect=AssertionError("Should not fetch on duplicate run")
        )

        now = datetime(2024, 1, 10, 22, 0, 0, tzinfo=timezone.utc)
        result = self.service.eval_paper_green_day(self.user_id, now=now)

        self.assertTrue(result["already_evaluated"])
        self.assertEqual(result["paper_green_days"], 4)  # NOT incremented
        self.assertEqual(result["daily_realized_pnl"], 150.0)  # cached value
        self.assertTrue(result["green_day"])  # derived from last_green == date

    def test_different_day_not_idempotent(self):
        """A different trading date should evaluate normally."""
        state = _make_state(
            paper_green_days=4,
            paper_last_green_day_evaluated_at="2024-01-10",
        )

        self.service.get_or_create_state = MagicMock(return_value=state)
        self.service._fetch_paper_daily_realized_pnl = MagicMock(return_value=75.0)

        update_chain = _make_chain_mock()
        self.mock_client.table = MagicMock(return_value=update_chain)

        # Next day: Jan 11
        now = datetime(2024, 1, 11, 20, 0, 0, tzinfo=timezone.utc)
        result = self.service.eval_paper_green_day(self.user_id, now=now)

        self.assertFalse(result["already_evaluated"])
        self.assertEqual(result["paper_green_days"], 5)
        self.assertEqual(result["evaluated_trading_date"], "2024-01-11")


class TestGreenDayChicagoBoundaries(unittest.TestCase):
    """Chicago date boundaries behave correctly across CST/CDT."""

    def setUp(self):
        self.mock_client = MagicMock()
        self.service = GoLiveValidationService(self.mock_client)
        self.user_id = "test-user-uuid"

    def test_late_utc_still_same_chicago_day(self):
        """
        11:59 PM UTC on Jan 10 is 5:59 PM CST on Jan 10 in Chicago.
        Trading date should be 2024-01-10.
        """
        state = _make_state()
        self.service.get_or_create_state = MagicMock(return_value=state)
        self.service._fetch_paper_daily_realized_pnl = MagicMock(return_value=100.0)

        update_chain = _make_chain_mock()
        self.mock_client.table = MagicMock(return_value=update_chain)

        now = datetime(2024, 1, 10, 23, 59, 0, tzinfo=timezone.utc)
        result = self.service.eval_paper_green_day(self.user_id, now=now)

        self.assertEqual(result["evaluated_trading_date"], "2024-01-10")

    def test_early_utc_previous_chicago_day(self):
        """
        5:00 AM UTC on Jan 11 is 11:00 PM CST on Jan 10 in Chicago.
        Trading date should be 2024-01-10 (still Chicago Jan 10).
        """
        state = _make_state()
        self.service.get_or_create_state = MagicMock(return_value=state)
        self.service._fetch_paper_daily_realized_pnl = MagicMock(return_value=100.0)

        update_chain = _make_chain_mock()
        self.mock_client.table = MagicMock(return_value=update_chain)

        now = datetime(2024, 1, 11, 5, 0, 0, tzinfo=timezone.utc)
        result = self.service.eval_paper_green_day(self.user_id, now=now)

        self.assertEqual(result["evaluated_trading_date"], "2024-01-10")

    def test_cdt_summer_boundary(self):
        """
        During CDT (UTC-5), 4:00 AM UTC on Jul 16 is 11:00 PM CDT on Jul 15.
        Trading date should be 2024-07-15.
        """
        state = _make_state()
        self.service.get_or_create_state = MagicMock(return_value=state)
        self.service._fetch_paper_daily_realized_pnl = MagicMock(return_value=50.0)

        update_chain = _make_chain_mock()
        self.mock_client.table = MagicMock(return_value=update_chain)

        now = datetime(2024, 7, 16, 4, 0, 0, tzinfo=timezone.utc)
        result = self.service.eval_paper_green_day(self.user_id, now=now)

        self.assertEqual(result["evaluated_trading_date"], "2024-07-15")

    def test_fetch_uses_chicago_window_boundaries(self):
        """The fetch should use day_start/day_end from chicago_day_window_utc."""
        state = _make_state()
        self.service.get_or_create_state = MagicMock(return_value=state)

        mock_fetch = MagicMock(return_value=200.0)
        self.service._fetch_paper_daily_realized_pnl = mock_fetch

        update_chain = _make_chain_mock()
        self.mock_client.table = MagicMock(return_value=update_chain)

        # Jan 15, 2024, 14:00 UTC = 8:00 AM CST
        now = datetime(2024, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
        self.service.eval_paper_green_day(self.user_id, now=now)

        # Verify the fetch was called with Chicago day window boundaries
        call_args = mock_fetch.call_args
        day_start, day_end = call_args[0][1], call_args[0][2]

        # CST midnight = 06:00 UTC
        expected_start = datetime(2024, 1, 15, 6, 0, 0, tzinfo=timezone.utc)
        expected_end = datetime(2024, 1, 16, 6, 0, 0, tzinfo=timezone.utc)

        self.assertEqual(day_start, expected_start)
        self.assertEqual(day_end, expected_end)


class TestGreenDayDoesNotAffectReadiness(unittest.TestCase):
    """Existing readiness behavior (paper_consecutive_passes) is unaffected."""

    def setUp(self):
        self.mock_client = MagicMock()
        self.service = GoLiveValidationService(self.mock_client)
        self.user_id = "test-user-uuid"

    def test_green_day_does_not_touch_consecutive_passes(self):
        """eval_paper_green_day must not modify paper_consecutive_passes."""
        state = _make_state(paper_consecutive_passes=7, paper_ready=False)

        self.service.get_or_create_state = MagicMock(return_value=state)
        self.service._fetch_paper_daily_realized_pnl = MagicMock(return_value=500.0)

        # Capture what gets written to the DB
        update_chain = _make_chain_mock()
        self.mock_client.table = MagicMock(return_value=update_chain)

        now = datetime(2024, 1, 10, 20, 0, 0, tzinfo=timezone.utc)
        self.service.eval_paper_green_day(self.user_id, now=now)

        # Extract the update payload from the mock chain
        update_call = update_chain.update.call_args
        update_payload = update_call[0][0]

        # paper_consecutive_passes and paper_ready must NOT be in the update
        self.assertNotIn("paper_consecutive_passes", update_payload)
        self.assertNotIn("paper_ready", update_payload)

    def test_green_day_does_not_modify_streak_days(self):
        """eval_paper_green_day must not modify paper_streak_days."""
        state = _make_state()

        self.service.get_or_create_state = MagicMock(return_value=state)
        self.service._fetch_paper_daily_realized_pnl = MagicMock(return_value=100.0)

        update_chain = _make_chain_mock()
        self.mock_client.table = MagicMock(return_value=update_chain)

        now = datetime(2024, 1, 10, 20, 0, 0, tzinfo=timezone.utc)
        self.service.eval_paper_green_day(self.user_id, now=now)

        update_payload = update_chain.update.call_args[0][0]
        self.assertNotIn("paper_streak_days", update_payload)

    def test_update_only_writes_green_day_fields(self):
        """The DB update should only contain green-day-specific fields + updated_at."""
        state = _make_state()

        self.service.get_or_create_state = MagicMock(return_value=state)
        self.service._fetch_paper_daily_realized_pnl = MagicMock(return_value=100.0)

        update_chain = _make_chain_mock()
        self.mock_client.table = MagicMock(return_value=update_chain)

        now = datetime(2024, 1, 10, 20, 0, 0, tzinfo=timezone.utc)
        self.service.eval_paper_green_day(self.user_id, now=now)

        update_payload = update_chain.update.call_args[0][0]
        allowed_keys = {
            "paper_green_days",
            "paper_last_green_day_date",
            "paper_last_daily_realized_pnl",
            "paper_last_green_day_evaluated_at",
            "updated_at",
        }
        self.assertTrue(set(update_payload.keys()).issubset(allowed_keys))


class TestGreenDayReturnContract(unittest.TestCase):
    """Verify the exact return shape for downstream consumers."""

    def setUp(self):
        self.mock_client = MagicMock()
        self.service = GoLiveValidationService(self.mock_client)
        self.user_id = "test-user-uuid"

    def test_return_shape_on_fresh_evaluation(self):
        """Fresh evaluation should return all required fields."""
        state = _make_state()
        self.service.get_or_create_state = MagicMock(return_value=state)
        self.service._fetch_paper_daily_realized_pnl = MagicMock(return_value=100.0)

        update_chain = _make_chain_mock()
        self.mock_client.table = MagicMock(return_value=update_chain)

        now = datetime(2024, 1, 10, 20, 0, 0, tzinfo=timezone.utc)
        result = self.service.eval_paper_green_day(self.user_id, now=now)

        required_keys = {
            "evaluated_trading_date",
            "daily_realized_pnl",
            "green_day",
            "paper_green_days",
            "paper_last_green_day_date",
            "already_evaluated",
        }
        self.assertTrue(required_keys.issubset(set(result.keys())))
        self.assertIsInstance(result["evaluated_trading_date"], str)
        self.assertIsInstance(result["daily_realized_pnl"], float)
        self.assertIsInstance(result["green_day"], bool)
        self.assertIsInstance(result["paper_green_days"], int)
        self.assertIsInstance(result["already_evaluated"], bool)

    def test_return_shape_on_duplicate_evaluation(self):
        """Duplicate evaluation should have the same field set."""
        state = _make_state(
            paper_green_days=4,
            paper_last_green_day_evaluated_at="2024-01-10",
            paper_last_daily_realized_pnl=100.0,
            paper_last_green_day_date="2024-01-10",
        )
        self.service.get_or_create_state = MagicMock(return_value=state)

        now = datetime(2024, 1, 10, 22, 0, 0, tzinfo=timezone.utc)
        result = self.service.eval_paper_green_day(self.user_id, now=now)

        required_keys = {
            "evaluated_trading_date",
            "daily_realized_pnl",
            "green_day",
            "paper_green_days",
            "paper_last_green_day_date",
            "already_evaluated",
        }
        self.assertTrue(required_keys.issubset(set(result.keys())))
        self.assertTrue(result["already_evaluated"])


if __name__ == "__main__":
    unittest.main()
