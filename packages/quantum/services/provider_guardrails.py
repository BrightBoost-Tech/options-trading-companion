"""
Provider Guardrails Service
Implements Circuit Breaker, Retries, and Rate Limit handling for external providers.
"""
import time
import logging
import functools
from typing import Callable, Any, Dict, Optional
from enum import Enum
from datetime import datetime, timedelta

# Loud-Error Doctrine v1.0: alerts on circuit-open and retry-exhausted
# paths so silent fallbacks become queryable. See
# docs/loud_error_doctrine.md anti-pattern 2 (log-only swallow with
# default return).
from packages.quantum.observability.alerts import alert, _get_admin_supabase

logger = logging.getLogger(__name__)

class CircuitState(Enum):
    CLOSED = "CLOSED"     # Normal operation
    OPEN = "OPEN"         # Circuit broken (fail fast / cache only)
    HALF_OPEN = "HALF_OPEN" # Testing recovery

class ProviderStatus(Enum):
    OK = "OK"
    RATE_LIMITED = "RATE_LIMITED"
    DOWN = "DOWN"

class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout

        self.state = CircuitState.CLOSED
        self.failures = 0
        self.last_failure_time = 0.0
        self.total_failures = 0
        self.total_rate_limits = 0

    def record_success(self):
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED
            self.failures = 0
            logger.info("Circuit CLOSED (Recovered)")
        elif self.state == CircuitState.CLOSED:
            self.failures = 0 # Reset on success in closed state too

    def record_failure(self, is_rate_limit: bool = False):
        self.failures += 1
        self.total_failures += 1
        self.last_failure_time = time.time()

        if is_rate_limit:
            self.total_rate_limits += 1

        if self.state == CircuitState.CLOSED and self.failures >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.warning(f"Circuit OPENED after {self.failures} failures")

        elif self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.OPEN
            logger.warning("Circuit RE-OPENED (Recovery failed)")

    def allow_request(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                logger.info("Circuit HALF_OPEN (Probing)")
                return True
            return False

        return True # HALF_OPEN allows 1 request (simplified: allows all until success/fail logic handles it)

    def get_metrics(self) -> Dict[str, Any]:
        return {
            "state": self.state.value,
            "failures_current_window": self.failures,
            "total_failures": self.total_failures,
            "total_rate_limits": self.total_rate_limits
        }

# Global registry of circuit breakers by provider
_BREAKERS: Dict[str, CircuitBreaker] = {}

def get_circuit_breaker(provider: str) -> CircuitBreaker:
    if provider not in _BREAKERS:
        _BREAKERS[provider] = CircuitBreaker()
    return _BREAKERS[provider]

class GuardrailException(Exception):
    def __init__(self, message: str, reason_code: str):
        super().__init__(message)
        self.reason_code = reason_code


def _repr_args_for_alert(func, args, kwargs, per_arg_cap=200, total_cap=500):
    """Stringify call arguments for risk_alerts metadata.

    - Per-arg repr capped at per_arg_cap chars
    - Joined string capped at total_cap chars
    - If func is a class method, skips args[0] (self)

    Method-detection heuristic: Python sets ``__qualname__`` to
    ``Class.method`` for class methods and to
    ``outer.<locals>.inner`` for nested functions. Both contain
    ``.``, so a naive ``'.' in __qualname__`` check would
    false-positive on nested functions. We additionally require
    ``<locals>`` to be ABSENT, which correctly distinguishes:

    - Module-level function ``fn`` → no ``.`` → not a method
    - Class method ``Class.method`` → has ``.``, no ``<locals>`` → method
    - Nested function ``outer.<locals>.inner`` → has ``.`` AND
      ``<locals>`` → not a method

    The heuristic still misses one edge case: classes defined inside
    a function (``outer.<locals>.Class.method``). If that pattern
    starts appearing under ``@guardrail``, switch to
    ``inspect.signature(func).parameters`` first-name == 'self'.
    """
    qualname = getattr(func, "__qualname__", "") or ""
    is_method = "." in qualname and "<locals>" not in qualname
    positional = args[1:] if (is_method and args) else args
    parts: list = []
    for a in positional:
        try:
            parts.append(repr(a)[:per_arg_cap])
        except Exception:
            parts.append("<unrepr-able>")
    for k, v in kwargs.items():
        try:
            parts.append(f"{k}={repr(v)[:per_arg_cap]}")
        except Exception:
            parts.append(f"{k}=<unrepr-able>")
    return ", ".join(parts)[:total_cap]


def guardrail(provider: str, max_retries: int = 2, backoff_base: float = 1.0, fallback: Any = None):
    """
    Decorator to wrap provider calls with circuit breaker and retries.

    Args:
        provider: Name of the provider (e.g., 'polygon')
        max_retries: Number of retries on recoverable errors
        backoff_base: Base seconds for exponential backoff
        fallback: Value to return if execution fails (None, {}, etc.)
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            breaker = get_circuit_breaker(provider)

            # 1. Check Circuit Breaker
            if not breaker.allow_request():
                # Circuit Open -> Fail Fast
                logger.warning(f"Circuit OPEN for {provider}, using fallback.")
                alert(
                    _get_admin_supabase(),
                    alert_type=f"{provider}_circuit_open",
                    severity="warning",
                    message=f"Circuit OPEN for {provider}, returning fallback for {func.__qualname__}",
                    metadata={
                        "provider": provider,
                        "function_name": func.__qualname__,
                        "circuit_state": breaker.state.value,
                        "args": _repr_args_for_alert(func, args, kwargs),
                    },
                )
                return fallback

            # 2. Try Execution with Retries
            retries = 0
            last_exception = None

            while retries <= max_retries:
                try:
                    result = func(*args, **kwargs)
                    breaker.record_success()
                    return result

                except Exception as e:
                    last_exception = e
                    is_rate_limit = "429" in str(e) or "Rate limit" in str(e) or "Too Many Requests" in str(e)

                    # Log
                    # logger.warning(f"Attempt {retries+1}/{max_retries+1} failed for {provider}: {e}")

                    # Update Breaker logic
                    if is_rate_limit:
                        # Rate limits count towards failure threshold
                        breaker.record_failure(is_rate_limit=True)
                    else:
                        # Other errors might strictly be failures
                        breaker.record_failure()

                    # Check if we should retry
                    # We retry on Rate Limits (with backoff) and potentially connection errors
                    # But if circuit trips mid-retries, we should probably stop?
                    # Simpler: just check breaker status again? No, let's finish retries unless we want to be strict.

                    if retries < max_retries:
                        sleep_time = backoff_base * (2 ** retries)
                        # Jitter could be added here
                        time.sleep(sleep_time)
                        retries += 1
                    else:
                        break

            # 3. Final Failure
            logger.error(f"Provider {provider} failed after retries: {last_exception}")
            alert(
                _get_admin_supabase(),
                alert_type=f"{provider}_retries_exhausted",
                severity="warning",
                message=f"Provider {provider} failed after retries for {func.__qualname__}: {last_exception}",
                metadata={
                    "provider": provider,
                    "function_name": func.__qualname__,
                    "max_retries": max_retries,
                    "is_rate_limit": is_rate_limit,
                    "error_class": type(last_exception).__name__ if last_exception else None,
                    "error_message": str(last_exception)[:500] if last_exception else None,
                    "args": _repr_args_for_alert(func, args, kwargs),
                },
            )
            return fallback

        return wrapper
    return decorator
