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

    def test_broker_prefix_requires_privileges(self):
        """Jobs starting with 'broker_' require privileges."""
        from public_tasks import _job_requires_live_privileges

        self.assertTrue(_job_requires_live_privileges("broker_sync"))
        self.assertTrue(_job_requires_live_privileges("broker_order"))

    def test_explicit_job_names_require_privileges(self):
        """Explicit job names in LIVE_EXEC_JOB_NAMES require privileges."""
        from public_tasks import _job_requires_live_privileges

        self.assertTrue(_job_requires_live_privileges("broker_sync"))
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


if __name__ == "__main__":
    unittest.main()
