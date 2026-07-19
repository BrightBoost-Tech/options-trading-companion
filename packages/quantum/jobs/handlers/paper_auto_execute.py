"""
Paper Auto-Execute Job Handler

v4-L1C: Automatically executes top executable suggestions for paper trading.

Part of Phase-3 streak automation:
- Fetches today's executable (pending) suggestions
- Selects top N based on score (PAPER_AUTOPILOT_MAX_TRADES_PER_DAY)
- Filters by min score (PAPER_AUTOPILOT_MIN_SCORE)
- Deduplicates against already-executed today
- Stages and executes via paper trading service

Requirements:
- PAPER_AUTOPILOT_ENABLED=1
- ops_state.mode == "paper"
- Specific user_id (not "all")
"""

import logging
from typing import Any, Dict

from packages.quantum.services.paper_autopilot_service import PaperAutopilotService
from packages.quantum.jobs.handlers.utils import get_admin_client
from packages.quantum.jobs.handlers.exceptions import RetryableJobError, PermanentJobError

logger = logging.getLogger(__name__)

JOB_NAME = "paper_auto_execute"


def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """
    Execute top suggestions for paper trading.

    Payload:
        - user_id: str - Target user UUID (required)
        - timestamp: str - Task trigger timestamp

    Returns:
        Dict with executed_count, skipped_count, errors, etc.
    """
    user_id = payload.get("user_id")

    if not user_id:
        raise PermanentJobError("user_id is required for paper_auto_execute")

    logger.info(f"[PAPER_AUTO_EXECUTE] Starting for user {user_id}")

    try:
        client = get_admin_client()
        service = PaperAutopilotService(client)

        # Check if autopilot is enabled
        if not service.is_enabled():
            logger.info("[PAPER_AUTO_EXECUTE] Autopilot is disabled, skipping")
            return {
                "ok": True,
                "status": "skipped",
                "reason": "autopilot_disabled",
                "executed_count": 0,
            }

        # Execute top suggestions.
        #
        # F-A4-RISKBASIS-SILENT (2026-07-19): open a per-cycle arm-evidence
        # scope so the utilization-gate comparison seam (buried in
        # _execute_per_cohort) records durable P0-B arm evidence; drain it into
        # job_runs.result.cycle_metadata.risk_basis_arm_evidence (no migration).
        # OBSERVE-ONLY — decisions are byte-identical; a persist fault folds to
        # counts.errors → the runner classifies the run 'partial' (never silent).
        from packages.quantum.services import risk_basis_shadow as rbs
        with rbs.arm_evidence_scope(cycle_id=f"paper_auto_execute:{user_id}") as _arm:
            result = service.execute_top_suggestions(user_id)
        result = rbs.persist_arm_evidence(
            result, _arm.rows, _arm.errors, cycle_id=_arm.cycle_id
        )

        logger.info(
            f"[PAPER_AUTO_EXECUTE] Complete for user {user_id}. "
            f"Executed: {result.get('executed_count', 0)}, "
            f"Skipped: {result.get('skipped_count', 0)}, "
            f"Errors: {result.get('error_count', 0)}"
        )

        return {
            "ok": result.get("status") == "ok"
            and not int((result.get("counts") or {}).get("errors") or 0),
            **result,
        }

    except Exception as e:
        logger.error(f"[PAPER_AUTO_EXECUTE] Failed for user {user_id}: {e}")
        raise RetryableJobError(f"Paper auto-execute failed: {e}")
