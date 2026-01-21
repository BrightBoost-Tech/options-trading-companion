import logging
import traceback
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List

from packages.quantum.jobs.db import create_supabase_admin_client
from packages.quantum.observability.audit_log_service import AuditLogService
from packages.quantum.observability.lineage import LineageSigner, get_code_sha

JOB_NAME = "regression_determinism"

logger = logging.getLogger(__name__)

def run(payload: Dict[str, Any], ctx=None) -> Dict[str, Any]:
    """
    Job handler for Regression & Determinism agent.

    Validates the integrity of trading engine suggestions by checking:
    1. Presence of required lineage/observability fields
    2. Cryptographic signature validity
    3. Code drift detection

    Payload:
      - lookback_days: int (default: 1)
      - mode: str (default: "daily")
    """
    logger.info(f"Starting {JOB_NAME} job with payload: {payload}")

    try:
        supabase = create_supabase_admin_client()
        if not supabase:
            return {"error": "Database unavailable"}

        audit_service = AuditLogService(supabase)
        current_code_sha = get_code_sha()

        # 1. Determine lookback window
        lookback_days = payload.get("lookback_days", 1)
        cutoff_date = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()

        # 2. Query trade_suggestions
        # We need specific fields to validate integrity
        logger.info(f"Querying trade_suggestions since {cutoff_date}")

        # Note: We select all columns needed for validation.
        # Ideally we would check if these columns exist, but we assume schema compliance.
        response = supabase.table("trade_suggestions") \
            .select("id, trace_id, features_hash, lineage_hash, code_sha, data_hash, lineage_sig, created_at") \
            .gte("created_at", cutoff_date) \
            .execute()

        suggestions = response.data or []
        logger.info(f"Found {len(suggestions)} suggestions to validate")

        # 3. Validate "Minimal Viable Replay" integrity
        stats = {
            "total_checked": 0,
            "integrity_failures": 0,
            "code_drift_count": 0,
            "data_drift_count": 0,
            "failures_details": []
        }

        for s in suggestions:
            stats["total_checked"] += 1
            s_id = s.get("id")

            # Check required fields presence
            required_fields = ["trace_id", "features_hash", "lineage_hash", "code_sha", "data_hash"]
            missing_fields = [f for f in required_fields if not s.get(f)]

            if missing_fields:
                stats["integrity_failures"] += 1
                stats["failures_details"].append({
                    "id": s_id,
                    "reason": "missing_fields",
                    "details": missing_fields
                })
                # We continue checking other aspects if possible,
                # but missing lineage_hash or code_sha might block specific checks.

            # Check lineage signature (authenticity)
            # We verify that the stored signature matches the stored hash
            lineage_hash = s.get("lineage_hash")
            lineage_sig = s.get("lineage_sig")

            if lineage_sig and lineage_hash:
                # verify_with_hash checks if signature is valid for the hash
                # We don't have the full lineage body here to recompute hash,
                # so we trust the hash matches the data (which is a separate check if we loaded full data)
                # But here we at least verify the signature signs the hash correctly.
                is_valid, _, status = LineageSigner.verify_with_hash(
                    stored_hash=lineage_hash,
                    stored_signature=lineage_sig
                )

                if not is_valid:
                    # TAMPERED or UNVERIFIED (if secret missing)
                    # We count TAMPERED as data drift/integrity issue
                    if status == "TAMPERED":
                        stats["data_drift_count"] += 1
                        stats["failures_details"].append({
                            "id": s_id,
                            "reason": "signature_mismatch",
                            "details": status
                        })
            else:
                # Missing signature is an integrity failure? Or just data drift?
                # Prompt says "Verify the lineage_sig (if available)"
                # If it's not available, maybe it's fine for older records?
                # But for v4 it should be there. Let's count as integrity failure if missing but hash present?
                # Actually, prompt says "Ensure ... present", but lineage_sig is "if available".
                # Let's verify if present.
                pass

            # Check code drift
            stored_code_sha = s.get("code_sha")
            if stored_code_sha and stored_code_sha != current_code_sha:
                stats["code_drift_count"] += 1

        # 4. Output results
        summary = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "lookback_days": lookback_days,
            "mode": payload.get("mode", "daily"),
            "current_code_sha": current_code_sha,
            "stats": {k: v for k, v in stats.items() if k != "failures_details"},
            # Limit details in summary to avoid huge payload
            "failures_sample": stats["failures_details"][:20]
        }

        logger.info(f"Regression report: {summary['stats']}")

        # Insert summary into decision_audit_events
        audit_service.log_audit_event(
            user_id="system",  # System level event
            trace_id=f"regression-{datetime.now(timezone.utc).strftime('%Y%m%d')}",
            event_name="v4_regression_report",
            payload=summary
        )

        return {
            "status": "completed",
            "result": summary
        }

    except Exception as e:
        logger.error(f"{JOB_NAME} failed: {e}")
        logger.error(traceback.format_exc())
        return {"status": "failed", "error": str(e)}
