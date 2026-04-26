"""
Observability primitives per Loud-Error Doctrine v1.0.

Reference: docs/loud_error_doctrine.md
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

_VALID_SEVERITIES = ("info", "warning", "critical")


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
        severity: One of ``"info"``, ``"warning"``, ``"critical"``.
            Invalid values default to ``"warning"`` with a logged
            warning.
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

    try:
        supabase.table("risk_alerts").insert(record).execute()
    except Exception:
        logger.exception(
            "alert_write_failed",
            extra={
                "intended_alert_type": alert_type,
                "intended_severity": severity,
                "intended_message": message[:200],
            },
        )
