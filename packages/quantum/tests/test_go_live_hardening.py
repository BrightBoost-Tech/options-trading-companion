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


class TestOutcomesTakePriority(unittest.TestCase):
    """
    v4-L1H: Tests for outcomes-take-priority behavior.

    When outcomes exist, validation should proceed to pass/miss evaluation
    regardless of pending_suggestion_ids. The no_pending_suggestions skip
    should ONLY apply when outcome_count == 0.
    """

    def setUp(self):
        self.mock_client = MagicMock()
        self.user_id = "test-user-uuid"
        self.service = GoLiveValidationService(self.mock_client)

        # Default state with streak of 5
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

    def _patch_seams_with_outcomes(self, outcomes, pending_suggestion_ids=None):
        """
        Patch seams to return provided outcomes and optional pending_suggestion_ids.

        This simulates a scenario where outcomes exist in the window.
        """
        if pending_suggestion_ids is None:
            pending_suggestion_ids = []

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

        def table_mock(table_name):
            if table_name == "learning_trade_outcomes_v3":
                return create_chain_mock(make_res(outcomes))
            elif table_name == "v3_go_live_runs":
                return create_chain_mock(make_res(None))
            elif table_name == "v3_go_live_state":
                return create_chain_mock(make_res(None))
            return create_chain_mock(make_res([]))

        self.mock_client.table = MagicMock(side_effect=table_mock)

        # Patch seams
        self.service.get_or_create_state = MagicMock(return_value=self.default_state.copy())
        self.service._ensure_forward_checkpoint_defaults = MagicMock(return_value=self.default_state.copy())
        self.service._repair_window_if_needed = MagicMock(return_value=(
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            datetime(2024, 1, 22, tzinfo=timezone.utc),
            False
        ))
        self.service._get_paper_forward_policy_overrides = MagicMock(return_value=None)
        self.service._compute_drawdown = MagicMock(return_value=0.0)
        self.service._log_checkpoint_run = MagicMock()
        # These should NOT be called when outcomes exist
        self.service._get_paper_portfolio_ids = MagicMock(return_value=["port1"])
        self.service._has_open_paper_positions = MagicMock(return_value=False)
        self.service._recent_paper_fills_count = MagicMock(return_value=0)
        self.service._pending_suggestion_ids = MagicMock(return_value=pending_suggestion_ids)
        self.service._has_linked_orders = MagicMock(return_value=False)

    def test_outcomes_exist_no_pending_suggestions_evaluates_normally(self):
        """
        v4-L1H: When outcomes exist but pending_suggestion_ids is empty,
        should NOT skip with no_pending_suggestions - should evaluate normally.
        """
        # Positive PnL outcome - should result in pass
        outcomes = [
            {"closed_at": "2024-01-10T14:00:00+00:00", "pnl_realized": 500.0, "profit_pct": 0.5}
        ]

        self._patch_seams_with_outcomes(
            outcomes=outcomes,
            pending_suggestion_ids=[]  # Empty - but shouldn't matter!
        )

        # Weekday: Wednesday January 10, 2024
        now = datetime(2024, 1, 10, 14, 0, 0, tzinfo=timezone.utc)

        result = self.service.eval_paper_forward_checkpoint(self.user_id, now=now)

        # Should NOT be skipped_no_signal_day
        self.assertNotEqual(result["status"], "skipped_no_signal_day")
        self.assertNotEqual(result.get("reason"), "no_pending_suggestions")

        # Should evaluate to pass or miss (not skip)
        self.assertIn(result["status"], ["pass", "miss", "fail_fast"])
        self.assertEqual(result["outcome_count"], 1)

    def test_outcomes_exist_proceeds_to_pass(self):
        """
        When outcomes exist with positive return, should pass checkpoint.
        """
        # Progress is ~0.45 (day 10 of 21 days)
        # At 0.45 progress, target_return_now = 10% * 0.45 = 4.5%
        # With 100k baseline and 500 PnL, return = 0.5%
        # This would be a miss (0.5% < 4.5%)

        # Let's use enough PnL to pass
        outcomes = [
            {"closed_at": "2024-01-10T14:00:00+00:00", "pnl_realized": 5000.0, "profit_pct": 5.0}
        ]

        self._patch_seams_with_outcomes(
            outcomes=outcomes,
            pending_suggestion_ids=[]
        )

        now = datetime(2024, 1, 10, 14, 0, 0, tzinfo=timezone.utc)

        result = self.service.eval_paper_forward_checkpoint(self.user_id, now=now)

        # Should pass (5% return > 4.5% target)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["outcome_count"], 1)
        # Streak should increment
        self.assertEqual(result["paper_consecutive_passes"], 6)

    def test_outcomes_exist_proceeds_to_miss(self):
        """
        When outcomes exist with below-target return, should miss checkpoint.
        """
        # Small positive PnL - below pacing target
        outcomes = [
            {"closed_at": "2024-01-10T14:00:00+00:00", "pnl_realized": 100.0, "profit_pct": 0.1}
        ]

        self._patch_seams_with_outcomes(
            outcomes=outcomes,
            pending_suggestion_ids=[]
        )

        now = datetime(2024, 1, 10, 14, 0, 0, tzinfo=timezone.utc)

        result = self.service.eval_paper_forward_checkpoint(self.user_id, now=now)

        # Should miss (0.1% return < ~4.5% target)
        self.assertEqual(result["status"], "miss")
        self.assertEqual(result["outcome_count"], 1)
        # Streak should reset
        self.assertEqual(result["paper_consecutive_passes"], 0)

    def test_no_outcomes_no_suggestions_still_skips(self):
        """
        When outcome_count == 0 AND pending_suggestion_ids is empty,
        should still skip with no_pending_suggestions.
        """
        self._patch_seams_with_outcomes(
            outcomes=[],  # No outcomes
            pending_suggestion_ids=[]  # No suggestions
        )

        now = datetime(2024, 1, 10, 14, 0, 0, tzinfo=timezone.utc)

        result = self.service.eval_paper_forward_checkpoint(self.user_id, now=now)

        # Should skip with no_pending_suggestions
        self.assertEqual(result["status"], "skipped_no_signal_day")
        self.assertEqual(result["reason"], "no_pending_suggestions")
        # Streak should be preserved
        self.assertEqual(result["paper_consecutive_passes"], 5)


class TestUpdatedAtOnSkip(unittest.TestCase):
    """
    Tests that updated_at is updated on non-weekend skips.

    v4-L1H: All skip statuses (except weekend) should update updated_at
    to confirm the evaluation ran.
    """

    def setUp(self):
        self.mock_client = MagicMock()
        self.user_id = "test-user-uuid"
        self.service = GoLiveValidationService(self.mock_client)

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

        self.update_calls = []

    def _patch_seams_and_capture_updates(self, has_open_positions=False, pending_suggestion_ids=None):
        """
        Patch seams and capture update calls to v3_go_live_state.
        """
        if pending_suggestion_ids is None:
            pending_suggestion_ids = []

        def make_res(data):
            r = MagicMock()
            r.data = data
            return r

        def create_chain_mock(return_value):
            chain = MagicMock()
            chain.execute.return_value = return_value
            def return_self(*args, **kwargs):
                return chain
            for method in ['select', 'eq', 'neq', 'gt', 'gte', 'lt', 'lte', 'in_', 'order', 'limit', 'single', 'insert']:
                setattr(chain, method, MagicMock(side_effect=return_self))
            # Capture update calls
            def capture_update(data):
                self.update_calls.append(data)
                return chain
            chain.update = MagicMock(side_effect=capture_update)
            return chain

        def table_mock(table_name):
            if table_name == "learning_trade_outcomes_v3":
                return create_chain_mock(make_res([]))  # No outcomes
            elif table_name == "v3_go_live_runs":
                return create_chain_mock(make_res(None))
            elif table_name == "v3_go_live_state":
                return create_chain_mock(make_res(None))
            return create_chain_mock(make_res([]))

        self.mock_client.table = MagicMock(side_effect=table_mock)

        self.service.get_or_create_state = MagicMock(return_value=self.default_state.copy())
        self.service._ensure_forward_checkpoint_defaults = MagicMock(return_value=self.default_state.copy())
        self.service._repair_window_if_needed = MagicMock(return_value=(
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            datetime(2024, 1, 22, tzinfo=timezone.utc),
            False
        ))
        self.service._get_paper_forward_policy_overrides = MagicMock(return_value=None)
        self.service._get_paper_portfolio_ids = MagicMock(return_value=["port1"])
        self.service._has_open_paper_positions = MagicMock(return_value=has_open_positions)
        self.service._recent_paper_fills_count = MagicMock(return_value=0)
        self.service._pending_suggestion_ids = MagicMock(return_value=pending_suggestion_ids)
        self.service._has_linked_orders = MagicMock(return_value=False)
        self.service._log_checkpoint_run = MagicMock()

    def test_weekend_skip_does_not_update_updated_at(self):
        """Weekend skip should NOT update updated_at (no activity expected)."""
        self._patch_seams_and_capture_updates()

        # Saturday January 20, 2024
        now = datetime(2024, 1, 20, 14, 0, 0, tzinfo=timezone.utc)

        result = self.service.eval_paper_forward_checkpoint(self.user_id, now=now)

        self.assertEqual(result["status"], "skipped_non_trading_day")
        self.assertEqual(result["reason"], "weekend")

        # No update should have been called
        update_with_updated_at = [u for u in self.update_calls if "updated_at" in u]
        self.assertEqual(len(update_with_updated_at), 0)

    def test_open_positions_skip_updates_updated_at(self):
        """Open positions skip should update updated_at."""
        self._patch_seams_and_capture_updates(has_open_positions=True)

        now = datetime(2024, 1, 10, 14, 0, 0, tzinfo=timezone.utc)

        result = self.service.eval_paper_forward_checkpoint(self.user_id, now=now)

        self.assertEqual(result["status"], "skipped_no_close_activity")
        self.assertEqual(result["reason"], "open_positions_held")

        # Should have updated updated_at
        update_with_updated_at = [u for u in self.update_calls if "updated_at" in u]
        self.assertEqual(len(update_with_updated_at), 1)

    def test_no_pending_suggestions_skip_updates_updated_at(self):
        """No pending suggestions skip should update updated_at."""
        self._patch_seams_and_capture_updates(pending_suggestion_ids=[])

        now = datetime(2024, 1, 10, 14, 0, 0, tzinfo=timezone.utc)

        result = self.service.eval_paper_forward_checkpoint(self.user_id, now=now)

        self.assertEqual(result["status"], "skipped_no_signal_day")
        self.assertEqual(result["reason"], "no_pending_suggestions")

        # Should have updated updated_at
        update_with_updated_at = [u for u in self.update_calls if "updated_at" in u]
        self.assertEqual(len(update_with_updated_at), 1)


if __name__ == "__main__":
    unittest.main()
