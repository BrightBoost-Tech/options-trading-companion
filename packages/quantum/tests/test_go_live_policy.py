"""
Unit tests for v4-L2 Go-Live Gate Policy.

Tests the Gate Matrix:
1. paused=True => allowed=False, reason=paused_globally
2. mode=paper => allowed=False, reason=mode_is_paper_only
3. mode=micro_live + paper_ready=False => allowed=False, reason=paper_milestones_incomplete
4. mode=micro_live + paper_ready=True => allowed=True, requires_manual_approval=True, reason=micro_live_restricted
5. mode=live + overall_ready=False => allowed=False, reason=historical_validation_failed
6. mode=live + overall_ready=True => allowed=True, requires_manual_approval=False, reason=fully_authorized
"""

import unittest
import sys
import os

# Add parent path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestGateMatrixPausedGlobally(unittest.TestCase):
    """Test case 1: paused=True => allowed=False, reason=paused_globally"""

    def test_paused_globally_denies_regardless_of_mode(self):
        """When paused=True, gate denies regardless of mode or readiness."""
        from policies.go_live_policy import evaluate_go_live_gate

        ops_state = {
            "paused": True,
            "pause_reason": "Maintenance",
            "mode": "live",
        }
        user_readiness = {
            "paper_ready": True,
            "overall_ready": True,
        }

        decision = evaluate_go_live_gate(ops_state, user_readiness)

        self.assertFalse(decision.allowed)
        self.assertFalse(decision.requires_manual_approval)
        self.assertEqual(decision.reason, "paused_globally")

    def test_paused_globally_context_includes_pause_reason(self):
        """Context includes pause_reason when paused."""
        from policies.go_live_policy import evaluate_go_live_gate

        ops_state = {
            "paused": True,
            "pause_reason": "System upgrade",
            "mode": "paper",
        }
        user_readiness = {}

        decision = evaluate_go_live_gate(ops_state, user_readiness)

        self.assertEqual(decision.context["pause_reason"], "System upgrade")


class TestGateMatrixPaperMode(unittest.TestCase):
    """Test case 2: mode=paper => allowed=False, reason=mode_is_paper_only"""

    def test_paper_mode_denies(self):
        """When mode=paper and not paused, gate denies."""
        from policies.go_live_policy import evaluate_go_live_gate

        ops_state = {
            "paused": False,
            "mode": "paper",
        }
        user_readiness = {
            "paper_ready": True,
            "overall_ready": True,
        }

        decision = evaluate_go_live_gate(ops_state, user_readiness)

        self.assertFalse(decision.allowed)
        self.assertFalse(decision.requires_manual_approval)
        self.assertEqual(decision.reason, "mode_is_paper_only")


class TestGateMatrixMicroLive(unittest.TestCase):
    """Test cases 3-4: micro_live mode checks paper_ready"""

    def test_micro_live_paper_not_ready_denies(self):
        """Case 3: mode=micro_live + paper_ready=False => denied."""
        from policies.go_live_policy import evaluate_go_live_gate

        ops_state = {
            "paused": False,
            "mode": "micro_live",
        }
        user_readiness = {
            "paper_ready": False,
            "overall_ready": False,
        }

        decision = evaluate_go_live_gate(ops_state, user_readiness)

        self.assertFalse(decision.allowed)
        self.assertFalse(decision.requires_manual_approval)
        self.assertEqual(decision.reason, "paper_milestones_incomplete")

    def test_micro_live_paper_ready_allows_with_manual_approval(self):
        """Case 4: mode=micro_live + paper_ready=True => allowed with manual approval."""
        from policies.go_live_policy import evaluate_go_live_gate

        ops_state = {
            "paused": False,
            "mode": "micro_live",
        }
        user_readiness = {
            "paper_ready": True,
            "overall_ready": False,
        }

        decision = evaluate_go_live_gate(ops_state, user_readiness)

        self.assertTrue(decision.allowed)
        self.assertTrue(decision.requires_manual_approval)
        self.assertEqual(decision.reason, "micro_live_restricted")


class TestGateMatrixLiveMode(unittest.TestCase):
    """Test cases 5-6: live mode checks overall_ready"""

    def test_live_mode_not_ready_denies(self):
        """Case 5: mode=live + overall_ready=False => denied."""
        from policies.go_live_policy import evaluate_go_live_gate

        ops_state = {
            "paused": False,
            "mode": "live",
        }
        user_readiness = {
            "paper_ready": True,
            "overall_ready": False,
        }

        decision = evaluate_go_live_gate(ops_state, user_readiness)

        self.assertFalse(decision.allowed)
        self.assertFalse(decision.requires_manual_approval)
        self.assertEqual(decision.reason, "historical_validation_failed")

    def test_live_mode_ready_allows_fully(self):
        """Case 6: mode=live + overall_ready=True => fully authorized."""
        from policies.go_live_policy import evaluate_go_live_gate

        ops_state = {
            "paused": False,
            "mode": "live",
        }
        user_readiness = {
            "paper_ready": True,
            "overall_ready": True,
        }

        decision = evaluate_go_live_gate(ops_state, user_readiness)

        self.assertTrue(decision.allowed)
        self.assertFalse(decision.requires_manual_approval)
        self.assertEqual(decision.reason, "fully_authorized")


class TestGateMatrixSafetyDefaults(unittest.TestCase):
    """Tests for safety defaults when data is missing."""

    def test_missing_ops_state_keys_defaults_to_deny(self):
        """Missing ops_state keys default to safe values (paused=True, mode=paper)."""
        from policies.go_live_policy import evaluate_go_live_gate

        ops_state = {}  # Empty - missing all keys
        user_readiness = {
            "paper_ready": True,
            "overall_ready": True,
        }

        decision = evaluate_go_live_gate(ops_state, user_readiness)

        # Should default to paused=True
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "paused_globally")

    def test_missing_user_readiness_keys_defaults_to_not_ready(self):
        """Missing user_readiness keys default to False."""
        from policies.go_live_policy import evaluate_go_live_gate

        ops_state = {
            "paused": False,
            "mode": "live",
        }
        user_readiness = {}  # Empty - missing paper_ready and overall_ready

        decision = evaluate_go_live_gate(ops_state, user_readiness)

        # Should default overall_ready to False
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "historical_validation_failed")

    def test_unknown_mode_defaults_to_deny(self):
        """Unknown mode defaults to deny."""
        from policies.go_live_policy import evaluate_go_live_gate

        ops_state = {
            "paused": False,
            "mode": "unknown_mode",
        }
        user_readiness = {
            "paper_ready": True,
            "overall_ready": True,
        }

        decision = evaluate_go_live_gate(ops_state, user_readiness)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "unknown_mode")


class TestGateDecisionContext(unittest.TestCase):
    """Tests that context is properly populated."""

    def test_context_includes_all_state(self):
        """Context includes mode, paused, pause_reason, paper_ready, overall_ready."""
        from policies.go_live_policy import evaluate_go_live_gate

        ops_state = {
            "paused": False,
            "pause_reason": None,
            "mode": "micro_live",
        }
        user_readiness = {
            "paper_ready": True,
            "overall_ready": False,
        }

        decision = evaluate_go_live_gate(ops_state, user_readiness)

        self.assertEqual(decision.context["mode"], "micro_live")
        self.assertFalse(decision.context["paused"])
        self.assertIsNone(decision.context["pause_reason"])
        self.assertTrue(decision.context["paper_ready"])
        self.assertFalse(decision.context["overall_ready"])

    def test_to_dict_returns_correct_structure(self):
        """to_dict() returns proper dictionary structure."""
        from policies.go_live_policy import evaluate_go_live_gate

        ops_state = {"paused": False, "mode": "live"}
        user_readiness = {"paper_ready": True, "overall_ready": True}

        decision = evaluate_go_live_gate(ops_state, user_readiness)
        result = decision.to_dict()

        self.assertIn("allowed", result)
        self.assertIn("requires_manual_approval", result)
        self.assertIn("reason", result)
        self.assertIn("context", result)
        self.assertTrue(result["allowed"])


class TestJobRequiresLivePrivileges(unittest.TestCase):
    """Tests for _job_requires_live_privileges helper."""

    def test_live_prefix_requires_privileges(self):
        """Jobs starting with 'live_' require privileges."""
        from public_tasks import _job_requires_live_privileges

        self.assertTrue(_job_requires_live_privileges("live_order_submit"))
        self.assertTrue(_job_requires_live_privileges("live_order_cancel"))
        self.assertTrue(_job_requires_live_privileges("live_anything"))

    def test_broker_prefix_does_not_require_privileges(self):
        """Jobs starting with 'broker_' do NOT require privileges (read-only)."""
        from public_tasks import _job_requires_live_privileges

        # broker_sync and other broker jobs are read-only, not gated
        self.assertFalse(_job_requires_live_privileges("broker_sync"))
        self.assertFalse(_job_requires_live_privileges("broker_read"))

    def test_explicit_job_names_require_privileges(self):
        """Explicit job names in LIVE_EXEC_JOB_NAMES require privileges."""
        from public_tasks import _job_requires_live_privileges

        # Only actual order execution jobs require privileges
        self.assertTrue(_job_requires_live_privileges("live_order_submit"))
        self.assertTrue(_job_requires_live_privileges("live_order_cancel"))
        self.assertTrue(_job_requires_live_privileges("live_order_retry"))

    def test_regular_jobs_do_not_require_privileges(self):
        """Regular jobs (suggestions, learning, etc.) don't require live privileges."""
        from public_tasks import _job_requires_live_privileges

        self.assertFalse(_job_requires_live_privileges("suggestions_open"))
        self.assertFalse(_job_requires_live_privileges("suggestions_close"))
        self.assertFalse(_job_requires_live_privileges("learning_ingest"))
        self.assertFalse(_job_requires_live_privileges("validation_eval"))
        self.assertFalse(_job_requires_live_privileges("strategy_autotune"))


class TestExtractUserId(unittest.TestCase):
    """Tests for _extract_user_id helper."""

    def test_extracts_valid_user_id(self):
        """Extracts user_id from payload."""
        from public_tasks import _extract_user_id

        payload = {"user_id": "abc123-uuid"}
        self.assertEqual(_extract_user_id(payload), "abc123-uuid")

    def test_returns_none_for_missing_user_id(self):
        """Returns None if user_id is missing."""
        from public_tasks import _extract_user_id

        payload = {}
        self.assertIsNone(_extract_user_id(payload))

    def test_returns_none_for_all_user_id(self):
        """Returns None if user_id is 'all' (batch job)."""
        from public_tasks import _extract_user_id

        payload = {"user_id": "all"}
        self.assertIsNone(_extract_user_id(payload))

    def test_returns_none_for_empty_user_id(self):
        """Returns None if user_id is empty string."""
        from public_tasks import _extract_user_id

        payload = {"user_id": ""}
        self.assertIsNone(_extract_user_id(payload))


class TestRollingPaperStreakCheckpoint(unittest.TestCase):
    """Tests for Phase 2.1 rolling paper streak checkpoint."""

    def setUp(self):
        """Set up mocked supabase client."""
        from unittest.mock import MagicMock, patch
        self.mock_client = MagicMock()
        self.user_id = "test-user-uuid"

        # Default state
        self.default_state = {
            "user_id": self.user_id,
            "paper_window_start": "2024-01-01T00:00:00+00:00",
            "paper_window_end": "2024-04-01T00:00:00+00:00",
            "paper_baseline_capital": 100000,
            "paper_consecutive_passes": 0,
            "paper_ready": False,
            "historical_last_run_at": None,
            "historical_last_result": {},
            "overall_ready": False,
            "paper_streak_days": 0,
            "paper_last_checkpoint_at": None,
            "paper_checkpoint_window_days": 14
        }

    def test_checkpoint_pass_increments_streak(self):
        """Checkpoint that passes increments streak_days."""
        from unittest.mock import MagicMock
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService
        from datetime import datetime, timezone

        # Mock state select
        mock_state_response = MagicMock()
        mock_state_response.data = self.default_state

        # Mock trades query - 3% return (above 2% threshold)
        mock_trades_response = MagicMock()
        mock_trades_response.data = [
            {"closed_at": "2024-01-10T00:00:00+00:00", "pnl_realized": 3000.0}
        ]

        # Setup query chain
        def table_mock(table_name):
            mock = MagicMock()
            if table_name == "v3_go_live_state":
                mock.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_state_response
                mock.update.return_value.eq.return_value.execute.return_value = MagicMock()
            elif table_name == "learning_trade_outcomes_v3":
                mock.select.return_value.eq.return_value.eq.return_value.gte.return_value.lte.return_value.execute.return_value = mock_trades_response
            elif table_name == "v3_go_live_runs":
                mock.insert.return_value.execute.return_value = MagicMock()
            return mock

        self.mock_client.table = table_mock

        service = GoLiveValidationService(self.mock_client)
        now = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        result = service.checkpoint_paper_streak(self.user_id, now=now, force=True)

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["streak_days"], 1)  # 0 + 1
        self.assertEqual(result["streak_before"], 0)
        self.assertGreaterEqual(result["rolling_return_pct"], 2.0)

    def test_checkpoint_fail_resets_streak(self):
        """Checkpoint that fails resets streak_days to 0."""
        from unittest.mock import MagicMock
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService
        from datetime import datetime, timezone

        # Set existing streak
        state_with_streak = self.default_state.copy()
        state_with_streak["paper_streak_days"] = 5

        mock_state_response = MagicMock()
        mock_state_response.data = state_with_streak

        # Mock trades query - negative return (below threshold)
        mock_trades_response = MagicMock()
        mock_trades_response.data = [
            {"closed_at": "2024-01-10T00:00:00+00:00", "pnl_realized": -500.0}
        ]

        def table_mock(table_name):
            mock = MagicMock()
            if table_name == "v3_go_live_state":
                mock.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_state_response
                mock.update.return_value.eq.return_value.execute.return_value = MagicMock()
            elif table_name == "learning_trade_outcomes_v3":
                mock.select.return_value.eq.return_value.eq.return_value.gte.return_value.lte.return_value.execute.return_value = mock_trades_response
            elif table_name == "v3_go_live_runs":
                mock.insert.return_value.execute.return_value = MagicMock()
            return mock

        self.mock_client.table = table_mock

        service = GoLiveValidationService(self.mock_client)
        now = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        result = service.checkpoint_paper_streak(self.user_id, now=now, force=True)

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["streak_days"], 0)  # Reset
        self.assertEqual(result["streak_before"], 5)

    def test_checkpoint_idempotent_same_day(self):
        """Checkpoint skips if already run today."""
        from unittest.mock import MagicMock
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService
        from datetime import datetime, timezone

        # State with today's checkpoint already done
        state_already_checkpointed = self.default_state.copy()
        state_already_checkpointed["paper_last_checkpoint_at"] = "2024-01-15T08:00:00+00:00"
        state_already_checkpointed["paper_streak_days"] = 3

        mock_state_response = MagicMock()
        mock_state_response.data = state_already_checkpointed

        def table_mock(table_name):
            mock = MagicMock()
            if table_name == "v3_go_live_state":
                mock.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_state_response
            return mock

        self.mock_client.table = table_mock

        service = GoLiveValidationService(self.mock_client)
        now = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)  # Same day

        result = service.checkpoint_paper_streak(self.user_id, now=now)

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "already_checkpointed_today")
        self.assertEqual(result["streak_days"], 3)  # Unchanged

    def test_checkpoint_sets_paper_ready_on_threshold(self):
        """Checkpoint sets paper_ready when streak reaches threshold."""
        from unittest.mock import MagicMock, patch
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService
        from datetime import datetime, timezone

        # State at streak 13 (one away from threshold of 14)
        state_near_ready = self.default_state.copy()
        state_near_ready["paper_streak_days"] = 13

        mock_state_response = MagicMock()
        mock_state_response.data = state_near_ready

        # Mock trades query - passing return
        mock_trades_response = MagicMock()
        mock_trades_response.data = [
            {"closed_at": "2024-01-10T00:00:00+00:00", "pnl_realized": 5000.0}
        ]

        def table_mock(table_name):
            mock = MagicMock()
            if table_name == "v3_go_live_state":
                mock.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_state_response
                mock.update.return_value.eq.return_value.execute.return_value = MagicMock()
            elif table_name == "learning_trade_outcomes_v3":
                mock.select.return_value.eq.return_value.eq.return_value.gte.return_value.lte.return_value.execute.return_value = mock_trades_response
            elif table_name == "v3_go_live_runs":
                mock.insert.return_value.execute.return_value = MagicMock()
            return mock

        self.mock_client.table = table_mock

        service = GoLiveValidationService(self.mock_client)
        now = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        with patch.object(service, 'supabase', self.mock_client):
            result = service.checkpoint_paper_streak(self.user_id, now=now, force=True)

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["streak_days"], 14)  # 13 + 1 = threshold
        self.assertTrue(result["paper_ready"])
        self.assertTrue(result["paper_ready_from_streak"])


class TestRollingPaperStreakConfig(unittest.TestCase):
    """Tests for rolling paper streak configuration."""

    def test_default_window_days(self):
        """Default window is 14 days."""
        from packages.quantum.services.go_live_validation_service import PAPER_STREAK_WINDOW_DAYS
        self.assertEqual(PAPER_STREAK_WINDOW_DAYS, 14)

    def test_default_min_return(self):
        """Default minimum return is 2%."""
        from packages.quantum.services.go_live_validation_service import PAPER_STREAK_MIN_RETURN_PCT
        self.assertEqual(PAPER_STREAK_MIN_RETURN_PCT, 2.0)

    def test_default_required_days(self):
        """Default required consecutive days is 14."""
        from packages.quantum.services.go_live_validation_service import PAPER_STREAK_REQUIRED_DAYS
        self.assertEqual(PAPER_STREAK_REQUIRED_DAYS, 14)

    def test_checkpoint_mode_default(self):
        """Default checkpoint mode is 'rolling'."""
        from packages.quantum.services.go_live_validation_service import PAPER_STREAK_CHECKPOINT_MODE
        self.assertEqual(PAPER_STREAK_CHECKPOINT_MODE, "rolling")


class TestForwardCheckpointEvaluation(unittest.TestCase):
    """Tests for v4-L1 eval_paper_forward_checkpoint method."""

    def setUp(self):
        """Set up common mocks."""
        from unittest.mock import MagicMock
        self.mock_client = MagicMock()
        self.user_id = "test-user-uuid"

        # Default state with v4-L1 fields
        self.default_state = {
            "user_id": self.user_id,
            "paper_window_start": "2024-01-01T00:00:00+00:00",
            "paper_window_end": "2024-01-22T00:00:00+00:00",
            "paper_baseline_capital": 100000,
            "paper_consecutive_passes": 0,
            "paper_ready": False,
            "paper_window_days": 21,
            "paper_checkpoint_target": 10,
            "paper_checkpoint_last_run_at": None,
            "paper_fail_fast_triggered": False,
            "paper_fail_fast_reason": None,
            "historical_last_run_at": None,
            "historical_last_result": {},
            "overall_ready": False,
        }

    def test_checkpoint_pass_increments_streak(self):
        """Passing checkpoint increments paper_consecutive_passes."""
        from unittest.mock import MagicMock
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService
        from datetime import datetime, timezone

        state = self.default_state.copy()
        state["paper_consecutive_passes"] = 3

        mock_state_response = MagicMock()
        mock_state_response.data = state

        # Mock outcomes - good return (need 10% * progress to pass)
        # At day 10 of 21, progress ~0.43, target ~4.3%, so 5% return should pass
        mock_outcomes_response = MagicMock()
        mock_outcomes_response.data = [
            {"closed_at": "2024-01-05T00:00:00+00:00", "pnl_realized": 5000.0, "profit_pct": 5.0}
        ]

        def table_mock(table_name):
            mock = MagicMock()
            if table_name == "v3_go_live_state":
                mock.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_state_response
                mock.update.return_value.eq.return_value.execute.return_value = MagicMock()
            elif table_name == "learning_trade_outcomes_v3":
                mock.select.return_value.eq.return_value.eq.return_value.gte.return_value.lte.return_value.order.return_value.execute.return_value = mock_outcomes_response
            elif table_name == "v3_go_live_runs":
                mock.insert.return_value.execute.return_value = MagicMock()
            return mock

        self.mock_client.table = table_mock

        service = GoLiveValidationService(self.mock_client)
        now = datetime(2024, 1, 10, 12, 0, 0, tzinfo=timezone.utc)

        result = service.eval_paper_forward_checkpoint(self.user_id, now=now)

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["paper_consecutive_passes"], 4)  # 3 + 1
        self.assertEqual(result["streak_before"], 3)

    def test_checkpoint_miss_resets_streak(self):
        """Missing checkpoint resets streak to 0."""
        from unittest.mock import MagicMock
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService
        from datetime import datetime, timezone

        state = self.default_state.copy()
        state["paper_consecutive_passes"] = 5

        mock_state_response = MagicMock()
        mock_state_response.data = state

        # Mock outcomes - poor return (below pacing target)
        mock_outcomes_response = MagicMock()
        mock_outcomes_response.data = [
            {"closed_at": "2024-01-05T00:00:00+00:00", "pnl_realized": 100.0, "profit_pct": 0.1}
        ]

        def table_mock(table_name):
            mock = MagicMock()
            if table_name == "v3_go_live_state":
                mock.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_state_response
                mock.update.return_value.eq.return_value.execute.return_value = MagicMock()
            elif table_name == "learning_trade_outcomes_v3":
                mock.select.return_value.eq.return_value.eq.return_value.gte.return_value.lte.return_value.order.return_value.execute.return_value = mock_outcomes_response
            elif table_name == "v3_go_live_runs":
                mock.insert.return_value.execute.return_value = MagicMock()
            return mock

        self.mock_client.table = table_mock

        service = GoLiveValidationService(self.mock_client)
        now = datetime(2024, 1, 10, 12, 0, 0, tzinfo=timezone.utc)

        result = service.eval_paper_forward_checkpoint(self.user_id, now=now)

        self.assertEqual(result["status"], "miss")
        self.assertEqual(result["paper_consecutive_passes"], 0)
        self.assertEqual(result["streak_before"], 5)

    def test_checkpoint_deduplication(self):
        """Checkpoint skips if already run in same bucket."""
        from unittest.mock import MagicMock
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService
        from datetime import datetime, timezone

        state = self.default_state.copy()
        state["paper_checkpoint_last_run_at"] = "2024-01-10T08:00:00+00:00"
        state["paper_consecutive_passes"] = 5

        mock_state_response = MagicMock()
        mock_state_response.data = state

        def table_mock(table_name):
            mock = MagicMock()
            if table_name == "v3_go_live_state":
                mock.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_state_response
            return mock

        self.mock_client.table = table_mock

        service = GoLiveValidationService(self.mock_client)
        now = datetime(2024, 1, 10, 14, 0, 0, tzinfo=timezone.utc)  # Same day

        result = service.eval_paper_forward_checkpoint(self.user_id, now=now)

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "already_checkpointed_this_bucket")
        self.assertEqual(result["paper_consecutive_passes"], 5)  # Unchanged

    def test_fail_fast_on_drawdown(self):
        """Fail-fast triggers when max drawdown exceeds threshold."""
        from unittest.mock import MagicMock
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService
        from datetime import datetime, timezone

        state = self.default_state.copy()
        state["paper_consecutive_passes"] = 7

        mock_state_response = MagicMock()
        mock_state_response.data = state

        # Mock outcomes with severe drawdown
        mock_outcomes_response = MagicMock()
        mock_outcomes_response.data = [
            {"closed_at": "2024-01-03T00:00:00+00:00", "pnl_realized": 2000.0, "profit_pct": 2.0},
            {"closed_at": "2024-01-05T00:00:00+00:00", "pnl_realized": -5000.0, "profit_pct": -5.0},
        ]

        def table_mock(table_name):
            mock = MagicMock()
            if table_name == "v3_go_live_state":
                mock.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_state_response
                mock.update.return_value.eq.return_value.execute.return_value = MagicMock()
            elif table_name == "learning_trade_outcomes_v3":
                mock.select.return_value.eq.return_value.eq.return_value.gte.return_value.lte.return_value.order.return_value.execute.return_value = mock_outcomes_response
            elif table_name == "v3_go_live_runs":
                mock.insert.return_value.execute.return_value = MagicMock()
            return mock

        self.mock_client.table = table_mock

        service = GoLiveValidationService(self.mock_client)
        now = datetime(2024, 1, 10, 12, 0, 0, tzinfo=timezone.utc)

        result = service.eval_paper_forward_checkpoint(self.user_id, now=now)

        self.assertEqual(result["status"], "fail_fast")
        self.assertIn("drawdown", result["reason"])
        self.assertEqual(result["paper_consecutive_passes"], 0)
        self.assertEqual(result["streak_before"], 7)
        # Window should be restarted
        self.assertIn("new_window_start", result)
        self.assertIn("new_window_end", result)

    def test_fail_fast_on_total_return(self):
        """Fail-fast triggers when total return is too negative."""
        from unittest.mock import MagicMock
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService
        from datetime import datetime, timezone

        state = self.default_state.copy()
        state["paper_consecutive_passes"] = 4

        mock_state_response = MagicMock()
        mock_state_response.data = state

        # Mock outcomes with negative return (but not severe single drawdown)
        mock_outcomes_response = MagicMock()
        mock_outcomes_response.data = [
            {"closed_at": "2024-01-03T00:00:00+00:00", "pnl_realized": -1000.0, "profit_pct": -1.0},
            {"closed_at": "2024-01-05T00:00:00+00:00", "pnl_realized": -1500.0, "profit_pct": -1.5},
        ]

        def table_mock(table_name):
            mock = MagicMock()
            if table_name == "v3_go_live_state":
                mock.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_state_response
                mock.update.return_value.eq.return_value.execute.return_value = MagicMock()
            elif table_name == "learning_trade_outcomes_v3":
                mock.select.return_value.eq.return_value.eq.return_value.gte.return_value.lte.return_value.order.return_value.execute.return_value = mock_outcomes_response
            elif table_name == "v3_go_live_runs":
                mock.insert.return_value.execute.return_value = MagicMock()
            return mock

        self.mock_client.table = table_mock

        service = GoLiveValidationService(self.mock_client)
        now = datetime(2024, 1, 10, 12, 0, 0, tzinfo=timezone.utc)

        result = service.eval_paper_forward_checkpoint(self.user_id, now=now)

        self.assertEqual(result["status"], "fail_fast")
        self.assertIn("return", result["reason"])
        self.assertEqual(result["paper_consecutive_passes"], 0)

    def test_paper_ready_on_target_reached(self):
        """paper_ready set to True when checkpoint_target reached."""
        from unittest.mock import MagicMock
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService
        from datetime import datetime, timezone

        state = self.default_state.copy()
        state["paper_consecutive_passes"] = 9  # One away from target of 10
        state["paper_checkpoint_target"] = 10

        mock_state_response = MagicMock()
        mock_state_response.data = state

        # Mock good outcomes
        mock_outcomes_response = MagicMock()
        mock_outcomes_response.data = [
            {"closed_at": "2024-01-05T00:00:00+00:00", "pnl_realized": 5000.0, "profit_pct": 5.0}
        ]

        def table_mock(table_name):
            mock = MagicMock()
            if table_name == "v3_go_live_state":
                mock.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_state_response
                mock.update.return_value.eq.return_value.execute.return_value = MagicMock()
            elif table_name == "learning_trade_outcomes_v3":
                mock.select.return_value.eq.return_value.eq.return_value.gte.return_value.lte.return_value.order.return_value.execute.return_value = mock_outcomes_response
            elif table_name == "v3_go_live_runs":
                mock.insert.return_value.execute.return_value = MagicMock()
            return mock

        self.mock_client.table = table_mock

        service = GoLiveValidationService(self.mock_client)
        now = datetime(2024, 1, 10, 12, 0, 0, tzinfo=timezone.utc)

        result = service.eval_paper_forward_checkpoint(self.user_id, now=now)

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["paper_consecutive_passes"], 10)
        self.assertTrue(result["paper_ready"])

    def test_no_outcomes_is_miss(self):
        """No outcomes results in miss, not fail-fast."""
        from unittest.mock import MagicMock
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService
        from datetime import datetime, timezone

        state = self.default_state.copy()
        state["paper_consecutive_passes"] = 2

        mock_state_response = MagicMock()
        mock_state_response.data = state

        # No outcomes
        mock_outcomes_response = MagicMock()
        mock_outcomes_response.data = []

        def table_mock(table_name):
            mock = MagicMock()
            if table_name == "v3_go_live_state":
                mock.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_state_response
                mock.update.return_value.eq.return_value.execute.return_value = MagicMock()
            elif table_name == "learning_trade_outcomes_v3":
                mock.select.return_value.eq.return_value.eq.return_value.gte.return_value.lte.return_value.order.return_value.execute.return_value = mock_outcomes_response
            elif table_name == "v3_go_live_runs":
                mock.insert.return_value.execute.return_value = MagicMock()
            return mock

        self.mock_client.table = table_mock

        service = GoLiveValidationService(self.mock_client)
        now = datetime(2024, 1, 10, 12, 0, 0, tzinfo=timezone.utc)

        result = service.eval_paper_forward_checkpoint(self.user_id, now=now)

        self.assertEqual(result["status"], "miss")
        self.assertEqual(result["reason"], "no_outcomes_yet")
        # Should NOT be fail_fast
        self.assertNotEqual(result["status"], "fail_fast")

    def test_window_expiry_finalization(self):
        """Window expiry triggers finalization."""
        from unittest.mock import MagicMock
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService
        from datetime import datetime, timezone

        state = self.default_state.copy()
        state["paper_consecutive_passes"] = 10
        state["paper_checkpoint_target"] = 10

        mock_state_response = MagicMock()
        mock_state_response.data = state

        # Outcomes for finalization
        mock_outcomes_response = MagicMock()
        mock_outcomes_response.data = [
            {"closed_at": "2024-01-10T00:00:00+00:00", "pnl_realized": 8000.0}
        ]

        def table_mock(table_name):
            mock = MagicMock()
            if table_name == "v3_go_live_state":
                mock.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_state_response
                mock.update.return_value.eq.return_value.execute.return_value = MagicMock()
            elif table_name == "learning_trade_outcomes_v3":
                mock.select.return_value.eq.return_value.eq.return_value.gte.return_value.lte.return_value.execute.return_value = mock_outcomes_response
            elif table_name == "v3_go_live_runs":
                mock.insert.return_value.execute.return_value = MagicMock()
            return mock

        self.mock_client.table = table_mock

        service = GoLiveValidationService(self.mock_client)
        # Now is after window_end (2024-01-22)
        now = datetime(2024, 1, 25, 12, 0, 0, tzinfo=timezone.utc)

        result = service.eval_paper_forward_checkpoint(self.user_id, now=now)

        self.assertEqual(result["status"], "window_final")
        self.assertTrue(result["passed"])
        self.assertTrue(result["paper_ready"])
        self.assertIn("new_window_start", result)
        self.assertIn("new_window_end", result)


class TestCheckpointBucket(unittest.TestCase):
    """Tests for _checkpoint_bucket helper."""

    def test_daily_bucket_format(self):
        """Daily bucket returns YYYY-MM-DD format."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService
        from datetime import datetime, timezone
        from unittest.mock import MagicMock

        service = GoLiveValidationService(MagicMock())

        ts = datetime(2024, 1, 15, 14, 30, 45, tzinfo=timezone.utc)
        bucket = service._checkpoint_bucket(ts, cadence="daily")

        self.assertEqual(bucket, "2024-01-15")

    def test_same_day_same_bucket(self):
        """Different times on same day produce same bucket."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService
        from datetime import datetime, timezone
        from unittest.mock import MagicMock

        service = GoLiveValidationService(MagicMock())

        ts1 = datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc)
        ts2 = datetime(2024, 1, 15, 20, 0, 0, tzinfo=timezone.utc)

        self.assertEqual(
            service._checkpoint_bucket(ts1),
            service._checkpoint_bucket(ts2)
        )


class TestDrawdownCalculation(unittest.TestCase):
    """Tests for _compute_drawdown helper."""

    def test_no_outcomes_zero_drawdown(self):
        """No outcomes returns 0 drawdown."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService
        from unittest.mock import MagicMock

        service = GoLiveValidationService(MagicMock())
        dd = service._compute_drawdown([], 100000)

        self.assertEqual(dd, 0.0)

    def test_all_positive_no_drawdown(self):
        """All positive PnL has no significant drawdown."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService
        from unittest.mock import MagicMock

        service = GoLiveValidationService(MagicMock())
        outcomes = [
            {"closed_at": "2024-01-01", "pnl_realized": 1000},
            {"closed_at": "2024-01-02", "pnl_realized": 500},
            {"closed_at": "2024-01-03", "pnl_realized": 800},
        ]

        dd = service._compute_drawdown(outcomes, 100000)

        self.assertEqual(dd, 0.0)

    def test_drawdown_from_peak(self):
        """Drawdown calculated from peak."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService
        from unittest.mock import MagicMock

        service = GoLiveValidationService(MagicMock())
        # Peak at 2000, then drops to 2000-3000 = -1000
        outcomes = [
            {"closed_at": "2024-01-01", "pnl_realized": 2000},
            {"closed_at": "2024-01-02", "pnl_realized": -3000},
        ]

        dd = service._compute_drawdown(outcomes, 100000)

        # Drawdown = -1000 - 2000 = -3000, / 100000 = -0.03
        self.assertAlmostEqual(dd, -0.03, places=4)


if __name__ == "__main__":
    unittest.main()
