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

        # ── Resting-TP sweep (06-12 pilot) ────────────────────────────
        # Flag-gated (GTC_PROFIT_EXIT_ENABLED; OFF → pure no-op) + pilot-
        # scoped. Runs AFTER evaluate_exits so the 8:35 CT slot places on
        # post-refresh state, never the opening auction. Fail-soft: a sweep
        # error can never fail the exit evaluation job.
        try:
            from packages.quantum.services.gtc_profit_exit import (
                place_resting_tp_for_open_positions,
            )
            sweep = place_resting_tp_for_open_positions(client, user_id)
            if sweep.get("placed") or sweep.get("skipped"):
                logger.info(f"[PAPER_EXIT_EVALUATE] resting-TP sweep: {sweep}")
            result["resting_tp_sweep"] = sweep
        except Exception as sweep_err:
            logger.error(
                f"[PAPER_EXIT_EVALUATE] resting-TP sweep failed "
                f"(non-fatal): {sweep_err}"
            )
            result["resting_tp_sweep"] = {"error": str(sweep_err)[:200]}

        # Independent single-leg shadow positions hold to expiry in v1. The
        # settlement service writes only dedicated internal-paper tables/RPCs;
        # it never enters the normal paper/live position evaluator or a broker.
        try:
            from packages.quantum.services.single_leg_shadow_lifecycle import (
                settle_expired_positions,
            )

            shadow_settlement = settle_expired_positions(client, user_id)
        except Exception as shadow_err:
            logger.exception("[PAPER_EXIT_EVALUATE] single-leg settlement crashed")
            shadow_settlement = {
                "status": "settlement_seam_crashed",
                "counts": {"errors": 1},
                "error_details": [
                    {
                        "stage": "settlement_seam",
                        "error_class": type(shadow_err).__name__,
                        "error": str(shadow_err)[:200],
                    }
                ],
            }
        result["single_leg_shadow_settlement"] = shadow_settlement

        settlement_errors = int(
            (shadow_settlement.get("counts") or {}).get("errors") or 0
        )
        if settlement_errors:
            counts = result.setdefault("counts", {})
            counts["errors"] = int(counts.get("errors") or 0) + settlement_errors

        return {"ok": settlement_errors == 0, **result}

    except Exception as e:
        logger.error(f"[PAPER_EXIT_EVALUATE] Failed for user {user_id}: {e}")
        raise RetryableJobError(f"Paper exit evaluation failed: {e}")
