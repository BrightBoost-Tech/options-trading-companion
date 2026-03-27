"""
Calibration Update Job Handler

5:00 AM Chicago — Recompute calibration adjustments from recent outcomes.

Runs daily before market open. Computes per-(strategy, regime)
EV and PoP multipliers from the last 30 days of closed positions,
then caches them in calibration_adjustments for fast lookup during
suggestion scoring.

Requires MIN_CALIBRATION_TRADES (default 20) outcomes to produce
adjustments. Below that threshold, no adjustments are stored (raw
predictions are used as-is).
"""

import time
from datetime import datetime, timezone
from typing import Any, Dict

from packages.quantum.jobs.handlers.utils import get_admin_client, get_active_user_ids, run_async
from packages.quantum.jobs.handlers.exceptions import RetryableJobError, PermanentJobError

JOB_NAME = "calibration_update"


def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """
    Recompute calibration adjustments for all active users.

    Payload:
        - window_days: int - Lookback window (default: 30)
        - user_id: str|None - Specific user, or all if None
    """
    start_time = time.time()
    window_days = payload.get("window_days", 30)
    target_user_id = payload.get("user_id")

    try:
        client = get_admin_client()

        if target_user_id:
            active_users = [target_user_id]
        else:
            active_users = get_active_user_ids(client)

        async def process_users():
            from packages.quantum.analytics.calibration_service import (
                CalibrationService,
                MIN_CALIBRATION_TRADES,
            )

            users_updated = 0
            users_skipped = 0

            for uid in active_users:
                svc = CalibrationService(client)
                result = svc.compute_calibration_adjustments(uid, window_days=window_days)

                if result.get("status") != "ok":
                    users_skipped += 1
                    continue

                # Cache adjustments
                try:
                    client.table("calibration_adjustments").insert({
                        "user_id": uid,
                        "adjustments": result["adjustments"],
                        "total_outcomes": result["total_outcomes"],
                        "computed_at": datetime.now(timezone.utc).isoformat(),
                    }).execute()
                    users_updated += 1
                except Exception as e:
                    print(f"[CALIBRATION] Failed to cache for {uid[:8]}: {e}")
                    users_skipped += 1

            return users_updated, users_skipped

        updated, skipped = run_async(process_users())

        timing_ms = (time.time() - start_time) * 1000

        return {
            "ok": True,
            "users_updated": updated,
            "users_skipped": skipped,
            "window_days": window_days,
            "timing_ms": timing_ms,
        }

    except ValueError as e:
        raise PermanentJobError(f"Configuration error: {e}")
    except Exception as e:
        raise RetryableJobError(f"Calibration update failed: {e}")
