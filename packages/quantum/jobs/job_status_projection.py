"""Secret-free projection of a ``job_runs`` row for the SIGNED read-only
status route (``GET /tasks/status/{job_run_id}``).

Dependency-free BY DESIGN: this module imports nothing from the app so the
projection (the only logic behind the status route) is unit-testable in
isolation and reusable without pulling rq / supabase / fastapi.

The projection is an ALLOWLIST, not a blocklist: only the curated top-level
columns below and an allowlisted ``result`` sub-summary are ever surfaced.
A future handler that stashes a secret in ``payload`` or ``result`` (or a new
column) can NEVER leak through this route, because unlisted keys are dropped
by construction. The raw ``payload`` (may carry ``user_id`` / ``origin``),
``error`` internals, ``locked_by`` / ``locked_at``, and ``idempotency_key``
are deliberately withheld.
"""

from typing import Any, Dict

# Terminal job_runs states — mirrors the enqueue-side TERMINAL_STATES set in
# packages/quantum/public_tasks.py (kept in lockstep). Only 'succeeded' is a
# healthy terminal; the rest are non-green terminals a caller should surface.
TERMINAL_STATES = (
    "succeeded",
    "partial",
    "failed",
    "failed_retryable",
    "dead_lettered",
    "cancelled",
)

# Allowlisted keys copied out of the handler ``result`` blob. Everything else
# in ``result`` is withheld. ``counts`` is a dict of ints; ``reason`` /
# ``blocked_reason`` / ``status`` / ``message`` are short handler-authored
# strings intended for display (never secrets).
RESULT_SAFE_KEYS = ("status", "reason", "blocked_reason", "counts", "message")


def project_job_status(row: Dict[str, Any]) -> Dict[str, Any]:
    """Return a curated, secret-free projection of a ``job_runs`` row.

    Only allowlisted columns and an allowlisted ``result`` sub-summary are
    emitted. ``payload``, ``error``, lock fields, ``origin``, and
    ``idempotency_key`` are never included.
    """
    result = row.get("result")
    if not isinstance(result, dict):
        result = {}

    result_summary: Dict[str, Any] = {}
    for key in RESULT_SAFE_KEYS:
        value = result.get(key)
        if value is not None:
            result_summary[key] = value

    # Surface an errors COUNT (never the raw error content) when the handler
    # reports a list/int of errors — enough to signal partial failure without
    # leaking internal messages.
    errors = result.get("errors")
    if isinstance(errors, list):
        result_summary["errors_count"] = len(errors)
    elif isinstance(errors, int):
        result_summary["errors_count"] = errors

    # Typed reason precedence: an explicit handler reason, then a blocked
    # reason, then the cancelled_reason column (pause / go-live gate).
    reason = (
        result.get("reason")
        or result.get("blocked_reason")
        or row.get("cancelled_reason")
    )

    status = row.get("status")

    return {
        "job_run_id": row.get("id"),
        "job_name": row.get("job_name"),
        "status": status,
        "terminal": status in TERMINAL_STATES,
        "created_at": row.get("created_at"),
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at") or row.get("completed_at"),
        "duration_ms": row.get("duration_ms"),
        "attempt": row.get("attempt"),
        "cancelled_reason": row.get("cancelled_reason"),
        "cancelled_detail": row.get("cancelled_detail"),
        "reason": reason,
        "result": result_summary or None,
    }
