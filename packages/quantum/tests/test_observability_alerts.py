"""
Unit tests for ``packages.quantum.observability.alerts.alert``.

Per Loud-Error Doctrine v1.0. Covers:
    1. Happy path — insert succeeds, no exception, no fallback log.
    2. Failure path — insert raises; helper catches, logs via
       ``logger.exception``, does not propagate.
    3. Severity validation — invalid severities default to ``warning``
       with a logged warning. Valid severities pass through.
    4. Optional fields — ``user_id``, ``position_id``, ``symbol``,
       ``metadata`` all work when None and when populated.
    5. Message truncation — messages longer than 500 chars are
       truncated.
    6. Recursion prevention — when called from inside another except
       block, the helper does not recurse on its own write failure.
    7. ``supabase=None`` fail-soft — no crash; logs and returns.
"""

import logging
import unittest
from unittest.mock import MagicMock

from packages.quantum.observability.alerts import alert


class TestAlertHappyPath(unittest.TestCase):
    def test_insert_called_with_required_fields(self):
        supabase = MagicMock()
        alert(
            supabase,
            alert_type="test_event",
            message="hello",
            severity="info",
        )
        supabase.table.assert_called_once_with("risk_alerts")
        insert = supabase.table.return_value.insert
        insert.assert_called_once()
        record = insert.call_args.args[0]
        self.assertEqual(record["alert_type"], "test_event")
        self.assertEqual(record["message"], "hello")
        self.assertEqual(record["severity"], "info")
        self.assertEqual(record["metadata"], {})
        self.assertNotIn("user_id", record)
        self.assertNotIn("position_id", record)
        self.assertNotIn("symbol", record)
        insert.return_value.execute.assert_called_once()

    def test_optional_fields_populate_when_provided(self):
        supabase = MagicMock()
        alert(
            supabase,
            alert_type="t",
            message="m",
            severity="warning",
            metadata={"k": "v"},
            user_id="u-123",
            position_id="p-456",
            symbol="AAPL",
        )
        record = supabase.table.return_value.insert.call_args.args[0]
        self.assertEqual(record["metadata"], {"k": "v"})
        self.assertEqual(record["user_id"], "u-123")
        self.assertEqual(record["position_id"], "p-456")
        self.assertEqual(record["symbol"], "AAPL")


class TestAlertFailurePath(unittest.TestCase):
    def test_insert_failure_does_not_propagate(self):
        supabase = MagicMock()
        supabase.table.return_value.insert.return_value.execute.side_effect = (
            RuntimeError("db down")
        )
        # MUST NOT raise.
        alert(
            supabase,
            alert_type="t",
            message="m",
            severity="warning",
        )

    def test_insert_failure_logs_exception_with_intended_fields(self):
        supabase = MagicMock()
        supabase.table.return_value.insert.return_value.execute.side_effect = (
            RuntimeError("db down")
        )
        with self.assertLogs(
            "packages.quantum.observability.alerts", level=logging.ERROR
        ) as logs:
            alert(
                supabase,
                alert_type="my_event",
                message="something failed",
                severity="critical",
            )
        # logger.exception emits at ERROR level
        self.assertTrue(
            any("alert_write_failed" in rec.getMessage() for rec in logs.records)
        )

    def test_alert_is_idempotent_on_recursion(self):
        """If alert() is called from inside another exception handler,
        and its own insert fails, it MUST NOT call alert() again.
        Verified by ensuring the supabase mock is touched exactly once.
        """
        supabase = MagicMock()
        supabase.table.return_value.insert.return_value.execute.side_effect = (
            RuntimeError("db down")
        )
        try:
            raise ValueError("outer error")
        except ValueError:
            alert(
                supabase,
                alert_type="recursion_test",
                message="outer except",
                severity="warning",
            )
        # Exactly one .table("risk_alerts") call — no recursion.
        self.assertEqual(supabase.table.call_count, 1)


class TestSeverityValidation(unittest.TestCase):
    def test_valid_severities_pass_through(self):
        for sev in ("info", "warning", "critical"):
            supabase = MagicMock()
            alert(supabase, alert_type="t", message="m", severity=sev)
            record = supabase.table.return_value.insert.call_args.args[0]
            self.assertEqual(record["severity"], sev)

    def test_invalid_severity_defaults_to_warning(self):
        supabase = MagicMock()
        with self.assertLogs(
            "packages.quantum.observability.alerts", level=logging.WARNING
        ) as logs:
            alert(supabase, alert_type="t", message="m", severity="critcal")
        record = supabase.table.return_value.insert.call_args.args[0]
        self.assertEqual(record["severity"], "warning")
        self.assertTrue(
            any("invalid severity" in rec.getMessage() for rec in logs.records)
        )

    def test_invalid_severity_debug_defaults_to_warning(self):
        supabase = MagicMock()
        alert(supabase, alert_type="t", message="m", severity="debug")
        record = supabase.table.return_value.insert.call_args.args[0]
        self.assertEqual(record["severity"], "warning")


class TestMessageTruncation(unittest.TestCase):
    def test_message_truncated_to_500_chars(self):
        supabase = MagicMock()
        long_message = "x" * 1000
        alert(supabase, alert_type="t", message=long_message, severity="info")
        record = supabase.table.return_value.insert.call_args.args[0]
        self.assertEqual(len(record["message"]), 500)

    def test_short_message_unchanged(self):
        supabase = MagicMock()
        alert(supabase, alert_type="t", message="short", severity="info")
        record = supabase.table.return_value.insert.call_args.args[0]
        self.assertEqual(record["message"], "short")


class TestSupabaseNoneFailSoft(unittest.TestCase):
    def test_supabase_none_does_not_raise(self):
        # MUST NOT raise.
        alert(None, alert_type="t", message="m", severity="info")

    def test_supabase_none_logs_skipped_warning(self):
        with self.assertLogs(
            "packages.quantum.observability.alerts", level=logging.WARNING
        ) as logs:
            alert(None, alert_type="my_event", message="m", severity="info")
        self.assertTrue(
            any("alert_skipped_no_supabase" in rec.getMessage() for rec in logs.records)
        )


class TestGetAdminSupabase(unittest.TestCase):
    """Per #72-H3: shared lazy admin singleton with sentinel
    semantics, extracted from scheduler.py."""

    def setUp(self):
        # Reset module state per test
        import importlib
        from packages.quantum.observability import alerts
        importlib.reload(alerts)
        self.alerts = alerts

    def test_caches_after_first_call(self):
        from unittest.mock import patch
        client_mock = MagicMock()
        with patch(
            "packages.quantum.jobs.handlers.utils.get_admin_client",
            return_value=client_mock,
        ) as factory:
            r1 = self.alerts._get_admin_supabase()
            r2 = self.alerts._get_admin_supabase()
        self.assertIs(r1, client_mock)
        self.assertIs(r2, client_mock)
        factory.assert_called_once()

    def test_does_not_retry_after_init_failure(self):
        from unittest.mock import patch
        factory = MagicMock(side_effect=RuntimeError("supabase down"))
        with patch(
            "packages.quantum.jobs.handlers.utils.get_admin_client",
            factory,
        ):
            r1 = self.alerts._get_admin_supabase()
            r2 = self.alerts._get_admin_supabase()
        self.assertIsNone(r1)
        self.assertIsNone(r2)
        # Sentinel must prevent retry.
        self.assertEqual(factory.call_count, 1)
        self.assertTrue(self.alerts._ADMIN_INIT_ATTEMPTED)


if __name__ == "__main__":
    unittest.main()
