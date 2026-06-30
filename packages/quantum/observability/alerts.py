"""
Observability primitives per Loud-Error Doctrine v1.0.

Reference: docs/loud_error_doctrine.md
"""

import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

# "high" added 2026-06-11 (v5-A4): the table has stored 'high' rows from
# direct writers (risk_envelope concentration warns) since inception, and
# the H11 baseline sweep queries severity IN ('critical','high') — this
# helper silently DOWNGRADING an attempted 'high' to 'warning' was the same
# severity-map gap class as the ops-health 'critical' omission.
_VALID_SEVERITIES = ("info", "warning", "high", "critical")

# ── External risk-alert egress (loss-protection, 2026-06-29) ──────────
# Risk categories whose alert() row ALSO egresses to the external ops
# webhook so an UNATTENDED loss-protection event reaches the operator
# off-platform — not merely a DB row that no one is watching. Kept to a
# TIGHT allowlist so routine high-severity rows (e.g. risk_envelope
# concentration warns that the table stores as 'high') do NOT spam the
# channel: only genuine brake/force-close/disarm events egress. Categories
# already egressed by ops_health_service (the 'ops_' prefixed types it
# writes via its own webhook channel) are deliberately ABSENT here to avoid
# double-sends.
_RISK_EGRESS_ALERT_TYPES = frozenset(
    {
        "force_close",  # brake fire / per-symbol loss / cohort stop force-close
        "exit_protection_disarmed",  # #1046 close re-arm budget tripped
        "job_dead_lettered",  # scheduler retries exhausted
        "loss_per_symbol_protection_degraded",  # per-symbol loss unmarkable
        "stop_loss_protection_degraded",  # position stop unmarkable
        "job_succeeded_with_errors",  # A4 silent-failure detector (ops_health)
    }
)

# alert() severity vocabulary → the ops sender's severity vocabulary. The
# sender's internal severity_order knows only critical/error/warning, so a
# 'high' MUST map to 'error' or it is suppressed below min-severity.
_OPS_SEVERITY_MAP = {"critical": "critical", "high": "error"}


def _maybe_egress_risk_alert(
    *,
    alert_type: str,
    severity: str,
    message: str,
    metadata: dict | None,
    symbol: str | None,
    position_id: str | None,
) -> None:
    """Best-effort: push a critical/high RISK alert out the ops webhook.

    Fires ONLY for the tight ``_RISK_EGRESS_ALERT_TYPES`` allowlist AND only
    at severity ``critical``/``high`` (warn/info NEVER egress — anti-spam).
    Reuses the existing ``send_ops_alert_v2`` sender via a FUNCTION-LOCAL
    import so there is no import cycle at module load (ops_health_service
    imports ``alert`` only lazily, inside its own sender). Egress is gated by
    the sender's own ``OPS_ALERT_WEBHOOK_URL`` check, so this is a safe no-op
    (``suppressed_reason="no_webhook"``) when the URL is unset — no
    duplicated suppression logic here. ANY exception is swallowed: egress
    must never break the risk path, the caller, or the authoritative DB row
    that was already written before this call.
    """
    if alert_type not in _RISK_EGRESS_ALERT_TYPES:
        return
    if severity not in ("critical", "high"):
        return
    try:
        from packages.quantum.services.ops_health_service import (
            send_ops_alert_v2,
        )

        # client=None → the sender's risk_alerts channel (its Channel 1) is
        # SKIPPED, so no second/duplicate DB row is written; only the
        # Slack-compatible webhook (its Channel 2) runs. The row alert()
        # already inserted remains the single source of truth.
        send_ops_alert_v2(
            alert_type=alert_type,
            message=message,
            details={
                **(metadata or {}),
                **({"symbol": symbol} if symbol else {}),
                **({"position_id": position_id} if position_id else {}),
            },
            severity=_OPS_SEVERITY_MAP.get(severity, "warning"),
            client=None,
        )
    except Exception:
        # Egress is strictly best-effort; the DB write already happened.
        logger.warning(
            "risk_alert_egress_failed",
            extra={"egress_alert_type": alert_type, "egress_severity": severity},
            exc_info=True,
        )


# ── risk_alerts insert retry (transient-disconnect only, 2026-06-30) ──────
# The observed failure signature for the risk_alerts write is a stale-keepalive
# "Server disconnected" / RemoteProtocolError after the connection has sat idle
# — NOT pool exhaustion. A right-sized retry-with-backoff recovers that write
# without any durable buffer/queue (over-engineering for this signature). Only
# transient disconnects retry; every other exception falls straight through to
# the unchanged logger.exception fallback so a genuine query/schema error is
# never silently spun on.
_ALERT_INSERT_RETRY_BACKOFFS = (0.25, 0.5)  # two retries after the first try


def _is_transient_disconnect(exc: BaseException | None) -> bool:
    """True when ``exc`` looks like a recoverable stale-keepalive server
    disconnect (httpx/httpcore ``RemoteProtocolError`` or a
    "Server disconnected"/"RemoteProtocol" message), False otherwise.

    Matched by CLASS NAME across the MRO (so a missing httpx/httpcore import
    can never break the alert path) plus a message-substring fallback. Pool
    exhaustion / real PostgREST errors do NOT match and are not retried.
    """
    if exc is None:
        return False
    for cls in type(exc).__mro__:
        if cls.__name__ == "RemoteProtocolError":
            return True
    text = str(exc)
    return "Server disconnected" in text or "RemoteProtocol" in text


def alert(
    supabase: Any,
    *,
    alert_type: str,
    message: str,
    severity: str = "info",
    metadata: dict | None = None,
    user_id: str | None = None,
    position_id: str | None = None,
    symbol: str | None = None,
) -> None:
    """Write a risk_alerts row. Never raises.

    Per Loud-Error Doctrine v1.0. The canonical primitive for
    capturing production exceptions that don't re-raise: every
    catching site that doesn't re-raise should call this helper
    before returning a default value.

    On insert failure, falls back to ``logger.exception`` with
    structured fields capturing the intended alert. Does NOT
    recurse (Valid pattern 5 in the doctrine).

    Args:
        supabase: Supabase client (must have INSERT permission on
            risk_alerts). If None, the call no-ops with a logger
            warning — caller should supply one whenever possible.
        alert_type: Snake_case identifier
            (e.g. ``"equity_state_alpaca_account_failed"``).
        message: Human-readable summary, capped at 500 chars.
        severity: One of ``"info"``, ``"warning"``, ``"high"``,
            ``"critical"``. Invalid values default to ``"warning"``
            with a logged warning.
        metadata: Optional structured context dict (becomes the
            ``metadata`` jsonb column).
        user_id: Optional UUID for user-scoping the alert.
        position_id: Optional UUID for position-scoping.
        symbol: Optional ticker for symbol-scoping.
    """
    if severity not in _VALID_SEVERITIES:
        logger.warning(
            "alert: invalid severity %r, defaulting to 'warning'",
            severity,
        )
        severity = "warning"

    if supabase is None:
        logger.warning(
            "alert_skipped_no_supabase",
            extra={
                "intended_alert_type": alert_type,
                "intended_severity": severity,
                "intended_message": message[:200],
            },
        )
        return

    record: dict[str, Any] = {
        "alert_type": alert_type,
        "severity": severity,
        "message": message[:500],
        "metadata": metadata or {},
    }
    if user_id is not None:
        record["user_id"] = user_id
    if position_id is not None:
        record["position_id"] = position_id
    if symbol is not None:
        record["symbol"] = symbol

    # Authoritative risk_alerts write with a right-sized retry on transient
    # stale-keepalive disconnects (loss-protection, 2026-06-30). ONLY transient
    # disconnects retry; any other exception breaks straight out to the
    # unchanged logger.exception fallback. On a transient disconnect that
    # EXHAUSTS the retries, an extra DISTINCT loss marker (alert_lost_after_
    # retries) makes the dropped row visible — important because, with
    # OPS_ALERT_WEBHOOK_URL unset on this deploy, a lost insert otherwise
    # reaches NOWHERE.
    written = False
    last_exc: BaseException | None = None
    retried = False
    for backoff in (0.0,) + _ALERT_INSERT_RETRY_BACKOFFS:
        if backoff:
            retried = True
            time.sleep(backoff)
        try:
            supabase.table("risk_alerts").insert(record).execute()
            written = True
            break
        except Exception as exc:  # noqa: BLE001 — classified below
            last_exc = exc
            if not _is_transient_disconnect(exc):
                break  # non-transient → do not retry; fall to the fallback

    if not written:
        # FINAL fallback (unchanged behavior): structured exception log of the
        # intended alert. Re-raise into an ``except`` so logger.exception keeps
        # the original traceback.
        try:
            if last_exc is not None:
                raise last_exc
        except Exception:
            logger.exception(
                "alert_write_failed",
                extra={
                    "intended_alert_type": alert_type,
                    "intended_severity": severity,
                    "intended_message": message[:200],
                },
            )
        if retried:
            logger.error(
                "alert_lost_after_retries",
                extra={
                    "intended_alert_type": alert_type,
                    "intended_severity": severity,
                    "intended_message": message[:200],
                    "retries": len(_ALERT_INSERT_RETRY_BACKOFFS),
                    "error": str(last_exc)[:200] if last_exc is not None else None,
                },
            )

    # AFTER the authoritative DB insert (source of truth): best-effort
    # external egress for the critical/high RISK loss-protection categories
    # only. Self-contained + exception-swallowing — never blocks the DB write
    # nor breaks the caller. No-op for every non-allowlisted / non-critical
    # alert (anti-spam) and when OPS_ALERT_WEBHOOK_URL is unset.
    _maybe_egress_risk_alert(
        alert_type=alert_type,
        severity=severity,
        message=message,
        metadata=metadata,
        symbol=symbol,
        position_id=position_id,
    )


# ── Shared admin Supabase singleton ───────────────────────────────
# Used by modules that need to write risk_alerts but don't carry
# a Supabase client through their call signatures (e.g., scheduler-
# side cron handlers, decorator-wrapped functions). Modules that
# DO have a client in scope should pass it directly to alert(...)
# rather than reaching for this helper.

_ADMIN_SUPABASE: Any = None
_ADMIN_INIT_ATTEMPTED = False


def _get_admin_supabase():
    """Return a lazy admin Supabase client suitable for risk_alerts writes.

    State machine:
      - Initial: ``_ADMIN_SUPABASE=None``,
        ``_ADMIN_INIT_ATTEMPTED=False``
      - After successful init: ``_ADMIN_SUPABASE=Client``,
        ``_ADMIN_INIT_ATTEMPTED=True``
      - After failed init: ``_ADMIN_SUPABASE=None``,
        ``_ADMIN_INIT_ATTEMPTED=True``

    Once init is attempted (success or failure), no further attempts
    happen until process restart. This prevents log spam during
    sustained Supabase outages and keeps cost low on the alert hot
    path.

    The ``alert()`` helper fails-soft on ``supabase=None``, so a
    persistent ``None`` here degrades alerts to ``logger.exception``
    rather than crashing callers.

    Returns:
        Optional[Client]: Supabase admin client, or None if creation
        failed.

    Test-hygiene guard (added 2026-05-14): when running under pytest
    (``PYTEST_CURRENT_TEST`` env var set) AND the singleton has not
    already been initialized, return None. Prevents local test
    execution against a developer environment with real Supabase
    credentials from polluting production tables via lazy alert
    imports that bypass handler-level mocking. Origin:
    iv_handler_accounting_mismatch alert pollution traced via H5
    unification investigation (see docs/backlog.md).

    Tests that pre-arm the singleton (set ``_ADMIN_INIT_ATTEMPTED=True``
    + ``_ADMIN_SUPABASE=<mock>``) pass through unaffected — the guard
    only fires on the lazy-init path. Tests that intentionally
    exercise the lazy-init path itself set
    ``ALERTS_ALLOW_ADMIN_UNDER_PYTEST=1`` to opt out.
    """
    global _ADMIN_SUPABASE, _ADMIN_INIT_ATTEMPTED
    if (
        not _ADMIN_INIT_ATTEMPTED
        and os.environ.get("PYTEST_CURRENT_TEST")
        and not os.environ.get("ALERTS_ALLOW_ADMIN_UNDER_PYTEST")
    ):
        return None
    if not _ADMIN_INIT_ATTEMPTED:
        _ADMIN_INIT_ATTEMPTED = True
        try:
            from packages.quantum.jobs.handlers.utils import get_admin_client
            _ADMIN_SUPABASE = get_admin_client()
        except Exception:
            logger.exception(
                "alerts: failed to obtain admin supabase client"
            )
    return _ADMIN_SUPABASE
