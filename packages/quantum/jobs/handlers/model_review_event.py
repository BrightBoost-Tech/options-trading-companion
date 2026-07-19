"""Event-driven model-review job handler (Lane J) — OBSERVE-ONLY.

Registered by JOB_NAME + run() (registry auto-discovery). Enqueued NOT by the
scheduler but by the learning-ingest tail detector
(``packages.quantum.analytics.model_review.evaluate_and_maybe_enqueue_review``)
when a new scorable close is persisted — origin ``event`` /
``new_scorable_close``, background queue.

It runs the signed/read-only terminal-distribution comparison over the
fingerprint's scorable outcome set (live vs shadow cohorts SEPARATE) and returns
a compact result. The runner persists that return into ``job_runs.result`` — the
ONLY output surface. This handler writes NOTHING to learning / calibration /
selectors / ranker / gates (observe-only, no calendar cadence).

WATCHDOG: deliberately ABSENT from ops_health_service.EXPECTED_JOBS — an
event-driven job has no cadence, so the job_late/never_run watchdog must not
expect it (an opt-in list; omission is the exemption). See the note beside
EXPECTED_JOBS.
"""

import logging
from typing import Any, Dict

from packages.quantum.jobs.handlers.utils import get_admin_client

logger = logging.getLogger(__name__)

JOB_NAME = "model_review_event"


def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """Run the observe-only model review for the enqueued fingerprint.

    Delegates to the shared review body. Returns the compact truth surface; the
    runner writes it to job_runs.result. counts.errors>0 in the return marks the
    run 'partial' (visible, terminal) rather than raising a retry storm — this
    is an observe-only review, not a live-risk job.
    """
    logger.info("[model_review_event] starting observe-only review: fingerprint=%s",
                str((payload or {}).get("fingerprint"))[:16])
    from packages.quantum.analytics.model_review import run_review

    client = get_admin_client()
    result = run_review(client, payload or {})
    logger.info(
        "[model_review_event] done: ok=%s scorable_count=%s errors=%s",
        result.get("ok"), result.get("scorable_count"),
        (result.get("counts") or {}).get("errors"),
    )
    return result
