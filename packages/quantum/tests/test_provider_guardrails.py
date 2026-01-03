
import unittest
import time
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

if __name__ == '__main__':
    unittest.main()
