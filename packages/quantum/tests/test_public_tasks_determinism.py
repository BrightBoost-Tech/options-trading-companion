import unittest
from unittest.mock import MagicMock, patch, ANY
import json
import os
from datetime import datetime, timezone
import asyncio

# Mock imports that might cause side effects or require env vars
with patch.dict(os.environ, {
    "AUTOPROMOTE_ENABLED": "1",
    "SHADOW_CHECKPOINT_ENABLED": "1",
    "NEXT_PUBLIC_SUPABASE_URL": "http://localhost:54321",
    "NEXT_PUBLIC_SUPABASE_ANON_KEY": "test"
}):
    from packages.quantum.public_tasks import task_validation_autopromote_cohort
    from packages.quantum.public_tasks_models import ValidationAutopromoteCohortPayload
    from packages.quantum.security.task_signing_v4 import TaskSignatureResult

class TestPublicTasksSerialization(unittest.TestCase):
    def setUp(self):
        self.mock_auth = TaskSignatureResult(
            valid=True,
            actor="test_actor",
            scope="tasks:validation_autopromote_cohort",
            key_id="test_key"
        )
        self.user_id = "00000000-0000-0000-0000-000000000000"
        self.payload = ValidationAutopromoteCohortPayload(user_id=self.user_id)

    @patch.dict(os.environ, {"AUTOPROMOTE_ENABLED": "1", "SHADOW_CHECKPOINT_ENABLED": "1"})
    @patch("packages.quantum.ops_endpoints.get_global_ops_control")
    @patch("packages.quantum.jobs.handlers.utils.get_admin_client")
    @patch("packages.quantum.public_tasks._get_shadow_cohorts")
    def test_autopromote_cohort_serialization(self, mock_get_cohorts, mock_get_client, mock_get_ops):
        # Setup mocks
        mock_get_ops.return_value = {"mode": "paper", "paused": False}

        # Mock cohorts
        mock_get_cohorts.return_value = [{
            "name": "test_cohort",
            "target_return_pct": 0.1,  # Float that needs canonicalization
            "fail_fast_drawdown_pct": -0.03
        }]

        # Mock Supabase
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Mock history query (shadow_cohort_daily)
        # We need enough history to trigger promotion
        mock_history_resp = MagicMock()
        mock_history_resp.data = [
            {
                "winner_cohort": "test_cohort",
                "winner_would_fail_fast": False,
                "winner_return_pct": 0.05,
                "bucket_date": "2024-01-03"
            },
            {
                "winner_cohort": "test_cohort",
                "winner_would_fail_fast": False,
                "winner_return_pct": 0.04,
                "bucket_date": "2024-01-02"
            },
            {
                "winner_cohort": "test_cohort",
                "winner_would_fail_fast": False,
                "winner_return_pct": 0.03,
                "bucket_date": "2024-01-01"
            }
        ]

        # Mock GoLiveValidationService state check
        # Mocking the service instance created inside the function is hard because it's instantiated locally
        # But we can mock the supabase queries it makes.

        # The function queries:
        # 1. shadow_cohort_daily (history)
        # 2. v3_go_live_state (current policy) -> via service.get_or_create_state
        # 3. v3_go_live_state (update) -> PROMOTION

        # We need to structure the mock client to handle these chained calls

        # 1. history query
        mock_client.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = mock_history_resp

        # 2. current state query (for anti-churn)
        # We need to simulate the service.get_or_create_state call which queries v3_go_live_state
        mock_state_resp = MagicMock()
        mock_state_resp.data = {"paper_forward_policy_cohort": "old_cohort"}

        # The function uses `GoLiveValidationService(supabase)` which calls `supabase.table("v3_go_live_state").select("*").eq("user_id", user_id).single().execute()`
        # But `task_validation_autopromote_cohort` also calls `supabase.table("shadow_cohort_daily")...` directly.

        # Define table mocks to be reused
        mock_shadow_table = MagicMock()
        mock_shadow_table.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = mock_history_resp

        mock_state_table = MagicMock()
        mock_state_table.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_state_resp
        mock_state_table.update.return_value.eq.return_value.execute.return_value = MagicMock()

        # To distinguish between table calls, we can use side_effect on `table`
        def table_side_effect(name):
            if name == "shadow_cohort_daily":
                return mock_shadow_table
            elif name == "v3_go_live_state":
                return mock_state_table
            return MagicMock()

        mock_client.table.side_effect = table_side_effect

        # Run the task
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(task_validation_autopromote_cohort(self.payload, self.mock_auth))

        # Verify result
        self.assertTrue(result.get("promoted"), f"Should be promoted but got: {result}")

        # Verify the update call
        self.assertTrue(mock_state_table.update.called)

        call_args = mock_state_table.update.call_args
        args, _ = call_args
        update_payload = args[0]

        # Check paper_forward_policy
        policy_json = update_payload["paper_forward_policy"]

        # Check if it contains float as string (Canonical) or float as number (Standard)
        # The test target has 0.1 which standard dumps as 0.1
        # Canonical bytes decode -> "0.100000"

        # We verify that "0.100000" string is present in the JSON string
        self.assertIn('"target_return_pct":"0.100000"', policy_json, "Should use canonical float formatting (stringified)")
        self.assertNotIn('"target_return_pct": 0.1', policy_json, "Should not use standard float formatting")

if __name__ == '__main__':
    unittest.main()
