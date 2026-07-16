"""Operator-triggered, read-only decision-tape hash verification."""

from typing import Any, Dict, List

from packages.quantum.jobs.handlers.utils import get_admin_client
from packages.quantum.services.replay.tape_hash_verifier import (
    verify_decision_tape_hashes,
)


JOB_NAME = "replay_integrity_check"


def _recent_complete_decision_ids(client: Any, limit: int) -> List[str]:
    result = (
        client.table("decision_runs")
        .select("decision_id")
        .eq("tape_integrity", "complete")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return [row["decision_id"] for row in (result.data or [])]


def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """Verify one named tape or the latest complete tapes (default 20)."""
    client = get_admin_client()
    requested_id = (payload or {}).get("decision_id")
    try:
        limit = int((payload or {}).get("limit", 20))
    except (TypeError, ValueError):
        return {
            "status": "error",
            "reason": "invalid_limit",
            "counts": {"checked": 0, "mismatches": 0, "errors": 1},
        }
    if limit < 1 or limit > 100:
        return {
            "status": "error",
            "reason": "invalid_limit",
            "counts": {"checked": 0, "mismatches": 0, "errors": 1},
        }

    try:
        decision_ids = (
            [str(requested_id)]
            if requested_id
            else _recent_complete_decision_ids(client, limit)
        )
    except Exception as exc:
        return {
            "status": "error",
            "reason": "decision_list_failed",
            "error": f"{type(exc).__name__}: {str(exc)[:300]}",
            "counts": {"checked": 0, "mismatches": 0, "errors": 1},
        }

    results = [verify_decision_tape_hashes(client, item) for item in decision_ids]
    mismatches = sum(item.get("status") == "mismatch" for item in results)
    errors = sum(item.get("status") == "error" for item in results)
    return {
        "status": "ok" if not (mismatches or errors) else "partial",
        "observation_scope": "persisted_tape_integrity_only",
        "live_reads": 0,
        "results": results,
        "counts": {
            "checked": len(results),
            "mismatches": mismatches,
            "errors": mismatches + errors,
        },
    }

