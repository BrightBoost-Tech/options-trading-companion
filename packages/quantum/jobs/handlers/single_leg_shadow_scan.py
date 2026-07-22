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


def _persist_execution_summary(
    client: Any,
    policy_result: Dict[str, Any],
    execution: Dict[str, Any],
) -> bool:
    run_id = policy_result.get("run_id")
    if not run_id:
        return False
    scan_counts = dict(policy_result.get("counts") or {})
    execution_counts = dict(execution.get("counts") or {})
    status = (
        "partial"
        if int(execution_counts.get("errors") or 0)
        else str(policy_result.get("status") or "succeeded")
    )
    row = {
        "status": status,
        "counts": {**scan_counts, "execution": execution_counts},
        "error_details": list(execution.get("error_details") or [])[:10],
    }
    response = (
        client.table("single_leg_shadow_runs")
        .update(row)
        .eq("run_id", str(run_id))
        .execute()
    )
    return response is not None


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
        try:
            persisted = _persist_execution_summary(client, policy_result, execution)
        except Exception as exc:
            persisted = False
            policy_result.setdefault("execution_persist_error", {})
            policy_result["execution_persist_error"] = {
                "error_class": type(exc).__name__,
                "error": str(exc)[:200],
            }
        if not persisted:
            execution_totals["errors"] += 1

    result["execution"] = execution_totals
    if execution_totals["errors"]:
        counts = result.setdefault("counts", {})
        counts["errors"] = int(counts.get("errors") or 0) + execution_totals["errors"]
        result["ok"] = False
        result["status"] = "partial"
    return result
