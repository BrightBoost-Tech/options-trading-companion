"""
Paper Auto-Close Job Handler

v4-L1C: Automatically closes paper positions before checkpoint.

Part of Phase-3 streak automation:
- Fetches open paper positions for user
- Checks positions already closed today (deduplication)
- Closes up to PAPER_AUTOPILOT_MAX_CLOSES_PER_DAY (default 1)
- Uses oldest-first ordering for determinism
- Creates learning outcomes for checkpoint validation

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

JOB_NAME = "paper_auto_close"


def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """
    Close paper positions before checkpoint.

    Payload:
        - user_id: str - Target user UUID (required)
        - timestamp: str - Task trigger timestamp

    Returns:
        Dict with closed_count, error_count, etc.
    """
    user_id = payload.get("user_id")

    if not user_id:
        raise PermanentJobError("user_id is required for paper_auto_close")

    logger.info(f"[PAPER_AUTO_CLOSE] Starting for user {user_id}")

    try:
        client = get_admin_client()
        service = PaperAutopilotService(client)

        # Check if autopilot is enabled
        if not service.is_enabled():
            logger.info("[PAPER_AUTO_CLOSE] Autopilot is disabled, skipping")
            return {
                "ok": True,
                "status": "skipped",
                "reason": "autopilot_disabled",
                "closed_count": 0,
            }

        # Close positions
        result = service.close_positions(user_id)

        logger.info(
            f"[PAPER_AUTO_CLOSE] Complete for user {user_id}. "
            f"Closed: {result.get('closed_count', 0)}, "
            f"Errors: {result.get('error_count', 0)}"
        )

        return {
            "ok": result.get("status") == "ok",
            **result,
        }

    except Exception as e:
        logger.error(f"[PAPER_AUTO_CLOSE] Failed for user {user_id}: {e}")
        raise RetryableJobError(f"Paper auto-close failed: {e}")
