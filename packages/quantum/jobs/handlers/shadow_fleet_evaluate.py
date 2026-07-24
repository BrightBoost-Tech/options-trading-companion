"""Worker handler for the recurring independent shadow-fleet evaluator (C1).

Registered by convention (``JOB_NAME`` + ``run``) in the background worker. The
child evaluates the shared candidate universe under every active, bound
micro-account policy and persists typed decision evidence. While the fleet is
inactive it is a true no-op (readiness re-read + empty active-account set).
"""

from __future__ import annotations

from typing import Any, Dict

from packages.quantum.jobs.handlers.utils import get_admin_client
from packages.quantum.services.shadow_fleet_evaluate import (
    JOB_NAME,
    run_fleet_policy_eval,
)

__all__ = ["JOB_NAME", "run"]


def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    del ctx
    client = get_admin_client()
    return run_fleet_policy_eval(payload or {}, client=client)
