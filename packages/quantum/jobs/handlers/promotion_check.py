"""
Promotion Check Job Handler

Runs daily after market close. Detects users stuck in a phase
that requires manual promotion and logs a CRITICAL alert so
ops_health_check / monitoring can surface it.

This is a read-only job — it does NOT auto-promote. It ensures
that stuck transitions are never silent.
"""

import logging
import time
from typing import Any, Dict

from packages.quantum.services.progression_service import ProgressionService
from packages.quantum.jobs.handlers.utils import get_admin_client, get_active_user_ids
from packages.quantum.jobs.handlers.exceptions import RetryableJobError

logger = logging.getLogger(__name__)

JOB_NAME = "promotion_check"

# Phase → required green days for next promotion
PROMOTION_REQUIREMENTS = {
    "micro_live": {"green_days_field": "micro_live_green_days", "required": 5},
}


def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """
    Check all active users for stuck phase transitions.
    Logs CRITICAL when a user is promotion-ready but stuck.
    """
    start_time = time.time()

    try:
        client = get_admin_client()
        users = get_active_user_ids(client)
        alerts = []

        for uid in users:
            try:
                svc = ProgressionService(client)
                state = svc.get_state(uid)
                phase = state.get("current_phase", "")

                if phase in PROMOTION_REQUIREMENTS:
                    req = PROMOTION_REQUIREMENTS[phase]
                    green_days = state.get(req["green_days_field"], 0)
                    required = req["required"]

                    alert = {
                        "user_id": uid[:8],
                        "phase": phase,
                        "green_days": green_days,
                        "required": required,
                    }

                    if green_days >= required:
                        alert["action_needed"] = "manual_promote"
                        logger.critical(
                            f"[PROMOTION_CHECK] User {uid[:8]} READY for promotion "
                            f"from {phase} ({green_days}/{required} green days). "
                            f"Requires manual approval."
                        )
                    else:
                        alert["action_needed"] = "wait"
                        logger.info(
                            f"[PROMOTION_CHECK] User {uid[:8]} in {phase}: "
                            f"{green_days}/{required} green days"
                        )

                    alerts.append(alert)

            except Exception as e:
                logger.error(f"[PROMOTION_CHECK] Error checking {uid[:8]}: {e}")

        # Also check for cancelled go_live_gate jobs today (silent failures)
        try:
            from datetime import datetime, timezone
            today_str = datetime.now(timezone.utc).date().isoformat()
            cancelled_res = client.table("job_runs") \
                .select("id, job_name, cancelled_reason, cancelled_detail") \
                .eq("cancelled_reason", "go_live_gate") \
                .gte("created_at", today_str) \
                .execute()
            cancelled = cancelled_res.data or []
            if cancelled:
                logger.critical(
                    f"[PROMOTION_CHECK] {len(cancelled)} jobs cancelled today by "
                    f"go_live_gate — users may be stuck in micro_live: "
                    f"{[c.get('job_name') for c in cancelled[:5]]}"
                )
                alerts.append({
                    "type": "go_live_gate_cancellations",
                    "count": len(cancelled),
                    "jobs": [c.get("job_name") for c in cancelled[:5]],
                })
        except Exception as e:
            logger.warning(f"[PROMOTION_CHECK] Could not check cancelled jobs: {e}")

        timing_ms = (time.time() - start_time) * 1000

        promotion_ready = [a for a in alerts if a.get("action_needed") == "manual_promote"]
        if promotion_ready:
            logger.critical(
                f"[PROMOTION_CHECK] SUMMARY: {len(promotion_ready)} user(s) need "
                f"manual promotion: {[a['user_id'] for a in promotion_ready]}"
            )

        return {
            "ok": True,
            "alerts": alerts,
            "promotion_ready_count": len(promotion_ready),
            "timing_ms": timing_ms,
        }

    except Exception as e:
        raise RetryableJobError(f"Promotion check failed: {e}")
