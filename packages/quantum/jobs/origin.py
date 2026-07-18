"""A5-2 job-origin provenance (Lane 4D, 2026-07-17).

Every ``job_runs`` row carries a typed origin object at ``payload.origin``,
stamped at enqueue time (``JobRunStore.create_or_get`` /
``create_or_get_cancelled``) — NOT post-hoc in ``result`` — so provenance
exists even when the run never executes (the 03946f58 queued-orphan lesson)
and an off-schedule 14:09Z-style ``suggestions_open`` run is attributable
afterwards.

Taxonomy (closed set):
    scheduler                — the in-process APScheduler fired the enqueue
                               (asserted via X-Task-Origin by scheduler._fire_task)
    operator_signed_endpoint — a signed /tasks/* request from an operator-class
                               client (run_signed_task.py CLI, GitHub Actions,
                               admin/user API) or an UNMARKED signed client
    internal_retry           — the automatic failed_retryable re-queue scan
                               (scheduler._retry_failed_jobs)
    manual_cli               — a local script enqueuing directly against the DB
                               (bypassing the API), e.g. rq_smoke_morning_brief
    replay                   — reserved: a replay-harness-driven enqueue.
                               NO production call site today — the replay layer
                               (services/replay) never enqueues job_runs; the
                               replay_integrity_check JOB is operator-triggered
                               and carries the trigger's origin, not 'replay'.
    unknown_legacy           — the create_or_get seam default for any caller
                               not yet threaded (and the coercion fallback)

Retry semantics: both retry paths (auto-retry scan, admin /jobs/runs/{id}/retry)
re-queue the SAME row — no new ``job_runs`` row exists to carry a fresh origin.
They therefore APPEND an annotation to ``payload.origin_retries`` (a list) via
``append_retry_origin`` and never overwrite ``payload.origin`` (first-writer
provenance is the row creator; the retry is an additional attributable event).
``parent_job_run_id`` on a retry annotation is the row's own id — the retried
run IS the parent, by construction of the reused row.

Trust boundary: the X-Task-Origin / X-Task-Actor-Class headers are
self-assertions by callers that already passed HMAC (or legacy cron-secret)
verification. Provenance is attribution metadata for the audit trail — it is
NEVER used for authorization, and it never carries personal identity or
tokens (actor CLASS strings only).

Queryability: ``payload->'origin'->>'origin'``,
``payload->'origin'->>'schedule_id'``, ``payload->'origin_retries'``.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ── Taxonomy ─────────────────────────────────────────────────────────
ORIGIN_SCHEDULER = "scheduler"
ORIGIN_OPERATOR_SIGNED_ENDPOINT = "operator_signed_endpoint"
ORIGIN_INTERNAL_RETRY = "internal_retry"
ORIGIN_MANUAL_CLI = "manual_cli"
ORIGIN_REPLAY = "replay"
ORIGIN_UNKNOWN_LEGACY = "unknown_legacy"

VALID_ORIGINS = frozenset({
    ORIGIN_SCHEDULER,
    ORIGIN_OPERATOR_SIGNED_ENDPOINT,
    ORIGIN_INTERNAL_RETRY,
    ORIGIN_MANUAL_CLI,
    ORIGIN_REPLAY,
    ORIGIN_UNKNOWN_LEGACY,
})

# ── Assertion headers (sent by trusted internal callers; read AFTER the
#    endpoint's HMAC / cron-secret verification has already passed) ───
ORIGIN_HEADER = "X-Task-Origin"
ACTOR_CLASS_HEADER = "X-Task-Actor-Class"
REQUEST_ID_HEADER = "X-Task-Request-Id"
SCHEDULE_ID_HEADER = "X-Task-Schedule-Id"
SCHEDULE_SLOT_HEADER = "X-Task-Schedule-Slot"

PROVENANCE_VERSION = 1

# Defensive clip for header-derived strings (attribution metadata, not
# payload data — a runaway value must never bloat the jsonb row).
_MAX_FIELD_LEN = 128


def _clip(value: Optional[Any]) -> Optional[str]:
    """Normalize an optional field to a clipped, stripped string (or None)."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:_MAX_FIELD_LEN]


def build_origin(
    origin: str,
    *,
    trigger_actor_class: Optional[str] = None,
    trigger_request_id: Optional[str] = None,
    parent_job_run_id: Optional[str] = None,
    schedule_id: Optional[str] = None,
    schedule_slot: Optional[str] = None,
    code_sha: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a typed origin provenance object.

    Raises ``ValueError`` on a taxonomy value outside VALID_ORIGINS — a typo
    at a call site must fail loudly at build/test time, never write a
    fabricated taxonomy value (H9). Seam-level callers that must not break
    enqueue use :func:`coerce_origin` instead.

    ``created_at`` is known-at semantics: the UTC instant this provenance was
    captured (enqueue/annotation time), independent of the DB row's own
    ``created_at``. ``code_sha`` is the ENQUEUING process's deployed SHA via
    the existing lineage resolver (observability/lineage.get_code_sha).
    """
    if origin not in VALID_ORIGINS:
        raise ValueError(
            f"invalid origin taxonomy value: {origin!r} "
            f"(valid: {sorted(VALID_ORIGINS)})"
        )
    if code_sha is None:
        # Reuse the existing lineage resolver — never duplicate SHA logic.
        from packages.quantum.observability.lineage import get_code_sha
        code_sha = get_code_sha()
    return {
        "origin": origin,
        "trigger_actor_class": _clip(trigger_actor_class),
        "trigger_request_id": _clip(trigger_request_id),
        "parent_job_run_id": _clip(parent_job_run_id),
        "schedule_id": _clip(schedule_id),
        "schedule_slot": _clip(schedule_slot),
        "code_sha": code_sha,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "v": PROVENANCE_VERSION,
    }


def coerce_origin(origin: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Seam-safe coercion at the create_or_get boundary.

    ``None`` (an un-threaded caller) → ``unknown_legacy`` with an actor class
    naming the gap. A malformed object (wrong type / invalid taxonomy) also
    coerces to ``unknown_legacy`` — provenance must never block an enqueue,
    and a bad assertion is recorded as the gap it is rather than fabricated
    into a valid-looking taxonomy value.
    """
    if origin is None:
        return build_origin(
            ORIGIN_UNKNOWN_LEGACY,
            trigger_actor_class="unthreaded_enqueue_caller",
        )
    if not isinstance(origin, dict) or origin.get("origin") not in VALID_ORIGINS:
        logger.warning(
            "[JOB_ORIGIN] malformed origin object coerced to unknown_legacy: %r",
            str(origin)[:200],
        )
        return build_origin(
            ORIGIN_UNKNOWN_LEGACY,
            trigger_actor_class="malformed_origin_object",
        )
    return origin


def resolve_request_origin(request: Any) -> Dict[str, Any]:
    """Classify an AUTHENTICATED task request into the origin taxonomy.

    Reads the self-asserted ``X-Task-Origin`` (+ actor/request-id/schedule)
    headers. Call this only from endpoints whose auth dependency
    (``verify_task_signature`` / user JWT) has already passed — the assertion
    is trusted at the signing-key-holder level.

    Classification:
    - asserted 'scheduler'        → scheduler (+ schedule_id/slot headers)
    - asserted other valid value  → that value (honest passthrough)
    - asserted unrecognized value → operator_signed_endpoint, actor class
                                    records the invalid assertion (never
                                    fabricated into a valid taxonomy value)
    - no assertion                → operator_signed_endpoint, actor class
                                    'signed_client_unmarked' (the 14:09Z
                                    lesson: an unmarked signed request must
                                    NEVER read as scheduler)
    """
    try:
        headers = request.headers
        claimed = (headers.get(ORIGIN_HEADER) or "").strip().lower()
        actor = _clip(headers.get(ACTOR_CLASS_HEADER))
        request_id = _clip(headers.get(REQUEST_ID_HEADER))
        schedule_id = _clip(headers.get(SCHEDULE_ID_HEADER))
        schedule_slot = _clip(headers.get(SCHEDULE_SLOT_HEADER))
    except Exception:
        # A request object we cannot read is a gap, not a guess.
        return build_origin(
            ORIGIN_UNKNOWN_LEGACY,
            trigger_actor_class="unresolvable_request",
        )

    if claimed == ORIGIN_SCHEDULER:
        return build_origin(
            ORIGIN_SCHEDULER,
            trigger_actor_class=actor or "apscheduler_in_process",
            trigger_request_id=request_id,
            schedule_id=schedule_id,
            schedule_slot=schedule_slot,
        )
    if claimed in VALID_ORIGINS:
        return build_origin(
            claimed,
            trigger_actor_class=actor or "signed_client",
            trigger_request_id=request_id,
            schedule_id=schedule_id,
            schedule_slot=schedule_slot,
        )
    if claimed:
        return build_origin(
            ORIGIN_OPERATOR_SIGNED_ENDPOINT,
            trigger_actor_class=f"invalid_origin_assertion:{claimed[:32]}",
            trigger_request_id=request_id,
        )
    return build_origin(
        ORIGIN_OPERATOR_SIGNED_ENDPOINT,
        trigger_actor_class=actor or "signed_client_unmarked",
        trigger_request_id=request_id,
    )


def append_retry_origin(
    payload: Optional[Dict[str, Any]],
    *,
    origin: str,
    trigger_actor_class: str,
    parent_job_run_id: str,
) -> Dict[str, Any]:
    """Return a NEW payload dict with a retry annotation appended to
    ``origin_retries``. Never mutates the input; never touches
    ``payload['origin']`` (creator provenance is immutable). Used by both
    retry paths (auto-retry scan → internal_retry; admin API retry →
    operator_signed_endpoint)."""
    base = dict(payload) if isinstance(payload, dict) else {}
    retries = list(base.get("origin_retries") or [])
    retries.append(
        build_origin(
            origin,
            trigger_actor_class=trigger_actor_class,
            parent_job_run_id=parent_job_run_id,
        )
    )
    base["origin_retries"] = retries
    return base
