"""
Provider Guardrails Service
Implements Circuit Breaker, Retries, and Rate Limit handling for external providers.
"""
import re
import time
import inspect
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
# Security v4 masking: catches DSN / sk- / JWT / AWS / Plaid secret shapes.
from packages.quantum.security.masking import sanitize_message

logger = logging.getLogger(__name__)

# SECURITY (v1.7 V17-5): every @guardrail-wrapped call is a Polygon request
# whose URL query carries apiKey=<secret> (packages/quantum/market_data.py).
# On a requests exception, str(exc) embeds that URL verbatim — the same class
# as the market_data.py:~610 fix. Redact credential-bearing query params AND
# any known configured provider secret BEFORE the text is logged, stored in an
# alert, or truncated. Only the logged/stored text changes; control flow and
# the fallback are untouched.
#
# Redacts <secret-param>=<value> up to the next '&' or whitespace. Covers the
# Polygon apiKey form plus api_key / apikey / token / access_token / secret /
# password / key. The (?<![A-Za-z0-9_]) guard anchors the param name to a
# boundary so a benign 'sortkey=' is not caught by the bare 'key' branch,
# while 'apiKey=' (matched by the api[_-]?key branch) still is.
_SECRET_QUERY_PARAM_RE = re.compile(
    r'(?<![A-Za-z0-9_])'
    r'((?:api[_-]?key|access[_-]?token|api[_-]?secret|token|secret|password|key)=)'
    r'[^&\s]+',
    re.IGNORECASE,
)

# Attribute names a bound provider client commonly stores its secret under, so
# the exact configured value can be redacted verbatim even outside a query
# string (best-effort; never raises).
_COMMON_SECRET_ATTRS = (
    "api_key", "apikey", "api_secret", "secret_key",
    "secret", "token", "access_token", "password",
)


def _bound_instance_secrets(args) -> list:
    """Best-effort: pull configured secret values off the bound provider
    instance (``args[0]`` for a decorated method, e.g. PolygonService.api_key)
    so they can be redacted verbatim. Never raises."""
    secrets: list = []
    if not args:
        return secrets
    inst = args[0]
    for attr in _COMMON_SECRET_ATTRS:
        try:
            val = getattr(inst, attr, None)
        except Exception:
            val = None
        if isinstance(val, str) and val:
            secrets.append(val)
    return secrets


def _redact_secrets(text, extra_secrets=()) -> Optional[str]:
    """Redact credential-bearing substrings from provider text BEFORE logging,
    alert storage, or truncation. Layered defence:

      1. verbatim replacement of any KNOWN configured secret value (catches it
         wherever it appears, even outside a query string);
      2. ``<secret-param>=<value>`` query-string redaction (the Polygon
         ``apiKey=<secret>`` URL shape, plus URL-encoded / rotated values the
         verbatim pass cannot match);
      3. ``masking.sanitize_message`` for DSN / sk- / JWT / AWS / Plaid shapes.
    """
    if not text:
        return text
    out = str(text)
    for secret in extra_secrets:
        if isinstance(secret, str) and secret:
            out = out.replace(secret, "[REDACTED]")
    out = _SECRET_QUERY_PARAM_RE.sub(r"\1[REDACTED]", out)
    out = sanitize_message(out)
    return out

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
    - If func is a class method, skips args[0] (self/cls)

    Method-detection: inspect the first parameter name of ``func``.
    If it's ``self`` or ``cls``, treat as a class method and skip
    ``args[0]``. Otherwise include all positional args.

    This correctly handles all the cases qualname-based heuristics
    struggled with:

    - Module-level function ``def fn(symbol)`` → first param is
      ``symbol`` → not a method (include args[0])
    - Class method ``def fetch(self, symbol)`` → first param is
      ``self`` → method (skip args[0])
    - Nested class method (``outer.<locals>.Class.method``) → first
      param is ``self`` → method (skip args[0])
    - Static method ``def fn(symbol)`` defined in a class → first
      param is ``symbol`` → not a method (include args[0]) — correct
      because @staticmethod-decorated funcs receive no implicit
      first arg
    - Callables without a discoverable signature → fall back to
      treating as not-a-method (include all args)
    """
    is_method = False
    try:
        first = next(iter(inspect.signature(func).parameters.values()), None)
        is_method = first is not None and first.name in ("self", "cls")
    except (TypeError, ValueError):
        # Builtins / partials / weird callables may not have a
        # discoverable signature. Fall back to non-method treatment.
        is_method = False
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
                safe_args = _redact_secrets(
                    _repr_args_for_alert(func, args, kwargs),
                    _bound_instance_secrets(args),
                )
                alert(
                    _get_admin_supabase(),
                    alert_type=f"{provider}_circuit_open",
                    severity="warning",
                    message=f"Circuit OPEN for {provider}, returning fallback for {func.__qualname__}",
                    metadata={
                        "provider": provider,
                        "function_name": func.__qualname__,
                        "circuit_state": breaker.state.value,
                        "args": safe_args,
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
            # SECURITY (v1.7 V17-5): str(last_exception) on a Polygon call can
            # embed the request URL whose query carries apiKey=<secret>. Redact
            # BEFORE logging / alert-storage / truncation (see _redact_secrets).
            instance_secrets = _bound_instance_secrets(args)
            safe_error = (
                _redact_secrets(str(last_exception), instance_secrets)
                if last_exception else None
            )
            safe_args = _redact_secrets(
                _repr_args_for_alert(func, args, kwargs), instance_secrets
            )
            logger.error(f"Provider {provider} failed after retries: {safe_error}")
            alert(
                _get_admin_supabase(),
                alert_type=f"{provider}_retries_exhausted",
                severity="warning",
                message=f"Provider {provider} failed after retries for {func.__qualname__}: {safe_error}",
                metadata={
                    "provider": provider,
                    "function_name": func.__qualname__,
                    "max_retries": max_retries,
                    "is_rate_limit": is_rate_limit,
                    "error_class": type(last_exception).__name__ if last_exception else None,
                    "error_message": safe_error[:500] if safe_error else None,
                    "args": safe_args,
                },
            )
            return fallback

        return wrapper
    return decorator
