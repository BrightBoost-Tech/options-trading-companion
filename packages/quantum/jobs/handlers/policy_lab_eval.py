"""
Policy Lab Evaluation Job Handler

Runs daily after market close (after MTM + learning ingest).
Computes cohort performance metrics and checks promotion eligibility.

Gated behind POLICY_LAB_ENABLED.
"""

import logging
import os
from datetime import date
from typing import Dict, Any

logger = logging.getLogger(__name__)

JOB_NAME = "policy_lab_eval"


def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """
    Evaluate Policy Lab cohorts and check for promotions.

    Payload:
        user_id: str (required)
    """
    if not os.environ.get("POLICY_LAB_ENABLED", "").lower() in ("1", "true"):
        return {"status": "disabled", "reason": "POLICY_LAB_ENABLED is not set"}

    user_id = payload.get("user_id")
    if not user_id:
        # If no user_id in payload, try all active users
        from packages.quantum.jobs.handlers.utils import get_admin_client, get_active_user_ids
        supabase = get_admin_client()
        user_ids = get_active_user_ids(supabase)
        if not user_ids:
            return {"status": "error", "reason": "no active users found"}
        # Process all users and aggregate results
        all_results = []
        for uid in user_ids:
            r = _evaluate_user(uid, supabase)
            all_results.append(r)
        return {"status": "ok", "users": len(all_results), "results": all_results}

    from packages.quantum.jobs.handlers.utils import get_admin_client
    supabase = get_admin_client()
    return _evaluate_user(user_id, supabase)


def _evaluate_user(user_id: str, supabase) -> Dict[str, Any]:

    from packages.quantum.policy_lab.evaluator import evaluate_cohorts, check_promotion

    eval_date = date.today()
    eval_result = evaluate_cohorts(user_id, eval_date, supabase)
    promo_result = check_promotion(user_id, supabase)

    logger.info(
        f"policy_lab_eval_complete: user={user_id} date={eval_date} "
        f"eval_status={eval_result.get('status')} promo_status={promo_result.get('status')}"
    )

    return {
        "status": "ok",
        "evaluation": eval_result,
        "promotion": promo_result,
    }
