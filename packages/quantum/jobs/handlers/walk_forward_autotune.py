"""
Walk-Forward Autotune Job Handler

5:30 AM Chicago, Mondays — Weekly walk-forward parameter optimization.

Uses train/validate split on recent trade history. Only promotes
parameter changes that improve out-of-sample performance.

Feature flags:
  AUTOTUNE_ENABLED       — must be "1" to run
  AUTOTUNE_AUTOPROMOTE   — "1" to auto-apply promoted changes
"""

import time
from datetime import datetime, timezone
from typing import Any, Dict

from packages.quantum.jobs.handlers.utils import get_admin_client, get_active_user_ids, run_async
from packages.quantum.jobs.handlers.exceptions import RetryableJobError, PermanentJobError

JOB_NAME = "walk_forward_autotune"


def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """
    Run walk-forward autotune for all active users.

    Payload:
        - lookback_days: int (default 60)
        - user_id: str|None
        - cohort_name: str|None
    """
    from packages.quantum.analytics.walk_forward_autotune import (
        AUTOTUNE_ENABLED,
        WalkForwardAutotune,
    )

    if not AUTOTUNE_ENABLED:
        return {"status": "disabled", "reason": "AUTOTUNE_ENABLED != 1"}

    start_time = time.time()
    lookback_days = payload.get("lookback_days", 60)
    target_user_id = payload.get("user_id")
    cohort_name = payload.get("cohort_name")

    try:
        client = get_admin_client()

        if target_user_id:
            active_users = [target_user_id]
        else:
            active_users = get_active_user_ids(client)

        async def process_users():
            results = []
            for uid in active_users:
                wfa = WalkForwardAutotune(client)
                result = wfa.run_autotune_cycle(
                    uid, lookback_days=lookback_days, cohort_name=cohort_name,
                )
                results.append({"user_id": uid[:8], **result})
            return results

        user_results = run_async(process_users())

        promoted_total = sum(
            len(r.get("promoted", [])) for r in user_results
        )

        return {
            "ok": True,
            "users_processed": len(user_results),
            "promoted_total": promoted_total,
            "lookback_days": lookback_days,
            "timing_ms": (time.time() - start_time) * 1000,
            "results": user_results[:10],  # Cap output size
        }

    except ValueError as e:
        raise PermanentJobError(f"Configuration error: {e}")
    except Exception as e:
        raise RetryableJobError(f"Walk-forward autotune failed: {e}")
