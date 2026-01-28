import unittest
from unittest.mock import MagicMock, patch
import sys
# Bypass version check
with patch.dict(sys.modules, {"packages.quantum.check_version": MagicMock()}):
    from packages.quantum.services.go_live_validation_service import GoLiveValidationService, chicago_day_window_utc, is_weekend_chicago
from datetime import datetime, timezone, timedelta


class TestIsWeekendChicago(unittest.TestCase):
    """Unit tests for DST-safe weekend check in Chicago timezone."""

    def test_weekend_saturday_cst(self):
        """Test Saturday detection during CST (winter)."""
        # Saturday January 20, 2024, 14:00 UTC (8:00 AM Chicago CST)
        now_utc = datetime(2024, 1, 20, 14, 0, 0, tzinfo=timezone.utc)
        self.assertTrue(is_weekend_chicago(now_utc))

    def test_weekend_sunday_cst(self):
        """Test Sunday detection during CST (winter)."""
        # Sunday January 21, 2024, 14:00 UTC (8:00 AM Chicago CST)
        now_utc = datetime(2024, 1, 21, 14, 0, 0, tzinfo=timezone.utc)
        self.assertTrue(is_weekend_chicago(now_utc))

    def test_weekday_monday_cst(self):
        """Test Monday is not weekend during CST (winter)."""
        # Monday January 15, 2024, 14:00 UTC (8:00 AM Chicago CST)
        now_utc = datetime(2024, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
        self.assertFalse(is_weekend_chicago(now_utc))

    def test_weekend_saturday_cdt(self):
        """Test Saturday detection during CDT (summer)."""
        # Saturday July 20, 2024, 14:00 UTC (9:00 AM Chicago CDT)
        now_utc = datetime(2024, 7, 20, 14, 0, 0, tzinfo=timezone.utc)
        self.assertTrue(is_weekend_chicago(now_utc))

    def test_weekday_friday_late_utc_still_friday_chicago(self):
        """Test late Friday UTC that is still Friday in Chicago."""
        # Friday January 19, 2024, 23:00 UTC (5:00 PM Chicago CST - still Friday)
        now_utc = datetime(2024, 1, 19, 23, 0, 0, tzinfo=timezone.utc)
        self.assertFalse(is_weekend_chicago(now_utc))

    def test_saturday_early_utc_is_saturday_chicago(self):
        """Test early Saturday UTC that is Saturday in Chicago."""
        # Saturday January 20, 2024, 07:00 UTC (1:00 AM Chicago CST - Saturday)
        now_utc = datetime(2024, 1, 20, 7, 0, 0, tzinfo=timezone.utc)
        self.assertTrue(is_weekend_chicago(now_utc))


class TestChicagoDayWindow(unittest.TestCase):
    """Unit tests for DST-safe Chicago day window computation."""

    def test_chicago_window_cst_winter(self):
        """Test Chicago window during CST (winter, UTC-6)."""
        # January 15, 2024, 14:00 UTC (8:00 AM Chicago CST)
        now_utc = datetime(2024, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
        start_utc, end_utc = chicago_day_window_utc(now_utc)

        # CST: Chicago midnight = 06:00 UTC
        expected_start = datetime(2024, 1, 15, 6, 0, 0, tzinfo=timezone.utc)
        expected_end = datetime(2024, 1, 16, 6, 0, 0, tzinfo=timezone.utc)

        self.assertEqual(start_utc, expected_start)
        self.assertEqual(end_utc, expected_end)

    def test_chicago_window_cdt_summer(self):
        """Test Chicago window during CDT (summer, UTC-5)."""
        # July 15, 2024, 14:00 UTC (9:00 AM Chicago CDT)
        now_utc = datetime(2024, 7, 15, 14, 0, 0, tzinfo=timezone.utc)
        start_utc, end_utc = chicago_day_window_utc(now_utc)

        # CDT: Chicago midnight = 05:00 UTC
        expected_start = datetime(2024, 7, 15, 5, 0, 0, tzinfo=timezone.utc)
        expected_end = datetime(2024, 7, 16, 5, 0, 0, tzinfo=timezone.utc)

        self.assertEqual(start_utc, expected_start)
        self.assertEqual(end_utc, expected_end)

    def test_chicago_window_dst_spring_forward(self):
        """Test Chicago window around DST spring forward (March 2024)."""
        # March 10, 2024 is DST spring forward day
        # At 2:00 AM Chicago, clocks spring forward to 3:00 AM
        # Before DST: CST (UTC-6), After DST: CDT (UTC-5)

        # March 11, 2024, 12:00 UTC (first full day after spring forward, 7:00 AM CDT)
        now_utc = datetime(2024, 3, 11, 12, 0, 0, tzinfo=timezone.utc)
        start_utc, end_utc = chicago_day_window_utc(now_utc)

        # CDT: Chicago midnight = 05:00 UTC
        expected_start = datetime(2024, 3, 11, 5, 0, 0, tzinfo=timezone.utc)
        expected_end = datetime(2024, 3, 12, 5, 0, 0, tzinfo=timezone.utc)

        self.assertEqual(start_utc, expected_start)
        self.assertEqual(end_utc, expected_end)

    def test_chicago_window_dst_fall_back(self):
        """Test Chicago window around DST fall back (November 2024)."""
        # November 3, 2024 is DST fall back day
        # At 2:00 AM Chicago, clocks fall back to 1:00 AM
        # Before DST: CDT (UTC-5), After DST: CST (UTC-6)

        # November 4, 2024, 12:00 UTC (first full day after fall back, 6:00 AM CST)
        now_utc = datetime(2024, 11, 4, 12, 0, 0, tzinfo=timezone.utc)
        start_utc, end_utc = chicago_day_window_utc(now_utc)

        # CST: Chicago midnight = 06:00 UTC
        expected_start = datetime(2024, 11, 4, 6, 0, 0, tzinfo=timezone.utc)
        expected_end = datetime(2024, 11, 5, 6, 0, 0, tzinfo=timezone.utc)

        self.assertEqual(start_utc, expected_start)
        self.assertEqual(end_utc, expected_end)

class TestGoLiveHardening(unittest.TestCase):
    """
    Phase 3 hardening tests using deterministic seam patching.

    These tests patch the helper seams directly instead of mocking
    Supabase query chains, making them more reliable and maintainable.
    """

    def setUp(self):
        self.mock_client = MagicMock()
        self.user_id = "test-user-uuid"
        self.service = GoLiveValidationService(self.mock_client)

        # Default passing state with streak of 5
        self.default_state = {
            "user_id": self.user_id,
            "paper_window_start": "2024-01-01T00:00:00+00:00",
            "paper_window_end": "2024-01-22T00:00:00+00:00",
            "paper_baseline_capital": 100000,
            "paper_consecutive_passes": 5,
            "paper_ready": False,
            "paper_window_days": 21,
            "paper_checkpoint_target": 10,
        }

    def _patch_seams_for_no_outcomes(
        self,
        portfolio_ids=None,
        has_open_positions=False,
        recent_fills_count=0,
        pending_suggestion_ids=None,
        has_linked_orders=False
    ):
        """
        Patch all helper seams for "no outcomes" branch testing.

        Returns a context manager that patches:
        - get_or_create_state -> default_state
        - _get_paper_portfolio_ids -> portfolio_ids
        - _has_open_paper_positions -> has_open_positions
        - _recent_paper_fills_count -> recent_fills_count
        - _pending_suggestion_ids -> pending_suggestion_ids
        - _has_linked_orders -> has_linked_orders
        """
        if portfolio_ids is None:
            portfolio_ids = ["port1"]
        if pending_suggestion_ids is None:
            pending_suggestion_ids = []

        # Also need to mock the outcomes query to return empty
        def make_res(data):
            r = MagicMock()
            r.data = data
            return r

        def create_chain_mock(return_value):
            chain = MagicMock()
            chain.execute.return_value = return_value
            def return_self(*args, **kwargs):
                return chain
            for method in ['select', 'eq', 'neq', 'gt', 'gte', 'lt', 'lte', 'in_', 'order', 'limit', 'single', 'update', 'insert']:
                setattr(chain, method, MagicMock(side_effect=return_self))
            return chain

        # Mock table calls for outcomes (empty) and v3_go_live_runs (logging)
        def table_mock(table_name):
            if table_name == "learning_trade_outcomes_v3":
                return create_chain_mock(make_res([]))  # No outcomes
            elif table_name == "v3_go_live_runs":
                return create_chain_mock(make_res(None))
            elif table_name == "v3_go_live_state":
                return create_chain_mock(make_res(None))
            return create_chain_mock(make_res([]))

        self.mock_client.table = MagicMock(side_effect=table_mock)

        # Patch all seams
        self.service.get_or_create_state = MagicMock(return_value=self.default_state.copy())
        self.service._get_paper_portfolio_ids = MagicMock(return_value=portfolio_ids)
        self.service._has_open_paper_positions = MagicMock(return_value=has_open_positions)
        self.service._recent_paper_fills_count = MagicMock(return_value=recent_fills_count)
        self.service._pending_suggestion_ids = MagicMock(return_value=pending_suggestion_ids)
        self.service._has_linked_orders = MagicMock(return_value=has_linked_orders)

    def test_skip_non_trading_day_weekend(self):
        """Weekend skip: Saturday in Chicago should skip with streak preserved."""
        self._patch_seams_for_no_outcomes()

        # Saturday January 20, 2024, 14:00 UTC (8:00 AM Chicago CST)
        now = datetime(2024, 1, 20, 14, 0, 0, tzinfo=timezone.utc)

        result = self.service.eval_paper_forward_checkpoint(self.user_id, now=now)

        self.assertEqual(result["status"], "skipped_non_trading_day")
        self.assertEqual(result["reason"], "weekend")
        self.assertEqual(result["paper_consecutive_passes"], 5)

    def test_skip_open_positions_held(self):
        """Open positions: Skip if positions exist with streak preserved."""
        self._patch_seams_for_no_outcomes(
            has_open_positions=True
        )

        # Weekday: Wednesday January 10, 2024
        now = datetime(2024, 1, 10, 14, 0, 0, tzinfo=timezone.utc)

        result = self.service.eval_paper_forward_checkpoint(self.user_id, now=now)

        self.assertEqual(result["status"], "skipped_no_close_activity")
        self.assertEqual(result["reason"], "open_positions_held")
        self.assertEqual(result["paper_consecutive_passes"], 5)

    def test_skip_no_pending_suggestions(self):
        """No suggestions: Skip if no pending suggestions with streak preserved."""
        self._patch_seams_for_no_outcomes(
            has_open_positions=False,
            pending_suggestion_ids=[]  # No pending suggestions
        )

        # Weekday: Wednesday January 10, 2024
        now = datetime(2024, 1, 10, 14, 0, 0, tzinfo=timezone.utc)

        result = self.service.eval_paper_forward_checkpoint(self.user_id, now=now)

        self.assertEqual(result["status"], "skipped_no_signal_day")
        self.assertEqual(result["reason"], "no_pending_suggestions")
        self.assertEqual(result["paper_consecutive_passes"], 5)

    def test_skip_autopilot_inactive(self):
        """Autopilot inactive: Suggestions exist but no linked orders."""
        self._patch_seams_for_no_outcomes(
            has_open_positions=False,
            pending_suggestion_ids=["sugg1", "sugg2"],  # Suggestions exist
            has_linked_orders=False  # But no linked orders
        )

        # Weekday: Wednesday January 10, 2024
        now = datetime(2024, 1, 10, 14, 0, 0, tzinfo=timezone.utc)

        result = self.service.eval_paper_forward_checkpoint(self.user_id, now=now)

        self.assertEqual(result["status"], "skipped_no_signal_day")
        self.assertEqual(result["reason"], "autopilot_inactive")
        self.assertEqual(result["paper_consecutive_passes"], 5)

    def test_skip_no_fill_activity(self):
        """No fill activity: Orders exist but no outcomes (ambiguous/no-fill)."""
        self._patch_seams_for_no_outcomes(
            has_open_positions=False,
            pending_suggestion_ids=["sugg1"],  # Suggestions exist
            has_linked_orders=True  # And linked orders exist
        )

        # Weekday: Wednesday January 10, 2024
        now = datetime(2024, 1, 10, 14, 0, 0, tzinfo=timezone.utc)

        result = self.service.eval_paper_forward_checkpoint(self.user_id, now=now)

        self.assertEqual(result["status"], "skipped_no_fill_activity")
        self.assertEqual(result["reason"], "orders_exist_no_outcomes")
        self.assertEqual(result["paper_consecutive_passes"], 5)

    def test_ingestion_lag_detected(self):
        """Ingestion lag: Recent fills detected should return error with streak preserved."""
        self._patch_seams_for_no_outcomes(
            has_open_positions=False,
            recent_fills_count=3  # Recent fills detected
        )

        # Weekday: Wednesday January 10, 2024
        now = datetime(2024, 1, 10, 14, 0, 0, tzinfo=timezone.utc)

        result = self.service.eval_paper_forward_checkpoint(self.user_id, now=now)

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["reason"], "ingestion_lag_detected")
        self.assertEqual(result["paper_consecutive_passes"], 5)

    def test_no_paper_portfolios(self):
        """Edge case: No paper portfolios should fall through to no signal day."""
        self._patch_seams_for_no_outcomes(
            portfolio_ids=[],  # No portfolios
            has_open_positions=False,  # Will be False with no portfolios
            pending_suggestion_ids=[]  # No suggestions
        )

        # Weekday: Wednesday January 10, 2024
        now = datetime(2024, 1, 10, 14, 0, 0, tzinfo=timezone.utc)

        result = self.service.eval_paper_forward_checkpoint(self.user_id, now=now)

        self.assertEqual(result["status"], "skipped_no_signal_day")
        self.assertEqual(result["paper_consecutive_passes"], 5)
