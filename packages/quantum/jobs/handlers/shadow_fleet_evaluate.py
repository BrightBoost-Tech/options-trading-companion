"""Worker handler for the recurring independent shadow-fleet evaluator.

Registered by convention (``JOB_NAME`` + ``run``) in the background worker.

C1: evaluate the shared candidate universe under every active, bound
micro-account policy and persist typed decision evidence.
C2: for the SELECTED decisions, open isolated internal-paper multi-leg positions
via the atomic fleet open RPC (a no-op while the fleet is inactive — no selected
decisions exist and the RPC rejects every call regardless).

The fleet open-position count feeds C1's capacity axis through a fail-closed
loader. While the fleet is inactive both stages are true no-ops.
"""

from __future__ import annotations

from typing import Any, Dict

from packages.quantum.jobs.handlers.utils import get_admin_client
from packages.quantum.services.shadow_fleet_evaluate import (
    JOB_NAME,
    run_fleet_policy_eval,
)
from packages.quantum.services.shadow_fleet_lifecycle import (
    count_open_fleet_positions,
    execute_fleet_selected_for_source,
)

__all__ = ["JOB_NAME", "run"]


def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    del ctx
    client = get_admin_client()
    # C1: decision evidence. Capacity reads the real per-account open-position
    # count (fail-closed) so a read error is evaluator_failed, never a silent 0.
    result = run_fleet_policy_eval(
        payload or {},
        client=client,
        open_positions_loader=count_open_fleet_positions,
    )

    # C2: open selected candidates. Gated on the eval having actually run AND
    # produced selections — while the fleet is inactive `status` is
    # `fleet_inactive` (no source_decision_id, no selections), so this is skipped
    # entirely and no lifecycle read/write occurs.
    counts = result.get("counts") or {}
    if (
        result.get("status") in ("succeeded", "partial")
        and int(counts.get("selected") or 0) > 0
        and result.get("source_decision_id")
    ):
        lifecycle = execute_fleet_selected_for_source(
            client,
            str(result["source_decision_id"]),
            fleet_epoch=str(result.get("fleet_epoch") or "small_tier_v1"),
        )
        result["lifecycle"] = lifecycle
        lc_errors = int((lifecycle.get("counts") or {}).get("errors") or 0)
        if lc_errors:
            result["counts"]["errors"] = int(counts.get("errors") or 0) + lc_errors
            result["ok"] = False
            result["status"] = "partial"

    return result
