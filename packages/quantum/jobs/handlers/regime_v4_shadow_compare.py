"""Worker handler for the Regime-V4 observe-only shadow-comparison child job.

Runs on the ``background`` queue (enqueued from the ``suggestions_open`` tail via
``maybe_enqueue_regime_v4_shadow_compare``).  Observe-only: zero provider calls
(the child's shim blocks every fetch), zero writes to any live decision surface.
"""

from __future__ import annotations

from typing import Any, Dict

from packages.quantum.jobs.handlers.utils import get_admin_client
from packages.quantum.analytics.regime_v4_shadow_capture import JOB_NAME
from packages.quantum.analytics.regime_v4_shadow_compare import (
    run_regime_v4_shadow_compare,
)


def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    del ctx
    client = get_admin_client()
    return run_regime_v4_shadow_compare(payload or {}, client=client)
