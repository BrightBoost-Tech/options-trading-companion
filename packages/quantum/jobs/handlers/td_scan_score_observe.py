"""⑤ Score-on-scan observer job handler (OBSERVE-ONLY, background queue).

Registered by JOB_NAME + run() (registry auto-discovery). Enqueued NOT by the
scheduler but by the ``suggestions_open`` tail
(``services.td_scan_observe.maybe_enqueue_td_scan_observe``) when a complete
natural decision tape commits AND the observe-only flag is on — origin
``event`` / ``td_scan_score_after_decision``, background queue.

It reads the cycle's scan-time research-candidate envelopes and scores each
(current frozen production-math baseline vs the lognormal challenger) via the
``scripts.analytics`` scorer, then upserts one ``td_scan_scores`` row per
candidate. The runner persists this return into ``job_runs.result``. This
handler writes ONLY its result table + job_runs.result — it never gates, ranks,
sizes, stages, submits, or names the observe-only scoring package.

WATCHDOG: deliberately ABSENT from ops_health_service.EXPECTED_JOBS — an
event-driven job has no cadence (an opt-in list; omission is the exemption),
exactly like ``model_review_event``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from packages.quantum.jobs.handlers.utils import get_admin_client

logger = logging.getLogger(__name__)

JOB_NAME = "td_scan_score_observe"


def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """Run the observe-only score-on-scan pass for the enqueued cycle.

    Delegates to the shared child body. Returns the compact result; the runner
    writes it to job_runs.result. counts.errors>0 in the return marks the run
    'partial' (visible, terminal) rather than raising a retry storm — this is an
    observe-only pass, not a live-risk job.
    """
    del ctx
    from packages.quantum.services.td_scan_observe import run_td_scan_score_observe

    client = get_admin_client()
    result = run_td_scan_score_observe(client, payload or {})
    logger.info(
        "[td_scan_score_observe] done: ok=%s scored=%s written=%s errors=%s",
        result.get("ok"),
        (result.get("counts") or {}).get("scored"),
        (result.get("counts") or {}).get("written"),
        (result.get("counts") or {}).get("errors"),
    )
    return result
