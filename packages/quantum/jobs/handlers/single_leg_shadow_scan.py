"""Worker handler for the internal single-leg shadow scan child job."""

from __future__ import annotations

from typing import Any, Dict

from packages.quantum.jobs.handlers.utils import get_admin_client
from packages.quantum.services.single_leg_shadow_lifecycle import (
    execute_run_candidates,
)
from packages.quantum.services.single_leg_shadow_scan import (
    JOB_NAME,
    run_single_leg_shadow_scan,
)


def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    del ctx
    client = get_admin_client()
    result = run_single_leg_shadow_scan(payload or {}, client=client)

    execution_totals = {
        "candidates": 0,
        "filled_internal": 0,
        "execution_rejected": 0,
        "idempotent_replays": 0,
        "errors": 0,
    }
    for policy_result in result.get("policy_results") or []:
        run_id = policy_result.get("run_id")
        if not run_id:
            continue
        execution = execute_run_candidates(client, str(run_id))
        policy_result["execution"] = execution
        for key in execution_totals:
            execution_totals[key] += int(
                (execution.get("counts") or {}).get(key) or 0
            )

    result["execution"] = execution_totals
    if execution_totals["errors"]:
        counts = result.setdefault("counts", {})
        counts["errors"] = int(counts.get("errors") or 0) + execution_totals["errors"]
        result["ok"] = False
        result["status"] = "partial"
    return result
