"""Read-only verification of persisted decision-tape aggregate hashes.

This reader never calls a market-data provider and never reconstructs a trade.
It proves that the durable ``decision_inputs`` and ``decision_features`` rows
still conserve the aggregate hashes and counts recorded on ``decision_runs``.
"""

from typing import Any, Dict, List, Optional

from packages.quantum.services.replay.canonical import compute_aggregate_hash


def _aggregate(values: List[str]) -> Optional[str]:
    return compute_aggregate_hash(sorted(values)) if values else None


def verify_decision_tape_hashes(client: Any, decision_id: str) -> Dict[str, Any]:
    """Verify one persisted decision tape without any live-data reads."""
    try:
        run_result = (
            client.table("decision_runs")
            .select(
                "decision_id,input_hash,features_hash,inputs_count,"
                "features_count,tape_integrity"
            )
            .eq("decision_id", decision_id)
            .single()
            .execute()
        )
        run = run_result.data
        if not run:
            return {
                "decision_id": decision_id,
                "status": "error",
                "reason": "decision_not_found",
                "counts": {"errors": 1},
            }

        input_result = (
            client.table("decision_inputs")
            .select("blob_hash")
            .eq("decision_id", decision_id)
            .execute()
        )
        feature_result = (
            client.table("decision_features")
            .select("features_hash")
            .eq("decision_id", decision_id)
            .execute()
        )
        inputs = input_result.data or []
        features = feature_result.data or []

        input_values = [row.get("blob_hash") for row in inputs]
        feature_values = [row.get("features_hash") for row in features]
        malformed = any(not isinstance(value, str) or not value for value in (
            input_values + feature_values
        ))
        computed_input_hash = None if malformed else _aggregate(input_values)
        computed_features_hash = None if malformed else _aggregate(feature_values)

        checks = {
            "input_hash": computed_input_hash == run.get("input_hash"),
            "features_hash": computed_features_hash == run.get("features_hash"),
            "inputs_count": len(inputs) == int(run.get("inputs_count") or 0),
            "features_count": len(features) == int(run.get("features_count") or 0),
            "tape_integrity_complete": run.get("tape_integrity") == "complete",
            "row_hashes_well_formed": not malformed,
        }
        mismatches = sorted(name for name, passed in checks.items() if not passed)
        return {
            "decision_id": decision_id,
            "status": "ok" if not mismatches else "mismatch",
            "reason": None if not mismatches else "tape_hash_mismatch",
            "checks": checks,
            "mismatches": mismatches,
            "stored": {
                "input_hash": run.get("input_hash"),
                "features_hash": run.get("features_hash"),
                "inputs_count": run.get("inputs_count"),
                "features_count": run.get("features_count"),
            },
            "computed": {
                "input_hash": computed_input_hash,
                "features_hash": computed_features_hash,
                "inputs_count": len(inputs),
                "features_count": len(features),
            },
            "counts": {"errors": 0 if not mismatches else 1},
        }
    except Exception as exc:
        return {
            "decision_id": decision_id,
            "status": "error",
            "reason": "tape_read_failed",
            "error": f"{type(exc).__name__}: {str(exc)[:300]}",
            "counts": {"errors": 1},
        }

