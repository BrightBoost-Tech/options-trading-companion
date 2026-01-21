"""
Integration tests for v4-L2 Go-Live Gate Enforcement in enqueue_job_run.

Tests that live-exec jobs are properly gated based on ops state and user readiness.
"""

import unittest
import sys
import os
from unittest.mock import MagicMock, patch

# Add parent path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestEnqueueGateEnforcement(unittest.TestCase):
    """Tests for gate enforcement in enqueue_job_run."""

    def setUp(self):
        """Set up common mocks."""
        self.mock_job_run_store_patcher = patch("public_tasks.JobRunStore")
        self.mock_job_run_store = self.mock_job_run_store_patcher.start()

        # Default mock for create_or_get_cancelled
        self.mock_store_instance = MagicMock()
        self.mock_store_instance.create_or_get_cancelled.return_value = {
            "id": "test-job-run-id",
            "status": "cancelled",
        }
        self.mock_store_instance.create_or_get.return_value = {
            "id": "test-job-run-id",
            "status": "pending",
        }
        self.mock_store_instance.client = MagicMock()
        self.mock_job_run_store.return_value = self.mock_store_instance

    def tearDown(self):
        """Clean up patches."""
        self.mock_job_run_store_patcher.stop()

    @patch("packages.quantum.services.go_live_validation_service.GoLiveValidationService")
    @patch("packages.quantum.ops_endpoints.get_global_ops_control")
    @patch("packages.quantum.ops_endpoints.is_trading_paused")
    def test_live_job_cancelled_when_paper_mode(
        self, mock_is_paused, mock_get_ops, mock_service_cls
    ):
        """Live order job is cancelled when ops mode is paper."""
        from public_tasks import enqueue_job_run

        # Not paused, but paper mode
        mock_is_paused.return_value = (False, None)
        mock_get_ops.return_value = {
            "paused": False,
            "mode": "paper",
        }
        mock_service_cls.return_value.get_or_create_state.return_value = {
            "paper_ready": True,
            "overall_ready": True,
        }

        result = enqueue_job_run(
            job_name="live_order_submit",
            idempotency_key="test-key",
            payload={"user_id": "test-user-uuid"}
        )

        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["cancelled_reason"], "go_live_gate")
        self.assertEqual(result["cancelled_detail"], "mode_is_paper_only")

    @patch("packages.quantum.services.go_live_validation_service.GoLiveValidationService")
    @patch("packages.quantum.ops_endpoints.get_global_ops_control")
    @patch("packages.quantum.ops_endpoints.is_trading_paused")
    def test_live_job_cancelled_when_micro_live_not_ready(
        self, mock_is_paused, mock_get_ops, mock_service_cls
    ):
        """Live order job is cancelled when micro_live mode but paper_ready=False."""
        from public_tasks import enqueue_job_run

        mock_is_paused.return_value = (False, None)
        mock_get_ops.return_value = {
            "paused": False,
            "mode": "micro_live",
        }
        mock_service_cls.return_value.get_or_create_state.return_value = {
            "paper_ready": False,
            "overall_ready": False,
        }

        result = enqueue_job_run(
            job_name="live_order_submit",
            idempotency_key="test-key",
            payload={"user_id": "test-user-uuid"}
        )

        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["cancelled_reason"], "go_live_gate")
        self.assertEqual(result["cancelled_detail"], "paper_milestones_incomplete")

    @patch("packages.quantum.services.go_live_validation_service.GoLiveValidationService")
    @patch("packages.quantum.ops_endpoints.get_global_ops_control")
    @patch("packages.quantum.ops_endpoints.is_trading_paused")
    def test_live_job_requires_manual_approval_in_micro_live(
        self, mock_is_paused, mock_get_ops, mock_service_cls
    ):
        """Live order job requires manual approval when micro_live mode and paper_ready=True."""
        from public_tasks import enqueue_job_run

        mock_is_paused.return_value = (False, None)
        mock_get_ops.return_value = {
            "paused": False,
            "mode": "micro_live",
        }
        mock_service_cls.return_value.get_or_create_state.return_value = {
            "paper_ready": True,
            "overall_ready": False,
        }

        result = enqueue_job_run(
            job_name="live_order_submit",
            idempotency_key="test-key",
            payload={"user_id": "test-user-uuid"}
        )

        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["cancelled_reason"], "manual_approval_required")
        self.assertEqual(result["cancelled_detail"], "micro_live_restricted")

    @patch("packages.quantum.services.go_live_validation_service.GoLiveValidationService")
    @patch("packages.quantum.ops_endpoints.get_global_ops_control")
    @patch("packages.quantum.ops_endpoints.is_trading_paused")
    def test_live_job_cancelled_when_live_mode_not_ready(
        self, mock_is_paused, mock_get_ops, mock_service_cls
    ):
        """Live order job is cancelled when live mode but overall_ready=False."""
        from public_tasks import enqueue_job_run

        mock_is_paused.return_value = (False, None)
        mock_get_ops.return_value = {
            "paused": False,
            "mode": "live",
        }
        mock_service_cls.return_value.get_or_create_state.return_value = {
            "paper_ready": True,
            "overall_ready": False,
        }

        result = enqueue_job_run(
            job_name="live_order_submit",
            idempotency_key="test-key",
            payload={"user_id": "test-user-uuid"}
        )

        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["cancelled_reason"], "go_live_gate")
        self.assertEqual(result["cancelled_detail"], "historical_validation_failed")

    @patch("public_tasks.enqueue_idempotent")
    @patch("packages.quantum.services.go_live_validation_service.GoLiveValidationService")
    @patch("packages.quantum.ops_endpoints.get_global_ops_control")
    @patch("packages.quantum.ops_endpoints.is_trading_paused")
    def test_live_job_allowed_when_live_mode_ready(
        self, mock_is_paused, mock_get_ops, mock_service_cls, mock_enqueue
    ):
        """Live order job is allowed when live mode and overall_ready=True."""
        from public_tasks import enqueue_job_run

        mock_is_paused.return_value = (False, None)
        mock_get_ops.return_value = {
            "paused": False,
            "mode": "live",
        }
        mock_service_cls.return_value.get_or_create_state.return_value = {
            "paper_ready": True,
            "overall_ready": True,
        }
        mock_enqueue.return_value = {"job_id": "rq-job-id"}

        result = enqueue_job_run(
            job_name="live_order_submit",
            idempotency_key="test-key",
            payload={"user_id": "test-user-uuid"}
        )

        # Should have proceeded to normal enqueue
        self.assertEqual(result["status"], "pending")
        self.assertIsNotNone(result["rq_job_id"])
        mock_enqueue.assert_called_once()

    @patch("packages.quantum.ops_endpoints.is_trading_paused")
    def test_live_job_cancelled_when_missing_user_id(self, mock_is_paused):
        """Live order job is cancelled when user_id is missing from payload."""
        from public_tasks import enqueue_job_run

        mock_is_paused.return_value = (False, None)

        result = enqueue_job_run(
            job_name="live_order_submit",
            idempotency_key="test-key",
            payload={}  # No user_id
        )

        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["cancelled_reason"], "go_live_gate")
        self.assertEqual(result["cancelled_detail"], "missing_user_id_for_gate")

    @patch("packages.quantum.ops_endpoints.is_trading_paused")
    def test_live_job_cancelled_when_user_id_is_all(self, mock_is_paused):
        """Live job is cancelled when user_id is 'all' (batch job)."""
        from public_tasks import enqueue_job_run

        mock_is_paused.return_value = (False, None)

        result = enqueue_job_run(
            job_name="live_order_submit",
            idempotency_key="test-key",
            payload={"user_id": "all"}
        )

        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["cancelled_reason"], "go_live_gate")
        self.assertEqual(result["cancelled_detail"], "missing_user_id_for_gate")


class TestNonLiveJobsNotGated(unittest.TestCase):
    """Tests that non-live jobs are not affected by go-live gate."""

    def setUp(self):
        """Set up common mocks."""
        self.mock_job_run_store_patcher = patch("public_tasks.JobRunStore")
        self.mock_job_run_store = self.mock_job_run_store_patcher.start()

        self.mock_store_instance = MagicMock()
        self.mock_store_instance.create_or_get.return_value = {
            "id": "test-job-run-id",
            "status": "pending",
        }
        self.mock_job_run_store.return_value = self.mock_store_instance

    def tearDown(self):
        """Clean up patches."""
        self.mock_job_run_store_patcher.stop()

    @patch("public_tasks.enqueue_idempotent")
    @patch("packages.quantum.ops_endpoints.is_trading_paused")
    def test_suggestions_job_not_gated(self, mock_is_paused, mock_enqueue):
        """suggestions_open job is not affected by go-live gate."""
        from public_tasks import enqueue_job_run

        mock_is_paused.return_value = (False, None)
        mock_enqueue.return_value = {"job_id": "rq-job-id"}

        # Even without user readiness checks, this should proceed
        result = enqueue_job_run(
            job_name="suggestions_open",
            idempotency_key="test-key",
            payload={"user_id": "test-user"}
        )

        self.assertEqual(result["status"], "pending")
        mock_enqueue.assert_called_once()

    @patch("public_tasks.enqueue_idempotent")
    @patch("packages.quantum.ops_endpoints.is_trading_paused")
    def test_learning_job_not_gated(self, mock_is_paused, mock_enqueue):
        """learning_ingest job is not affected by go-live gate."""
        from public_tasks import enqueue_job_run

        mock_is_paused.return_value = (False, None)
        mock_enqueue.return_value = {"job_id": "rq-job-id"}

        result = enqueue_job_run(
            job_name="learning_ingest",
            idempotency_key="test-key",
            payload={}
        )

        self.assertEqual(result["status"], "pending")
        mock_enqueue.assert_called_once()

    @patch("public_tasks.enqueue_idempotent")
    @patch("packages.quantum.ops_endpoints.is_trading_paused")
    def test_broker_sync_not_gated_by_go_live(self, mock_is_paused, mock_enqueue):
        """broker_sync job is NOT gated by go-live gate (read-only broker job)."""
        from public_tasks import enqueue_job_run

        # Not paused, paper mode - live_order_submit would be blocked
        # but broker_sync should proceed
        mock_is_paused.return_value = (False, None)
        mock_enqueue.return_value = {"job_id": "rq-job-id"}

        result = enqueue_job_run(
            job_name="broker_sync",
            idempotency_key="test-key",
            payload={"user_id": "test-user"}
        )

        # broker_sync should proceed normally (not blocked by go-live gate)
        self.assertEqual(result["status"], "pending")
        mock_enqueue.assert_called_once()


class TestPauseGateStillFirst(unittest.TestCase):
    """Tests that pause gate still takes precedence over go-live gate."""

    def setUp(self):
        """Set up common mocks."""
        self.mock_job_run_store_patcher = patch("public_tasks.JobRunStore")
        self.mock_job_run_store = self.mock_job_run_store_patcher.start()

        self.mock_store_instance = MagicMock()
        self.mock_store_instance.create_or_get_cancelled.return_value = {
            "id": "test-job-run-id",
            "status": "cancelled",
        }
        self.mock_job_run_store.return_value = self.mock_store_instance

    def tearDown(self):
        """Clean up patches."""
        self.mock_job_run_store_patcher.stop()

    @patch("packages.quantum.ops_endpoints.is_trading_paused")
    def test_pause_gate_blocks_before_go_live_gate(self, mock_is_paused):
        """Pause gate blocks job before go-live gate is checked."""
        from public_tasks import enqueue_job_run

        # Paused globally
        mock_is_paused.return_value = (True, "System maintenance")

        result = enqueue_job_run(
            job_name="live_order_submit",
            idempotency_key="test-key",
            payload={"user_id": "test-user-uuid"}
        )

        # Should be blocked by pause gate, not go-live gate
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["cancelled_reason"], "global_ops_pause")
        self.assertEqual(result["cancelled_detail"], "System maintenance")
        # Backward compat: pause_reason field should also be present
        self.assertEqual(result["pause_reason"], "System maintenance")

    @patch("packages.quantum.ops_endpoints.is_trading_paused")
    def test_broker_sync_still_respects_pause_gate(self, mock_is_paused):
        """broker_sync (read-only) still respects pause gate even though not go-live gated."""
        from public_tasks import enqueue_job_run

        # Paused globally
        mock_is_paused.return_value = (True, "System maintenance")

        result = enqueue_job_run(
            job_name="broker_sync",
            idempotency_key="test-key",
            payload={"user_id": "test-user-uuid"}
        )

        # broker_sync should still be blocked by pause gate
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["cancelled_reason"], "global_ops_pause")
        self.assertEqual(result["cancelled_detail"], "System maintenance")
        self.assertEqual(result["pause_reason"], "System maintenance")


if __name__ == "__main__":
    unittest.main()
