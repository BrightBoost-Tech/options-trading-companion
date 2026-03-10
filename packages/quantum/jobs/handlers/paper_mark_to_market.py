"""
Paper Mark-to-Market Job Handler

Refreshes current_mark and unrealized_pl on all open paper positions,
then saves an EOD snapshot for checkpoint evaluation.

Schedule: 3:30 PM CDT (while quotes are still live, before checkpoint).
"""

import logging
from typing import Any, Dict

from packages.quantum.services.paper_mark_to_market_service import PaperMarkToMarketService
from packages.quantum.jobs.handlers.utils import get_admin_client
from packages.quantum.jobs.handlers.exceptions import RetryableJobError, PermanentJobError

logger = logging.getLogger(__name__)

JOB_NAME = "paper_mark_to_market"


def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """
    Refresh marks and save EOD snapshot.

    Payload:
        - user_id: str - Target user UUID (required)
    """
    user_id = payload.get("user_id")

    if not user_id:
        raise PermanentJobError("user_id is required for paper_mark_to_market")

    logger.info(f"[PAPER_MARK_TO_MARKET] Starting for user {user_id}")

    try:
        client = get_admin_client()
        service = PaperMarkToMarketService(client)

        # 1. Refresh marks with live quotes
        mark_result = service.refresh_marks(user_id)
        logger.info(
            f"[PAPER_MARK_TO_MARKET] Marks refreshed: "
            f"{mark_result.get('positions_marked', 0)}/{mark_result.get('total_positions', 0)}"
        )

        # 2. Save EOD snapshot
        snapshot_result = service.save_eod_snapshot(user_id)
        logger.info(
            f"[PAPER_MARK_TO_MARKET] Snapshots saved: {snapshot_result.get('snapshots_saved', 0)}"
        )

        return {
            "ok": True,
            "mark_result": mark_result,
            "snapshot_result": snapshot_result,
        }

    except Exception as e:
        logger.error(f"[PAPER_MARK_TO_MARKET] Failed for user {user_id}: {e}")
        raise RetryableJobError(f"Paper mark-to-market failed: {e}")
