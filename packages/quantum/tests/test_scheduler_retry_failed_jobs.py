"""
Unit tests for ``packages.quantum.scheduler._retry_failed_jobs``.

Per #72-H2a. Covers:
    1. Import path — the canonical ``get_admin_client`` import resolves.
    2. Retry branch — ``failed_retryable`` rows with ``attempt < 2``
       are re-queued.
    3. Dead-letter branch — ``failed_retryable`` rows with
       ``attempt >= 2`` are promoted to ``dead_lettered`` + a
       ``risk_alerts`` row is written.
    4. Outer-except alert — function-level errors produce an
       ``auto_retry_scan_failed`` alert per Loud-Error Doctrine v1.0.
    5. Outer-except no-crash — the scheduler stays alive even when
       the scan internals raise.
"""

import importlib
import unittest
from unittest.mock import MagicMock, patch


class TestCanonicalImportPath(unittest.TestCase):
    def test_get_admin_client_is_importable(self):
        """The fix swaps to ``get_admin_client`` from the canonical
        ``packages.quantum.jobs.handlers.utils`` location. This test
        guards against future regressions of the same shape (a missing
        module name in a critical function)."""
        from packages.quantum.jobs.handlers.utils import get_admin_client
        self.assertTrue(callable(get_admin_client))


class _RetryFailedJobsTestBase(unittest.TestCase):
    """Reload scheduler per test; pre-arm the alert singleton so
    ``_get_supabase_for_alerts`` short-circuits to a controlled mock."""

    def setUp(self):
        from packages.quantum import scheduler
        from packages.quantum.observability import alerts
        importlib.reload(scheduler)
        self.scheduler = scheduler
        self.alerts = alerts
        self._alert_supabase_mock = MagicMock()
        # Per #72-H3: singleton lives in observability.alerts, not
        # scheduler. Patch there so _get_admin_supabase() returns mock.
        alerts._ADMIN_SUPABASE = self._alert_supabase_mock
        alerts._ADMIN_INIT_ATTEMPTED = True


class TestRetryBranch(_RetryFailedJobsTestBase):
    def _run_with_row(self, row):
        client = MagicMock()
        # Chain 1: SELECT failed_retryable WHERE attempt < 2 → 1 row
        retry_chain = (
            client.table.return_value
            .select.return_value
            .eq.return_value
            .gte.return_value
            .lt.return_value
            .limit.return_value
        )
        retry_chain.execute.return_value.data = [row]
        # Chain 2: SELECT failed_retryable WHERE attempt >= 2 → empty
        deadletter_chain = (
            client.table.return_value
            .select.return_value
            .eq.return_value
            .gte.return_value
            .limit.return_value
        )
        deadletter_chain.execute.return_value.data = []

        with patch(
            "packages.quantum.jobs.handlers.utils.get_admin_client",
            return_value=client,
        ):
            self.scheduler._retry_failed_jobs()
        return client

    def test_retry_eligible_row_is_requeued(self):
        """A5-2 (2026-07-17): the re-queue update now ALSO carries the
        internal_retry provenance annotation in payload.origin_retries —
        the exact-dict assertion is widened to field-level asserts."""
        client = self._run_with_row(
            {
                "id": "job-1",
                "job_name": "alpaca_order_sync",
                "attempt": 1,
                "payload": {"trigger_ts": "t0", "origin": {"origin": "scheduler"}},
            }
        )

        update_call = client.table.return_value.update
        update_dicts = [
            call.args[0] for call in update_call.call_args_list
            if call.args and isinstance(call.args[0], dict)
            and call.args[0].get("status") == "queued"
        ]
        self.assertEqual(len(update_dicts), 1)
        fields = update_dicts[0]
        self.assertEqual(fields["attempt"], 2)  # incremented from 1
        self.assertIsNone(fields["locked_by"])
        self.assertIsNone(fields["locked_at"])

        # A5-2: internal_retry annotation appended; creator origin immutable.
        payload = fields["payload"]
        self.assertEqual(payload["trigger_ts"], "t0")
        self.assertEqual(payload["origin"], {"origin": "scheduler"})
        retries = payload["origin_retries"]
        self.assertEqual(len(retries), 1)
        self.assertEqual(retries[0]["origin"], "internal_retry")
        self.assertEqual(retries[0]["trigger_actor_class"], "scheduler_auto_retry")
        self.assertEqual(retries[0]["parent_job_run_id"], "job-1")

    def test_origin_stamp_failure_never_blocks_requeue(self):
        """A stamp error must degrade to the legacy update (no payload key),
        never skip the retry — provenance is metadata, not a gate."""
        with patch(
            "packages.quantum.jobs.origin.append_retry_origin",
            side_effect=RuntimeError("stamp boom"),
        ):
            client = self._run_with_row(
                {"id": "job-2", "job_name": "validation_eval", "attempt": 0,
                 "payload": {}}
            )

        update_call = client.table.return_value.update
        update_dicts = [
            call.args[0] for call in update_call.call_args_list
            if call.args and isinstance(call.args[0], dict)
            and call.args[0].get("status") == "queued"
        ]
        self.assertEqual(len(update_dicts), 1)
        fields = update_dicts[0]
        self.assertEqual(fields["attempt"], 1)
        self.assertNotIn("payload", fields)  # stamp failed → legacy shape


class TestDeadLetterBranch(_RetryFailedJobsTestBase):
    def test_exhausted_row_is_dead_lettered_with_alert(self):
        client = MagicMock()
        retry_chain = (
            client.table.return_value
            .select.return_value
            .eq.return_value
            .gte.return_value
            .lt.return_value
            .limit.return_value
        )
        retry_chain.execute.return_value.data = []
        deadletter_chain = (
            client.table.return_value
            .select.return_value
            .eq.return_value
            .gte.return_value
            .limit.return_value
        )
        deadletter_chain.execute.return_value.data = [
            {
                "id": "job-x",
                "job_name": "validation_eval",
                "attempt": 2,
                "result": {"error": "boom"},
                "finished_at": "2026-04-26T18:00:00Z",
            },
        ]

        with patch(
            "packages.quantum.jobs.handlers.utils.get_admin_client",
            return_value=client,
        ):
            self.scheduler._retry_failed_jobs()

        update_call = client.table.return_value.update
        update_call.assert_any_call({"status": "dead_lettered"})

        # The legacy risk_alerts write inside _retry_failed_jobs uses
        # client.table("risk_alerts").insert(...) — verify it fired.
        insert_call = client.table.return_value.insert
        # At least one insert call should reference job_dead_lettered
        any_dead_letter_alert = any(
            (call.args and isinstance(call.args[0], dict)
             and call.args[0].get("alert_type") == "job_dead_lettered")
            for call in insert_call.call_args_list
        )
        self.assertTrue(
            any_dead_letter_alert,
            "Dead-letter branch must insert a risk_alerts row "
            "with alert_type='job_dead_lettered'",
        )


class TestOuterExceptAlert(_RetryFailedJobsTestBase):
    def test_function_level_error_writes_doctrine_alert(self):
        # Make get_admin_client itself raise — this hits the outer except.
        with patch(
            "packages.quantum.jobs.handlers.utils.get_admin_client",
            side_effect=RuntimeError("supabase down"),
        ):
            # MUST NOT raise — function is a scheduled callback.
            self.scheduler._retry_failed_jobs()

        # The alert helper writes via _SUPABASE_FOR_ALERTS, which we
        # pre-armed in setUp.
        insert = self._alert_supabase_mock.table.return_value.insert
        insert.assert_called_once()
        record = insert.call_args.args[0]
        self.assertEqual(record["alert_type"], "auto_retry_scan_failed")
        self.assertEqual(record["severity"], "warning")
        self.assertIn("supabase down", record["message"])
        self.assertEqual(record["metadata"]["error_class"], "RuntimeError")
        self.assertEqual(
            record["metadata"]["function"], "_retry_failed_jobs"
        )

    def test_function_level_error_does_not_crash(self):
        with patch(
            "packages.quantum.jobs.handlers.utils.get_admin_client",
            side_effect=RuntimeError("supabase down"),
        ):
            # Must return normally — APScheduler's BackgroundScheduler
            # would otherwise mark the job as failed and stop scheduling.
            result = self.scheduler._retry_failed_jobs()
        # _retry_failed_jobs has no return; assert it didn't raise.
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
