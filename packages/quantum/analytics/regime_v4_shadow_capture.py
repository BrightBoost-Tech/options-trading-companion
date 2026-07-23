"""Regime V4 shadow comparison — PARENT CAPTURE + ENQUEUE SEAM (observe-only).

This is the LIVE-PATH-SAFE half of the Regime-V4 observe arc.  It is imported by
the orchestrator (``run_midday_cycle``) and the ``suggestions_open`` handler, so
it deliberately references NEITHER ``RegimeEngineV4`` NOR the child scorer — the
live import graph never pulls the V4 engine in.  All V4 compute lives in
``regime_v4_shadow_compare.py`` (the census-pinned scorer) on the ``background``
queue.

Two responsibilities, both zero-decision:
1. ``is_observe_enabled`` — the NEW ``REGIME_V4_OBSERVE_ENABLED`` flag
   (behavioral opt-in, default OFF; fails SAFE to "no observation").  It gates
   ENQUEUE only and never any live behavior.  It does NOT touch / repurpose the
   reserved ``REGIME_V4_ENABLED`` wiring gate.
2. ``build_capture_envelope`` + ``maybe_enqueue_regime_v4_shadow_compare`` — pure
   capture (of values the live V3 cycle ALREADY computed) + an idempotent
   scheduler-origin-only enqueue to the ``background`` queue.  Mirrors the
   single-leg ``maybe_enqueue`` pattern: own try/except, NEVER touches parent
   counts, one failure never affects the live cycle.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Dict, List, Mapping, Optional

logger = logging.getLogger(__name__)

FLAG_ENV = "REGIME_V4_OBSERVE_ENABLED"
JOB_NAME = "regime_v4_shadow_compare"
NATURAL_PARENT_ORIGIN = "scheduler"


def is_observe_enabled() -> bool:
    """Behavioral opt-in (§3): unset/empty → OFF (no observation). Lenient truthy
    parse (``1/true/yes/on``), matching the vol_signal / regime_filter observe
    precedents. An env regression fails SAFE to no-observe; the flag NEVER gates
    a live decision."""
    return os.environ.get(FLAG_ENV, "0").strip().lower() in ("1", "true", "yes", "on")


def observe_sinks() -> tuple:
    """One-call per-cycle setup for the parent capture seam. Returns
    ``(on, capture_sink, symbol_sink)``: when the observe flag is OFF the two
    sinks are ``None`` so ``compute_global_snapshot`` + ``scan_for_opportunities``
    run byte-identical and nothing is captured/enqueued. Kept compact so the
    orchestrator preamble stays small."""
    on = is_observe_enabled()
    return on, ({} if on else None), ({"per_symbol": {}} if on else None)


def build_capture_envelope(
    global_snapshot: Any,
    capture_sink: Optional[Mapping[str, Any]],
    symbol_sink: Optional[Mapping[str, Any]],
    *,
    as_of: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Assemble the child payload from values the live cycle ALREADY produced —
    PURE extraction, ZERO new computation (Audit-B C2/C4).

    - ``capture_sink`` is populated by ``compute_global_snapshot`` (basket closes
      + basket quotes it already fetched this cycle).
    - ``symbol_sink`` is populated by the scanner (per-scanned-symbol V3
      snapshot state / effective regime / sentiment / iv_rank / live pool /
      earnings signal).
    Returns ``None`` when there is nothing to observe (no basket closes captured),
    so the enqueue seam stays a true no-op."""
    if global_snapshot is None:
        return None
    basket_closes = dict((capture_sink or {}).get("basket_closes") or {})
    if not basket_closes:
        return None
    per_symbol = list((symbol_sink or {}).get("per_symbol", {}).values())
    return {
        "as_of": as_of or getattr(global_snapshot, "as_of_ts", None),
        "v3_global": {
            "state": global_snapshot.state.value,
            "risk_score": float(global_snapshot.risk_score),
            "risk_scaler": float(global_snapshot.risk_scaler),
            "as_of_ts": getattr(global_snapshot, "as_of_ts", None),
        },
        "basket_closes": basket_closes,
        "basket_quotes": dict((capture_sink or {}).get("basket_quotes") or {}),
        "per_symbol": per_symbol,
    }


def maybe_enqueue_regime_v4_shadow_compare(
    client: Any,
    *,
    capture: Optional[Mapping[str, Any]],
    user_id: str,
    source_job_run_id: Optional[str],
    source_decision_id: Optional[str],
    source_code_sha: Optional[str],
    as_of: Optional[str],
    parent_origin: Optional[str],
    enqueue_fn: Optional[Callable[..., Dict[str, Any]]] = None,
    origin_builder: Optional[Callable[..., Dict[str, Any]]] = None,
    background_queue: Optional[str] = None,
) -> Dict[str, Any]:
    """Enqueue ONE observe child for a complete natural parent cycle.

    Gate order (fail SAFE to no-observation at every step):
      1. flag OFF → no-op;
      2. no capture → no-op (nothing was observed this cycle);
      3. non-scheduler parent → no-op (operator-forced scans cannot manufacture
         research evidence — mirrors the single-leg contract).
    The idempotency key ``regime_v4_shadow_compare:<cycle_id>:<code_sha>`` means a
    redeploy legitimately re-observes the same cycle under new code while a
    re-run under identical code is a no-op.  OBSERVE-ONLY: this never raises into
    the live cycle and never touches parent counts (the caller notes-only)."""
    if not is_observe_enabled():
        return {"status": "observe_disabled", "enqueued": False}
    if not capture or not (capture.get("basket_closes")):
        return {"status": "no_capture", "enqueued": False}
    if str(parent_origin or "") != NATURAL_PARENT_ORIGIN:
        return {"status": "non_natural_parent", "enqueued": False}

    cycle_id = str(source_decision_id or source_job_run_id or "").strip()
    if not cycle_id or not str(user_id or "").strip():
        return {"status": "source_identity_missing", "enqueued": False}

    code_sha = str(source_code_sha or "").strip() or "unknown"

    if enqueue_fn is None:
        from packages.quantum.public_tasks import enqueue_job_run as enqueue_fn
    if origin_builder is None:
        from packages.quantum.jobs.origin import build_event_origin as origin_builder

    payload = {
        "capture": dict(capture),
        "cycle_id": cycle_id,
        "source_job_run_id": str(source_job_run_id) if source_job_run_id else None,
        "source_code_sha": source_code_sha,
        "as_of": str(as_of) if as_of else capture.get("as_of"),
        "user_id": str(user_id),
    }
    try:
        if background_queue is None:
            # Lazy import (the constant lives in rq_enqueue, whose module-load
            # touches the RQ fork context — kept out of the live import graph and
            # injectable so the seam is hermetically testable). background/otc is
            # the §6 queue-routing discipline: observe/research work → background.
            from packages.quantum.jobs.rq_enqueue import BACKGROUND_QUEUE

            background_queue = BACKGROUND_QUEUE

        enqueued = enqueue_fn(
            job_name=JOB_NAME,
            idempotency_key=f"{JOB_NAME}:{cycle_id}:{code_sha}",
            payload=payload,
            queue_name=background_queue,
            origin=origin_builder(
                "regime_v4_shadow_after_decision",
                parent_job_run_id=(
                    str(source_job_run_id) if source_job_run_id else None
                ),
            ),
        )
    except Exception as exc:  # noqa: BLE001 — observe enqueue never breaks the cycle
        logger.warning(
            "[REGIME_V4_OBSERVE] enqueue failed (non-fatal): %s", str(exc)[:200]
        )
        return {
            "status": "enqueue_failed",
            "enqueued": False,
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
        }

    result = enqueued if isinstance(enqueued, dict) else {}
    terminal_skip = bool(result.get("skipped"))
    actually_queued = bool(result.get("rq_job_id")) and not terminal_skip
    return {
        "status": result.get("status", "queued"),
        "enqueued": actually_queued,
        "job_run_id": result.get("job_run_id"),
        "rq_job_id": result.get("rq_job_id"),
        "skipped": terminal_skip,
    }
