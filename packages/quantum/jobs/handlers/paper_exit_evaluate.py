"""
Paper Exit Evaluator Job Handler

Checks open paper positions against condition-based exit rules and closes
only those that trigger (target profit, stop loss, DTE threshold, expiration).

Replaces the blanket EOD force-close with intelligent exits.

Schedule: 3:00 PM CDT (before mark-to-market at 3:30 PM).
"""

import logging
from typing import Any, Dict

from packages.quantum.services.paper_exit_evaluator import PaperExitEvaluator
from packages.quantum.jobs.handlers.utils import get_admin_client
from packages.quantum.jobs.handlers.exceptions import RetryableJobError, PermanentJobError

logger = logging.getLogger(__name__)

JOB_NAME = "paper_exit_evaluate"


def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """
    Evaluate exit conditions on all open positions.

    Payload:
        - user_id: str - Target user UUID (required)
    """
    user_id = payload.get("user_id")

    if not user_id:
        raise PermanentJobError("user_id is required for paper_exit_evaluate")

    logger.info(f"[PAPER_EXIT_EVALUATE] Starting for user {user_id}")

    try:
        client = get_admin_client()
        evaluator = PaperExitEvaluator(client)

        result = evaluator.evaluate_exits(user_id)

        logger.info(
            f"[PAPER_EXIT_EVALUATE] Complete for user {user_id}. "
            f"Closing: {result.get('closing', 0)}, "
            f"Holding: {result.get('holding', 0)}, "
            f"Reasons: {result.get('close_reasons', {})}"
        )

        return {"ok": True, **result}

    except Exception as e:
        logger.error(f"[PAPER_EXIT_EVALUATE] Failed for user {user_id}: {e}")
        raise RetryableJobError(f"Paper exit evaluation failed: {e}")
