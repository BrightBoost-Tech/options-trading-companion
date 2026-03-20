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


def run(payload: Dict[str, Any], supabase=None) -> Dict[str, Any]:
    """
    Evaluate Policy Lab cohorts and check for promotions.

    Payload:
        user_id: str (required)
    """
    if not os.environ.get("POLICY_LAB_ENABLED", "").lower() in ("1", "true"):
        return {"status": "disabled", "reason": "POLICY_LAB_ENABLED is not set"}

    user_id = payload.get("user_id")
    if not user_id:
        return {"status": "error", "reason": "user_id required"}

    if supabase is None:
        from packages.quantum.security.supabase_config import get_admin_client
        supabase = get_admin_client()

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
