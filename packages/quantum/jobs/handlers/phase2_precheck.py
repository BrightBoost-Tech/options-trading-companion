"""
phase2_precheck.py — PR #6 Phase 2 observation-window verification.

Runs every 6 hours for 48 hours after PR #6 deploy. Executes the 4
verification queries from docs/pr6_close_path_consolidation.md §5
and writes a risk_alerts row capturing the result. The Phase 2 PR
references a specific successful row from this sequence as the
green-light signal — not a screenshot, not operator memory.

Why recurring, not single-fire
  A single fire at T+24h is fragile. Railway restart or scheduler
  glitch around that timestamp could miss the fire silently. Running
  every 6h produces 8 snapshots over the 48h window. Queries are
  cheap (~50ms) and catch mid-window issues a single fire would miss.

Self-expiry
  Handler checks hours-since PR6_DEPLOY_TIMESTAMP. After 48h it
  returns no-op regardless of whether Phase 2 has landed — the
  observation window is over by definition. This is simpler than
  querying the CHECK constraint definition to detect Phase 2 and
  equivalent in effect: post-window runs are harmless (verification
  queries still pass if Phase 2 is in place because the CHECK
  enforces them) but redundant. Avoiding extra alert rows is
  polish, not correctness.

Config (env vars — set at deploy time)
  PR6_DEPLOY_TIMESTAMP — ISO 8601 UTC datetime of PR #6 merge
    completion. Required. Bounds the verification query's search
    for post-deploy legacy writes. If unset, handler writes
    severity='warning' alert and exits — loud failure beats silent
    wrong answer. Deploy checklist in
    docs/pr6_close_path_consolidation.md §3.

  USER_ID — valid user UUID, already set on the worker service
    for every other user-scoped job (TRADING_USER_IDS). Required
    because risk_alerts has a FK to users(id); a placeholder UUID
    (e.g. all-zeros) violates the constraint and aborts the write.
    Discovered 2026-04-23 during the manual T+0 baseline write
    after the Phase 1 migration-repair incident: the system-UUID
    INSERT raised risk_alerts_user_id_fkey and required pivoting
    to the trading account owner UUID. If USER_ID is unset or
    empty, handler logs a stderr warning and returns without
    writing — it cannot satisfy the FK and would otherwise crash
    with a constraint error mid-run.

Output
  Each run writes one risk_alerts row with:
    alert_type        = 'phase2_precheck'
    severity          = 'info' on all-clean, 'critical' on any
                        failing Q1/Q2/Q3, 'warning' on missing
                        config or on Q4-only anomalies
    metadata.verification_type       = 'phase2_precheck'
    metadata.all_checks_passed       = bool (Q1, Q2, Q3 all zero)
    metadata.run_timestamp           = ISO UTC of this run
    metadata.deploy_timestamp        = PR6_DEPLOY_TIMESTAMP value
    metadata.hours_since_deploy      = float
    metadata.query_results           = {q1, q2, q3, q4 dicts}
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from packages.quantum.jobs.handlers.utils import get_admin_client

logger = logging.getLogger(__name__)

JOB_NAME = "phase2_precheck"

# Observation-window duration. After this many hours post-deploy, the
# handler returns no-op regardless of config or Phase 2 state.
_WINDOW_HOURS = 48

# risk_alerts.user_id FK constraint
# risk_alerts has a FK to users(id). A placeholder UUID like all-zeros
# fails the constraint and aborts the write. Discovered 2026-04-23
# during the manual T+0 baseline write after the Phase 1 migration-
# repair incident: the system-UUID insert raised FK violation
# (risk_alerts_user_id_fkey) and required pivoting to the trading
# account owner UUID. This handler reads USER_ID from env — same
# value the rest of the worker already uses for user-scoped jobs —
# so the row attaches to a real user. If unset or empty, the handler
# logs a warning and exits without writing. That's the loud-failure
# pattern: better to surface a config gap in logs than to crash with
# a FK error buried in the handler.

_LEGACY_REASONS = [
    "target_profit",
    "stop_loss",
    "alpaca_fill_reconciled_2026_04_16",
    "manual_internal_fill",
    "alpaca_fill_manual",
]

_CANONICAL_REASONS = [
    "target_profit_hit",
    "stop_loss_hit",
    "dte_threshold",
    "expiration_day",
    "manual_close_user_initiated",
    "alpaca_fill_reconciler_sign_corrected",
    "alpaca_fill_reconciler_standard",
    "envelope_force_close",
    "orphan_fill_repair",
]


def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """Entry point invoked by the job worker. See module docstring."""
    now_utc = datetime.now(timezone.utc)
    now_iso = now_utc.isoformat()
    supabase = get_admin_client()

    # ── user_id FK gate ────────────────────────────────────────────
    # risk_alerts has a FK to users(id); we must attach each alert
    # row to a real user. USER_ID env var is the project-wide
    # convention for user-scoped worker jobs (see TRADING_USER_IDS
    # / USER_ID in Railway). If unset/empty, exit early with a
    # stderr warning — no alert row is written because we can't
    # satisfy the FK. This is deliberate: a silent FK crash later
    # would be harder to diagnose than a noisy log line now.
    user_id = (os.environ.get("USER_ID") or "").strip()
    if not user_id:
        logger.warning(
            "[PHASE2_PRECHECK] USER_ID env var is unset or empty. "
            "Handler cannot write risk_alerts row (FK constraint to "
            "users table). Skipping this run; set USER_ID on the "
            "worker service to a valid trading account UUID. Incident "
            "reference: 2026-04-23 T+0 baseline write discovered the "
            "FK gap."
        )
        return {"ok": False, "status": "user_id_missing"}

    # ── Config gate ────────────────────────────────────────────────
    deploy_ts_raw = os.environ.get("PR6_DEPLOY_TIMESTAMP")
    if not deploy_ts_raw:
        _write_alert(
            supabase,
            user_id=user_id,
            severity="warning",
            message=(
                "phase2_precheck: PR6_DEPLOY_TIMESTAMP env var is unset. "
                "Handler cannot bound the verification query search window. "
                "Set the env var to the PR #6 deploy completion timestamp "
                "(ISO 8601 UTC) per docs/pr6_close_path_consolidation.md §3."
            ),
            metadata={
                "verification_type": "phase2_precheck",
                "status": "config_missing",
                "run_timestamp": now_iso,
            },
        )
        return {"ok": False, "status": "config_missing"}

    try:
        deploy_dt = _parse_iso_utc(deploy_ts_raw)
    except ValueError as exc:
        _write_alert(
            supabase,
            user_id=user_id,
            severity="warning",
            message=(
                f"phase2_precheck: PR6_DEPLOY_TIMESTAMP value "
                f"{deploy_ts_raw!r} could not be parsed as ISO 8601 "
                f"UTC: {exc}. Handler aborted."
            ),
            metadata={
                "verification_type": "phase2_precheck",
                "status": "config_parse_error",
                "run_timestamp": now_iso,
                "raw_value": deploy_ts_raw,
            },
        )
        return {"ok": False, "status": "config_parse_error"}

    # ── Window expiry ──────────────────────────────────────────────
    hours_since = (now_utc - deploy_dt).total_seconds() / 3600.0
    if hours_since > _WINDOW_HOURS:
        logger.info(
            f"[PHASE2_PRECHECK] observation window closed: "
            f"{hours_since:.1f}h since deploy > {_WINDOW_HOURS}h. No-op."
        )
        return {
            "ok": True,
            "status": "window_expired",
            "hours_since_deploy": round(hours_since, 2),
        }

    if hours_since < 0:
        # Clock skew or misconfiguration: deploy timestamp in the future.
        _write_alert(
            supabase,
            user_id=user_id,
            severity="warning",
            message=(
                f"phase2_precheck: PR6_DEPLOY_TIMESTAMP is in the future "
                f"({hours_since:.1f}h). Clock skew or misconfiguration."
            ),
            metadata={
                "verification_type": "phase2_precheck",
                "status": "clock_skew",
                "run_timestamp": now_iso,
                "deploy_timestamp": deploy_ts_raw,
                "hours_since_deploy": hours_since,
            },
        )
        return {"ok": False, "status": "clock_skew"}

    # ── Verification queries ───────────────────────────────────────
    deploy_iso = deploy_dt.isoformat()
    query_results = {
        "q1_legacy_reason_writes":        _q1_legacy_reason_writes(supabase, deploy_iso),
        "q2_missing_fill_source":         _q2_missing_fill_source(supabase, deploy_iso),
        "q3_non_canonical_reason":        _q3_non_canonical_reason(supabase, deploy_iso),
        "q4_anomaly_alerts_in_window":    _q4_anomaly_alerts_in_window(supabase, deploy_iso),
    }

    q1_count = query_results["q1_legacy_reason_writes"]["count"]
    q2_count = query_results["q2_missing_fill_source"]["count"]
    q3_count = query_results["q3_non_canonical_reason"]["count"]
    q4_count = query_results["q4_anomaly_alerts_in_window"]["count"]

    # Q1/Q2/Q3 are hard-gate checks. Any non-zero = Phase 2 NOT SAFE.
    # Q4 is informational: recurring anomalies are concerning but
    # don't mechanically block Phase 2 (operator reviews the actual
    # alerts before shipping).
    all_checks_passed = (q1_count == 0 and q2_count == 0 and q3_count == 0)

    if not all_checks_passed:
        severity = "critical"
        status = "hard_gate_failed"
    elif q4_count > 0:
        severity = "warning"
        status = "anomalies_present"
    else:
        severity = "info"
        status = "all_checks_passed"

    _write_alert(
        supabase,
        user_id=user_id,
        severity=severity,
        message=(
            f"phase2_precheck [{status}]: "
            f"legacy_writes={q1_count}, missing_fill_source={q2_count}, "
            f"non_canonical_reason={q3_count}, "
            f"anomaly_alerts_in_window={q4_count}."
        ),
        metadata={
            "verification_type": "phase2_precheck",
            "status": status,
            "all_checks_passed": all_checks_passed,
            "run_timestamp": now_iso,
            "deploy_timestamp": deploy_iso,
            "hours_since_deploy": round(hours_since, 2),
            "query_results": query_results,
        },
    )

    return {
        "ok": all_checks_passed,
        "status": status,
        "hours_since_deploy": round(hours_since, 2),
        "query_results": query_results,
    }


# ── Verification queries ───────────────────────────────────────────


def _q1_legacy_reason_writes(supabase, deploy_iso: str) -> Dict[str, Any]:
    """Post-deploy closes whose close_reason is in the 5-value legacy
    set. Expected: zero. Non-zero means a handler migration missed
    a call site. Phase 2 must NOT apply with Q1 > 0."""
    try:
        res = supabase.table("paper_positions") \
            .select("id, close_reason, closed_at, fill_source", count="exact") \
            .gt("closed_at", deploy_iso) \
            .in_("close_reason", _LEGACY_REASONS) \
            .execute()
        return {
            "count": len(res.data or []),
            "sample_rows": (res.data or [])[:5],
        }
    except Exception as exc:
        return {"count": -1, "error": str(exc)}


def _q2_missing_fill_source(supabase, deploy_iso: str) -> Dict[str, Any]:
    """Post-deploy closed rows with NULL fill_source. Expected: zero.
    Non-zero means a path bypassed close_position_shared. Phase 2
    must NOT apply with Q2 > 0 — close_path_required will reject
    these rows at the next UPDATE."""
    try:
        res = supabase.table("paper_positions") \
            .select("id, close_reason, closed_at", count="exact") \
            .eq("status", "closed") \
            .gt("closed_at", deploy_iso) \
            .is_("fill_source", "null") \
            .execute()
        return {
            "count": len(res.data or []),
            "sample_rows": (res.data or [])[:5],
        }
    except Exception as exc:
        return {"count": -1, "error": str(exc)}


def _q3_non_canonical_reason(supabase, deploy_iso: str) -> Dict[str, Any]:
    """Post-deploy closes with a close_reason NOT in the 9 canonical
    values. Complementary to Q1 — catches typos or unknown strings
    that aren't in the legacy-5 either. Expected: zero."""
    try:
        res = supabase.table("paper_positions") \
            .select("id, close_reason, closed_at, fill_source", count="exact") \
            .eq("status", "closed") \
            .gt("closed_at", deploy_iso) \
            .not_.in_("close_reason", _CANONICAL_REASONS) \
            .execute()
        # Phase 1 accepts NULL — filter those out explicitly.
        rows = [r for r in (res.data or []) if r.get("close_reason") is not None]
        return {
            "count": len(rows),
            "sample_rows": rows[:5],
        }
    except Exception as exc:
        return {"count": -1, "error": str(exc)}


def _q4_anomaly_alerts_in_window(supabase, deploy_iso: str) -> Dict[str, Any]:
    """Critical close_path_anomaly alerts fired since deploy. Non-zero
    is informational: each alert represents a position that didn't
    close as expected and required operator triage. The Phase 2 PR
    description should explain any non-zero count (are alerts
    resolved? transient or systematic?)."""
    try:
        res = supabase.table("risk_alerts") \
            .select("id, created_at, metadata, message", count="exact") \
            .eq("alert_type", "close_path_anomaly") \
            .eq("severity", "critical") \
            .gt("created_at", deploy_iso) \
            .execute()
        return {
            "count": len(res.data or []),
            "sample_rows": (res.data or [])[:5],
        }
    except Exception as exc:
        return {"count": -1, "error": str(exc)}


# ── Helpers ────────────────────────────────────────────────────────


def _parse_iso_utc(ts: str) -> datetime:
    """Parse ISO 8601 datetime to a timezone-aware UTC datetime.
    Handles both 'Z' suffix and '+00:00' suffix. Raises ValueError
    if the input is unparseable or lacks timezone information."""
    s = str(ts).strip()
    if not s:
        raise ValueError("empty")
    normalized = s.replace("Z", "+00:00") if s.endswith("Z") else s
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        raise ValueError(
            f"datetime {ts!r} has no timezone — require ISO 8601 UTC "
            f"(trailing 'Z' or '+00:00')."
        )
    return dt.astimezone(timezone.utc)


def _write_alert(
    supabase,
    user_id: str,
    severity: str,
    message: str,
    metadata: Dict[str, Any],
) -> None:
    """Write one risk_alerts row capturing the run result. Swallows
    its own exceptions — if the alert write itself fails, log and
    continue. The next 6h fire will attempt again.

    user_id must be a valid user UUID (resolved upstream from the
    USER_ID env var). risk_alerts has a FK to users(id); callers
    who can't resolve a real user MUST NOT invoke this helper —
    the handler's run() short-circuits on missing USER_ID before
    any write attempt."""
    try:
        supabase.table("risk_alerts").insert({
            "user_id": user_id,
            "alert_type": "phase2_precheck",
            "severity": severity,
            "message": message,
            "metadata": metadata,
        }).execute()
    except Exception as exc:
        logger.error(
            f"[PHASE2_PRECHECK] failed to write risk_alert "
            f"(severity={severity}): {exc}"
        )
