"""
Alpaca Order Sync Job Handler

Runs every 5 minutes during market hours (9:30 AM - 4:00 PM Chicago, Mon-Fri).

Polls Alpaca for status updates on submitted orders and syncs fills,
cancellations, and rejections back to paper_orders.

Uses the existing poll_pending_orders() from alpaca_order_handler.py.
"""

import time
import logging
from datetime import datetime, timezone
from typing import Any, Dict

from packages.quantum.jobs.handlers.utils import get_admin_client, get_active_user_ids, run_async
from packages.quantum.jobs.handlers.exceptions import RetryableJobError, PermanentJobError

logger = logging.getLogger(__name__)

JOB_NAME = "alpaca_order_sync"


def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """
    Sync Alpaca order statuses for all submitted orders.

    1. Query paper_orders with alpaca_order_id and status in (submitted, working, partial)
    2. Poll Alpaca for each order's current status
    3. Update paper_orders with fills, cancellations, rejections
    4. When fills are confirmed, trigger position updates
    """
    start_time = time.time()

    try:
        client = get_admin_client()

        from packages.quantum.brokers.alpaca_client import get_alpaca_client
        alpaca = get_alpaca_client()

        if not alpaca:
            return {
                "ok": True,
                "status": "no_alpaca_client",
                "reason": "ALPACA_API_KEY not configured",
            }

        async def sync_orders():
            from packages.quantum.brokers.alpaca_order_handler import poll_pending_orders

            result = poll_pending_orders(alpaca, client)

            logger.info(
                f"[ALPACA_SYNC] Polled {result.get('total_polled', 0)} orders: "
                f"fills={result.get('fills', 0)} "
                f"partials={result.get('partials', 0)} "
                f"cancels={result.get('cancels', 0)} "
                f"unchanged={result.get('unchanged', 0)}"
            )

            return result

        sync_result = run_async(sync_orders())

        return {
            "ok": True,
            "timing_ms": (time.time() - start_time) * 1000,
            **sync_result,
        }

    except Exception as e:
        raise RetryableJobError(f"Alpaca order sync failed: {e}")
