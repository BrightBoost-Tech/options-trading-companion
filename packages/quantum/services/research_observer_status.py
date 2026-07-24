"""Research-observer status isolation (Lane B, 2026-07-23).

The terminal-distribution (``td_scan_score_observe``) and shadow-fleet
(``shadow_fleet_evaluate``) ENQUEUE seams ride the tail of the live
``suggestions_open`` scan as OBSERVE-ONLY research children. A readiness or
enqueue failure in either seam is a RESEARCH failure, NOT a live-decision
failure: the parent scan still produced (or correctly declined to produce) its
live suggestions.

Before this module, both seams folded their observer ``errors`` into the
parent's ``cycle_result["counts"]["errors"]``. The A9-F8 roll-up
(``suggestions_open._persist_error_rollup``) then carried that into the
TOP-LEVEL ``counts.errors``, which the runner's partial classifier
(``packages/quantum/jobs/runner.py:_classify_handler_return`` — reads
``counts.errors`` / ``users_failed`` / ``error`` only) and the A4 silent-failure
detector (``job_succeeded_with_errors``, which reads ``counts.errors``) both
consume. Result: a research enqueue hiccup marked an otherwise-clean LIVE scan
PARTIAL and could page the operator on pure research noise.

This module isolates that truth WITHOUT hiding research failures. A failure:
  - stays durable in the parent's per-user metadata (the enqueue dict) AND the
    top-level ``result.research_observers`` block;
  - increments ``counts.research_observer_failures`` — a SEPARATE channel the
    live-job partial classifier NEVER reads;
  - emits a dedicated typed ``research_observer_enqueue_failed`` alert,
    de-duplicated on ``(source_job_run_id, observer_name, failure_signature,
    code_sha)`` by REUSING the #1332 mechanism: the append-only ``risk_alerts``
    rows are themselves the dedup store, matched by identity fields carried in
    metadata, fail-OPEN (a possible duplicate beats a swallowed failure).

The child job, once enqueued, keeps its OWN honest succeeded/partial/failed
truth (``run_td_scan_score_observe`` / ``run_fleet_policy_eval`` are untouched) —
this module governs only the PARENT's classification of the enqueue seam.
Regime-V4 stays note-only (its own seam); single-leg is deliberately left
exactly as-is (its enqueue errors still count as live errors — a separate
contract, per the Lane B spec default).

Flagless by doctrine: this is a measurement-honesty correction, not a behavioral
opt-in, so it adds no env flag and nothing to FLAG_ECHO.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Canonical observer names — stable identity strings used both as the
# ``result.research_observers`` keys AND as the dedup ``observer_name``.
OBSERVER_TERMINAL_DISTRIBUTION = "terminal_distribution"
OBSERVER_SHADOW_FLEET = "shadow_fleet"

RESEARCH_OBSERVER_ALERT_TYPE = "research_observer_enqueue_failed"
# Bump ONLY when the classification/emit SEMANTICS materially change — a bump
# lets the same standing failure re-emit exactly once under the new version
# (mirrors ops_health_service.A4_DETECTOR_VERSION, #1332).
RESEARCH_OBSERVER_DETECTOR_VERSION = "v1"
_PRIOR_LOOKUP_LIMIT = 50
_ALERTS_TABLE = "risk_alerts"


def new_research_observers_block() -> Dict[str, Dict[str, Any]]:
    """A fresh ``result.research_observers`` accumulator with both known
    observers pre-seeded to a no-op shape ``{status, errors, job_run_id}``."""
    return {
        OBSERVER_TERMINAL_DISTRIBUTION: {"status": None, "errors": 0, "job_run_id": None},
        OBSERVER_SHADOW_FLEET: {"status": None, "errors": 0, "job_run_id": None},
    }


def classify_observer_enqueue(enq_result: Any) -> int:
    """The observer's OWN error count (0 = no-op/success, >0 = research failure).

    A pure re-READ of the honest ``errors`` int the observer seam already
    returns (0 for ``flag_disabled`` / ``non_natural_parent`` / ``fleet_inactive``
    / ``fleet_absent`` / ``queued``; >0 for a readiness or enqueue failure). Never
    mutates, never raises."""
    if not isinstance(enq_result, dict):
        return 0
    try:
        return int(enq_result.get("errors") or 0)
    except (TypeError, ValueError):
        return 0


def fold_observer_result(
    block: Dict[str, Dict[str, Any]],
    observer_name: str,
    enq_result: Any,
) -> None:
    """Accumulate one observer enqueue result into the top-level block.

    ``errors`` sum; ``job_run_id`` keeps the last non-null; ``status`` prefers a
    FAILURE status (errors>0) over a no-op/success status so the block headline
    is the most-severe truth across users. Never raises."""
    entry = block.setdefault(
        observer_name, {"status": None, "errors": 0, "job_run_id": None}
    )
    result = enq_result if isinstance(enq_result, dict) else {}
    obs_errors = classify_observer_enqueue(result)
    entry["errors"] = int(entry.get("errors") or 0) + obs_errors
    jr = result.get("job_run_id")
    if jr:
        entry["job_run_id"] = jr
    new_status = result.get("status")
    if obs_errors > 0:
        # A failure status always wins the headline.
        entry["status"] = new_status
    elif entry.get("status") is None:
        entry["status"] = new_status


def research_observer_failure_signature(
    observer_name: Any, status: Any, error_class: Any
) -> str:
    """Stable signature of the FAILURE a research-observer alert reports.

    A materially-different failure — a different observer, a different terminal
    status, or a different error class — yields a DIFFERENT signature (allowed to
    re-emit); a byte-identical failure yields the SAME signature (deduped).
    Mirrors ``ops_health_service.a4_failure_signature`` (#1332)."""
    obs = str(observer_name if observer_name is not None else "unknown")
    st = str(status if status is not None else "unknown")
    ec = str(error_class if error_class is not None else "none")
    return f"{obs}|status={st}|error_class={ec}"


def _error_class_of(enq_result: Dict[str, Any]) -> Optional[str]:
    """Best-effort exception class from the observer result. The seam stores it
    either as an explicit ``error_class`` (the parent-caught crash path) or as
    the ``ClassName: message`` prefix of ``error`` (the seam-internal path)."""
    ec = enq_result.get("error_class")
    if ec:
        return str(ec)
    err = enq_result.get("error")
    if isinstance(err, str) and ":" in err:
        return err.split(":", 1)[0].strip() or None
    return None


def find_prior_research_observer_alert(
    client: Any,
    *,
    source_job_run_id: Any,
    observer_name: str,
    failure_signature: str,
    code_sha: Any,
) -> Optional[Dict[str, Any]]:
    """Return the newest durable ``risk_alerts`` row that ALREADY reported this
    exact ``(source_job_run_id, observer_name, failure_signature, code_sha)``
    identity, or ``None`` when this is the first emit.

    REUSES the #1332 dedup mechanism (``find_prior_silent_failure_alert``): the
    append-only alert rows the emitter itself writes ARE the dedup store, so the
    check is durable across process recycle and visible across both workers —
    no parallel store is invented. Candidates are fetched by ``alert_type`` +
    ``metadata->>source_job_run_id`` and the full identity is re-verified in
    Python so a jsonb-filter quirk can never widen the match.

    FAIL-OPEN: a missing id or a query error returns ``None`` (emit) — loudness
    beats a silently swallowed research failure."""
    if client is None or not source_job_run_id:
        return None
    try:
        res = (
            client.table(_ALERTS_TABLE)
            .select("id, created_at, metadata")
            .eq("alert_type", RESEARCH_OBSERVER_ALERT_TYPE)
            .filter("metadata->>source_job_run_id", "eq", str(source_job_run_id))
            .order("created_at", desc=True)
            .limit(_PRIOR_LOOKUP_LIMIT)
            .execute()
        )
        rows = getattr(res, "data", None) or []
    except Exception as exc:  # noqa: BLE001 — fail-open by design
        logger.warning(
            "[RESEARCH_OBSERVER_DEDUP] prior-alert lookup failed "
            "(fail-open, will emit): %s",
            exc,
        )
        return None

    want_sha = str(code_sha or "")
    for row in rows:
        meta = row.get("metadata") if isinstance(row, dict) else None
        if not isinstance(meta, dict):
            continue
        if str(meta.get("source_job_run_id")) != str(source_job_run_id):
            continue
        if str(meta.get("observer_name")) != str(observer_name):
            continue
        cand_version = (
            meta.get("detector_version") or RESEARCH_OBSERVER_DETECTOR_VERSION
        )
        cand_sig = meta.get("failure_signature")
        cand_sha = str(meta.get("code_sha") or "")
        if (
            cand_version == RESEARCH_OBSERVER_DETECTOR_VERSION
            and cand_sig == failure_signature
            and cand_sha == want_sha
        ):
            return row
    return None


def _redact(text: Any) -> Optional[str]:
    """Redact secrets from observer error text BEFORE truncation (doctrine:
    'truncate only after redaction'), via the canonical secret-shape masker."""
    if text is None:
        return None
    try:
        from packages.quantum.security.masking import sanitize_message

        return sanitize_message(str(text))[:300]
    except Exception:  # noqa: BLE001 — redaction must never break the alert
        return str(text)[:300]


def emit_research_observer_failure_alert(
    client: Any,
    *,
    observer_name: str,
    enq_result: Any,
    source_job_run_id: Any,
    code_sha: Any,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Emit the typed ``research_observer_enqueue_failed`` alert for ONE observer
    enqueue failure, de-duped on ``(source_job_run_id, observer_name,
    failure_signature, code_sha)`` against the append-only ``risk_alerts`` store
    (#1332 mechanism). Secrets are redacted before truncation. Returns a typed
    ``{emitted, reason, failure_signature}`` dict. NEVER raises."""
    result = enq_result if isinstance(enq_result, dict) else {}
    status = result.get("status")
    error_class = _error_class_of(result)
    redacted_error = _redact(result.get("error"))
    signature = research_observer_failure_signature(observer_name, status, error_class)

    try:
        prior = find_prior_research_observer_alert(
            client,
            source_job_run_id=source_job_run_id,
            observer_name=observer_name,
            failure_signature=signature,
            code_sha=code_sha,
        )
    except Exception:  # noqa: BLE001 — dedup lookup is best-effort, fail-open
        prior = None
    if prior is not None:
        return {
            "emitted": False,
            "reason": "duplicate",
            "failure_signature": signature,
            "prior_alert_id": prior.get("id") if isinstance(prior, dict) else None,
        }

    try:
        from packages.quantum.observability.alerts import alert

        alert(
            client,
            alert_type=RESEARCH_OBSERVER_ALERT_TYPE,
            severity="warning",
            message=(
                f"Research observer `{observer_name}` enqueue/readiness failed "
                f"(status={status}) — ISOLATED from the live scan: the parent "
                f"run stays succeeded and counts.errors is unchanged."
            ),
            user_id=user_id,
            metadata={
                "source": "suggestions_open",
                "observer_name": observer_name,
                "status": status,
                "observer_errors": classify_observer_enqueue(result),
                "error": redacted_error,
                "error_class": error_class,
                "source_job_run_id": (
                    str(source_job_run_id) if source_job_run_id else None
                ),
                "code_sha": str(code_sha) if code_sha else None,
                "detector_version": RESEARCH_OBSERVER_DETECTOR_VERSION,
                "failure_signature": signature,
            },
        )
        return {"emitted": True, "reason": "emitted", "failure_signature": signature}
    except Exception as exc:  # noqa: BLE001 — alert emit is best-effort
        logger.warning(
            "[RESEARCH_OBSERVER] alert emit failed (non-fatal): %s", exc
        )
        return {
            "emitted": False,
            "reason": "emit_error",
            "failure_signature": signature,
        }


def record_observer_seam(
    *,
    client: Any,
    observer_name: str,
    enq_result: Any,
    research_observers: Dict[str, Dict[str, Any]],
    source_job_run_id: Any,
    source_code_sha: Any,
    user_id: str,
    notes: List[str],
) -> int:
    """Fold one observer enqueue result into ``research_observers`` and, on a
    research failure, emit the deduped typed alert + add a durable note.

    Returns the number of RESEARCH-observer failures to add to
    ``counts.research_observer_failures`` (the observer's own ``errors`` count).
    NEVER touches ``counts.errors`` and NEVER raises — an accounting/alert bug
    must not fail a live scan that succeeded."""
    try:
        fold_observer_result(research_observers, observer_name, enq_result)
        obs_errors = classify_observer_enqueue(enq_result)
        result = enq_result if isinstance(enq_result, dict) else {}
        if obs_errors > 0:
            emit_research_observer_failure_alert(
                client,
                observer_name=observer_name,
                enq_result=result,
                source_job_run_id=source_job_run_id,
                code_sha=source_code_sha,
                user_id=user_id,
            )
            notes.append(
                f"research observer {observer_name} enqueue DEGRADED for "
                f"{str(user_id)[:8]}: {result.get('status')} "
                f"(ISOLATED — live counts.errors unchanged, parent status kept)"
            )
            return obs_errors
        if result.get("enqueued"):
            notes.append(
                f"research observer {observer_name} child enqueued for "
                f"{str(user_id)[:8]}: {result.get('job_run_id')}"
            )
        return 0
    except Exception as exc:  # noqa: BLE001 — isolation helper is fail-soft
        logger.warning(
            "[RESEARCH_OBSERVER] record_observer_seam failed (non-fatal): %s",
            exc,
        )
        return 0
