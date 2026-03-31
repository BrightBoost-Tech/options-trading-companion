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

            # Find all users with pending Alpaca orders
            pending_res = client.table("paper_orders") \
                .select("user_id") \
                .in_("status", ["submitted", "working", "partial"]) \
                .not_.is_("alpaca_order_id", "null") \
                .execute()
            user_ids = list({r["user_id"] for r in (pending_res.data or [])})

            if not user_ids:
                return {"total_polled": 0, "users": 0}

            totals = {"total_polled": 0, "fills": 0, "partials": 0, "cancels": 0, "unchanged": 0, "users": len(user_ids)}
            for uid in user_ids:
                result = poll_pending_orders(alpaca, client, uid)
                for key in ("total_polled", "fills", "partials", "cancels", "unchanged"):
                    totals[key] += result.get(key, 0)

            logger.info(
                f"[ALPACA_SYNC] {totals['users']} user(s), "
                f"polled={totals['total_polled']} "
                f"fills={totals['fills']} "
                f"partials={totals['partials']} "
                f"cancels={totals['cancels']} "
                f"unchanged={totals['unchanged']}"
            )

            return totals

        sync_result = run_async(sync_orders())

        return {
            "ok": True,
            "timing_ms": (time.time() - start_time) * 1000,
            **sync_result,
        }

    except Exception as e:
        raise RetryableJobError(f"Alpaca order sync failed: {e}")
