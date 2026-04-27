
import unittest
import time
from unittest.mock import MagicMock
from packages.quantum.services.provider_guardrails import CircuitBreaker, guardrail, CircuitState

class TestProviderGuardrails(unittest.TestCase):
    def test_circuit_breaker_logic(self):
        breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=1)

        # 1. Closed State
        self.assertEqual(breaker.state, CircuitState.CLOSED)
        self.assertTrue(breaker.allow_request())

        # 2. Record Failures
        breaker.record_failure()
        self.assertEqual(breaker.state, CircuitState.CLOSED)

        breaker.record_failure()
        self.assertEqual(breaker.state, CircuitState.OPEN)

        # 3. Open State Rejection
        self.assertFalse(breaker.allow_request())

        # 4. Timeout Recovery
        time.sleep(1.1)
        self.assertTrue(breaker.allow_request()) # Should transition to HALF_OPEN
        self.assertEqual(breaker.state, CircuitState.HALF_OPEN)

        # 5. Success Closes
        breaker.record_success()
        self.assertEqual(breaker.state, CircuitState.CLOSED)

    def test_guardrail_decorator(self):
        # Mock function that fails n times then succeeds
        self.call_count = 0

        @guardrail(provider="test_provider", max_retries=2, backoff_base=0.01, fallback="FALLBACK")
        def flaky_service():
            self.call_count += 1
            if self.call_count < 3:
                raise ValueError("Fail")
            return "SUCCESS"

        # Should retry twice (calls: 1=fail, 2=fail, 3=success)
        result = flaky_service()
        self.assertEqual(result, "SUCCESS")
        self.assertEqual(self.call_count, 3)

    def test_guardrail_fallback(self):
        self.call_count = 0

        @guardrail(provider="test_fail", max_retries=1, backoff_base=0.01, fallback="FALLBACK")
        def failing_service():
            self.call_count += 1
            raise ValueError("Always Fail")

        result = failing_service()
        self.assertEqual(result, "FALLBACK")
        self.assertEqual(self.call_count, 2) # Initial + 1 Retry

class TestGuardrailAlerts(unittest.TestCase):
    """Per #72-H3 + Loud-Error Doctrine v1.0: @guardrail must write
    risk_alerts on Path A (circuit OPEN) and Path B (retries
    exhausted)."""

    def setUp(self):
        # Pre-arm the shared admin singleton with a controlled mock.
        from packages.quantum.observability import alerts
        self._alerts_module = alerts
        self._supabase_mock = MagicMock()
        alerts._ADMIN_SUPABASE = self._supabase_mock
        alerts._ADMIN_INIT_ATTEMPTED = True

        # Reset per-provider breakers so prior tests don't pollute.
        from packages.quantum.services.provider_guardrails import _BREAKERS
        _BREAKERS.clear()

    def _last_alert_record(self):
        return self._supabase_mock.table.return_value.insert.call_args.args[0]

    def test_path_a_circuit_open_writes_alert(self):
        """When breaker is OPEN, the decorator returns fallback AND
        writes a circuit_open alert."""
        @guardrail(provider="testprov", max_retries=0, backoff_base=0.01, fallback="FB")
        def fn():
            raise ValueError("trip")

        # Drive the breaker to OPEN by exhausting threshold (default 5).
        for _ in range(6):
            fn()
        # Reset insert mock to look at NEXT call only.
        self._supabase_mock.table.return_value.insert.reset_mock()

        # Now the breaker should be OPEN → next call hits Path A.
        result = fn()
        self.assertEqual(result, "FB")
        record = self._last_alert_record()
        self.assertEqual(record["alert_type"], "testprov_circuit_open")
        self.assertEqual(record["severity"], "warning")
        self.assertEqual(record["metadata"]["circuit_state"], "OPEN")
        self.assertEqual(record["metadata"]["provider"], "testprov")
        self.assertIn("fn", record["metadata"]["function_name"])

    def test_path_b_retries_exhausted_writes_alert(self):
        @guardrail(provider="testprov", max_retries=1, backoff_base=0.01, fallback="FB")
        def fn(symbol):
            raise RuntimeError("boom")

        result = fn("AAPL")
        self.assertEqual(result, "FB")
        record = self._last_alert_record()
        self.assertEqual(record["alert_type"], "testprov_retries_exhausted")
        self.assertEqual(record["severity"], "warning")
        self.assertEqual(record["metadata"]["error_class"], "RuntimeError")
        self.assertIn("boom", record["metadata"]["error_message"])
        self.assertEqual(record["metadata"]["max_retries"], 1)
        self.assertFalse(record["metadata"]["is_rate_limit"])
        self.assertIn("'AAPL'", record["metadata"]["args"])

    def test_alert_metadata_skips_self_for_methods(self):
        class Svc:
            @guardrail(provider="testprov", max_retries=0, backoff_base=0.01, fallback=None)
            def fetch(self, symbol):
                raise RuntimeError("boom")

        svc = Svc()
        svc.fetch("AAPL")
        record = self._last_alert_record()
        # args metadata should contain 'AAPL' but not the Svc instance repr.
        self.assertIn("'AAPL'", record["metadata"]["args"])
        # The repr of a Svc instance would start with '<' — make sure
        # we didn't capture self.
        self.assertFalse(
            record["metadata"]["args"].startswith("<"),
            f"args should not start with self repr: {record['metadata']['args']}",
        )

    def test_429_rate_limit_detected_in_metadata(self):
        @guardrail(provider="testprov", max_retries=1, backoff_base=0.01, fallback="FB")
        def fn():
            raise Exception("HTTP 429 Too Many Requests")

        fn()
        record = self._last_alert_record()
        self.assertTrue(record["metadata"]["is_rate_limit"])

    def test_alert_write_failure_does_not_propagate(self):
        """If alert() itself fails, the decorator must still return
        the fallback rather than raising."""
        self._supabase_mock.table.return_value.insert.return_value.execute.side_effect = (
            RuntimeError("alert insert down")
        )

        @guardrail(provider="testprov", max_retries=0, backoff_base=0.01, fallback="FB")
        def fn():
            raise RuntimeError("boom")

        # MUST NOT raise.
        result = fn()
        self.assertEqual(result, "FB")

    def test_2xx_success_writes_no_alert(self):
        @guardrail(provider="testprov", max_retries=2, backoff_base=0.01, fallback="FB")
        def fn():
            return "ok"

        result = fn()
        self.assertEqual(result, "ok")
        self._supabase_mock.table.return_value.insert.assert_not_called()


if __name__ == '__main__':
    unittest.main()
