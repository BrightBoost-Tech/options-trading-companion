"""
Unit tests for ``packages.quantum.scheduler._fire_task`` alerting.

Per Loud-Error Doctrine v1.0 / #72-H2. Covers:
    1. Signing failure produces ``scheduler_task_signing_failed`` alert
       with correct metadata.
    2. httpx exception produces ``scheduler_task_http_error`` alert.
    3. HTTP 4xx response produces ``scheduler_task_http_status_error``
       alert with ``status_code`` and ``response_body`` in metadata.
    4. HTTP 5xx response produces ``scheduler_task_http_status_error``
       alert (same shape).
    5. HTTP 2xx response produces NO alert.
    6. Response body is truncated to 2000 chars in metadata.
    7. When the lazy supabase singleton fails to initialize, the
       ``alert()`` helper fails-soft (no crash, no propagation).
    8. After the sentinel marks init as attempted, subsequent
       ``_fire_task`` calls do NOT retry creation — they short-circuit
       to the cached value (which may be None on persistent failure).
"""

import importlib
import unittest
from unittest.mock import MagicMock, patch


class _FireTaskTestBase(unittest.TestCase):
    """Reload scheduler module per test so the singleton starts fresh.

    The base setUp installs a known mock as ``_SUPABASE_FOR_ALERTS`` and
    flips ``_SUPABASE_INIT_ATTEMPTED`` to True so ``_get_supabase_for_alerts``
    short-circuits to the mock without trying to import
    ``get_admin_client``.
    """

    def setUp(self):
        from packages.quantum import scheduler
        from packages.quantum.observability import alerts
        importlib.reload(scheduler)
        self.scheduler = scheduler
        self.alerts = alerts
        self._supabase_mock = MagicMock()
        # Per #72-H3: the singleton lives in observability.alerts now,
        # not in scheduler. Both modules import _get_admin_supabase
        # from alerts, so patching alerts._ADMIN_SUPABASE controls
        # the value scheduler sees.
        alerts._ADMIN_SUPABASE = self._supabase_mock
        alerts._ADMIN_INIT_ATTEMPTED = True

    def _last_alert_record(self):
        """Helper: extract the dict passed to risk_alerts.insert()."""
        insert = self._supabase_mock.table.return_value.insert
        return insert.call_args.args[0]


class TestSigningFailureAlert(_FireTaskTestBase):
    def test_signing_failure_writes_alert_with_metadata(self):
        with patch(
            "packages.quantum.security.task_signing_v4.sign_task_request",
            side_effect=ValueError("missing TASK_SIGNING_KEYS"),
        ):
            self.scheduler._fire_task(
                endpoint="/tasks/policy-lab/eval",
                scope="tasks:policy_lab_eval",
                job_id="policy_lab_eval",
            )

        record = self._last_alert_record()
        self.assertEqual(record["alert_type"], "scheduler_task_signing_failed")
        self.assertEqual(record["severity"], "warning")
        self.assertIn("policy_lab_eval", record["message"])
        meta = record["metadata"]
        self.assertEqual(meta["job_name"], "policy_lab_eval")
        self.assertEqual(meta["scope"], "tasks:policy_lab_eval")
        self.assertIn("/tasks/policy-lab/eval", meta["endpoint_url"])
        self.assertEqual(meta["error_class"], "ValueError")
        self.assertIn("TASK_SIGNING_KEYS", meta["error_message"])


class TestHttpExceptionAlert(_FireTaskTestBase):
    def test_httpx_exception_writes_http_error_alert(self):
        with patch(
            "packages.quantum.security.task_signing_v4.sign_task_request",
            return_value={"X-Sig": "abc"},
        ), patch.object(
            self.scheduler.httpx,
            "post",
            side_effect=Exception("connection refused"),
        ):
            self.scheduler._fire_task(
                endpoint="/tasks/foo",
                scope="tasks:foo",
                job_id="foo_job",
            )

        record = self._last_alert_record()
        self.assertEqual(record["alert_type"], "scheduler_task_http_error")
        self.assertEqual(record["severity"], "warning")
        meta = record["metadata"]
        self.assertEqual(meta["job_name"], "foo_job")
        self.assertEqual(meta["error_class"], "Exception")
        self.assertIn("connection refused", meta["error_message"])


class TestHttpStatusErrorAlert(_FireTaskTestBase):
    def _stub_response(self, status_code: int, body: str):
        resp = MagicMock()
        resp.status_code = status_code
        resp.text = body
        return resp

    def test_4xx_response_writes_status_error_alert(self):
        resp = self._stub_response(404, "not found")
        with patch(
            "packages.quantum.security.task_signing_v4.sign_task_request",
            return_value={"X-Sig": "abc"},
        ), patch.object(self.scheduler.httpx, "post", return_value=resp):
            self.scheduler._fire_task(
                endpoint="/tasks/foo", scope="tasks:foo", job_id="foo_job"
            )
        record = self._last_alert_record()
        self.assertEqual(record["alert_type"], "scheduler_task_http_status_error")
        self.assertEqual(record["metadata"]["status_code"], 404)
        self.assertEqual(record["metadata"]["response_body"], "not found")

    def test_5xx_response_writes_status_error_alert(self):
        resp = self._stub_response(500, "Internal Server Error")
        with patch(
            "packages.quantum.security.task_signing_v4.sign_task_request",
            return_value={"X-Sig": "abc"},
        ), patch.object(self.scheduler.httpx, "post", return_value=resp):
            self.scheduler._fire_task(
                endpoint="/tasks/policy-lab/eval",
                scope="tasks:policy_lab_eval",
                job_id="policy_lab_eval",
            )
        record = self._last_alert_record()
        self.assertEqual(record["alert_type"], "scheduler_task_http_status_error")
        self.assertEqual(record["metadata"]["status_code"], 500)
        self.assertIn("Internal Server Error", record["metadata"]["response_body"])

    def test_response_body_truncated_to_2000_chars(self):
        resp = self._stub_response(500, "x" * 5000)
        with patch(
            "packages.quantum.security.task_signing_v4.sign_task_request",
            return_value={"X-Sig": "abc"},
        ), patch.object(self.scheduler.httpx, "post", return_value=resp):
            self.scheduler._fire_task(
                endpoint="/tasks/foo", scope="tasks:foo", job_id="foo_job"
            )
        record = self._last_alert_record()
        self.assertEqual(len(record["metadata"]["response_body"]), 2000)

    def test_2xx_response_writes_no_alert(self):
        resp = self._stub_response(200, "ok")
        with patch(
            "packages.quantum.security.task_signing_v4.sign_task_request",
            return_value={"X-Sig": "abc"},
        ), patch.object(self.scheduler.httpx, "post", return_value=resp):
            self.scheduler._fire_task(
                endpoint="/tasks/foo", scope="tasks:foo", job_id="foo_job"
            )
        # Insert should NOT have been called.
        self._supabase_mock.table.return_value.insert.assert_not_called()


class TestSupabaseSingletonFailureFailsSoft(unittest.TestCase):
    """Override the base setUp: simulate fresh state where the
    sentinel hasn't been flipped yet, so ``_get_supabase_for_alerts``
    actually attempts ``get_admin_client``.
    """

    def setUp(self):
        from packages.quantum import scheduler
        from packages.quantum.observability import alerts
        importlib.reload(scheduler)
        importlib.reload(alerts)
        self.scheduler = scheduler
        self.alerts = alerts
        # Singleton lives in alerts now; reset to fresh state.
        alerts._ADMIN_SUPABASE = None
        alerts._ADMIN_INIT_ATTEMPTED = False

    def test_singleton_failure_does_not_crash_fire_task(self):
        with patch(
            "packages.quantum.jobs.handlers.utils.get_admin_client",
            side_effect=RuntimeError("supabase down"),
        ), patch(
            "packages.quantum.security.task_signing_v4.sign_task_request",
            side_effect=ValueError("signing fail"),
        ):
            # MUST NOT raise.
            self.scheduler._fire_task(
                endpoint="/tasks/foo", scope="tasks:foo", job_id="foo_job"
            )
        # Singleton stayed None; sentinel flipped to True.
        self.assertIsNone(self.alerts._ADMIN_SUPABASE)
        self.assertTrue(self.alerts._ADMIN_INIT_ATTEMPTED)

    def test_sentinel_prevents_retry_after_init_failure(self):
        """After first init attempt fails, subsequent calls must NOT
        re-attempt ``get_admin_client``. Verifies the sentinel works.
        """
        get_admin_mock = MagicMock(side_effect=RuntimeError("supabase down"))
        with patch(
            "packages.quantum.jobs.handlers.utils.get_admin_client",
            get_admin_mock,
        ), patch(
            "packages.quantum.security.task_signing_v4.sign_task_request",
            side_effect=ValueError("signing fail"),
        ):
            self.scheduler._fire_task(
                endpoint="/tasks/foo", scope="tasks:foo", job_id="foo_job"
            )
            self.scheduler._fire_task(
                endpoint="/tasks/bar", scope="tasks:bar", job_id="bar_job"
            )

        self.assertEqual(
            get_admin_mock.call_count, 1,
            "Sentinel should prevent retry after init failure",
        )


if __name__ == "__main__":
    unittest.main()
