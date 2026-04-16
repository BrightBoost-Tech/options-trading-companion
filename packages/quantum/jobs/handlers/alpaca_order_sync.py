"""
Alpaca Order Sync Job Handler

Runs every 5 minutes during market hours (9:30 AM - 4:00 PM Chicago, Mon-Fri).

Polls Alpaca for status updates on submitted orders and syncs fills,
cancellations, and rejections back to paper_orders.

Uses the existing poll_pending_orders() from alpaca_order_handler.py.
"""

import os
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

            totals = {
                "total_polled": 0, "fills": 0, "partials": 0,
                "cancels": 0, "unchanged": 0, "users": 0,
                "orphans_repaired": 0,
            }

            # ── Step 1: Poll Alpaca for pending orders ──────────────────
            pending_res = client.table("paper_orders") \
                .select("user_id") \
                .in_("status", ["submitted", "working", "partial"]) \
                .not_.is_("alpaca_order_id", "null") \
                .execute()
            poll_user_ids = list({r["user_id"] for r in (pending_res.data or [])})

            if poll_user_ids:
                totals["users"] = len(poll_user_ids)
                for uid in poll_user_ids:
                    result = poll_pending_orders(alpaca, client, uid)
                    for key in ("total_polled", "fills", "partials", "cancels", "unchanged"):
                        totals[key] += result.get(key, 0)

            # ── Step 2: Repair orphaned fills (ALWAYS runs) ─────────────
            # Finds orders with status=filled, position_id=NULL, filled_qty > 0
            # These are fills that were synced but never had positions created,
            # e.g. from before the fix, race conditions, or missed cycles.
            orphan_res = client.table("paper_orders") \
                .select("user_id") \
                .eq("status", "filled") \
                .is_("position_id", "null") \
                .gt("filled_qty", 0) \
                .execute()
            orphan_user_ids = list({r["user_id"] for r in (orphan_res.data or [])})

            if orphan_user_ids:
                from packages.quantum.paper_endpoints import _process_orders_for_user
                from packages.quantum.services.analytics_service import AnalyticsService
                analytics = AnalyticsService(client)

                for uid in orphan_user_ids:
                    try:
                        repair = _process_orders_for_user(client, analytics, uid)
                        repaired = repair.get("processed", 0)
                        totals["orphans_repaired"] += repaired
                        if repaired > 0:
                            logger.info(
                                f"[ALPACA_SYNC] Repaired {repaired} orphaned fill(s) for {uid[:8]}"
                            )
                    except Exception as e:
                        logger.error(f"[ALPACA_SYNC] Orphan repair failed for {uid[:8]}: {e}")

            # ── Step 3: Reconcile stuck-open positions ──────────────────
            # Catch positions that are 'open' but have a filled CLOSE order.
            # This is a safety net for the primary close path in poll_pending_orders.
            #
            # CRITICAL: Only process CLOSE orders, not entry orders.
            # Entry orders also have position_id (backfilled by _process_orders_for_user),
            # so we must check order_json.source_engine to distinguish.
            # Close orders: source_engine in (paper_exit_evaluator, manual_close, paper_autopilot)
            #   where paper_autopilot is used for autopilot close path
            # Entry orders: source_engine in (midday_entry, morning_limit, etc.)
            CLOSE_SOURCE_ENGINES = {"paper_exit_evaluator", "manual_close"}
            stuck_open_closed = 0
            try:
                from packages.quantum.brokers.alpaca_order_handler import _close_position_on_fill

                # Find filled orders with position_id set
                stuck_res = client.table("paper_orders") \
                    .select("id, position_id, side, alpaca_order_id, filled_qty, avg_fill_price, filled_at, broker_response, order_json") \
                    .eq("status", "filled") \
                    .not_.is_("position_id", "null") \
                    .gt("filled_qty", 0) \
                    .execute()

                for filled_order in (stuck_res.data or []):
                    pid = filled_order.get("position_id")
                    if not pid:
                        continue

                    # ── Filter: only close orders ──────────────────────
                    order_json = filled_order.get("order_json") or {}
                    source_engine = order_json.get("source_engine") or ""
                    if source_engine not in CLOSE_SOURCE_ENGINES:
                        continue  # Entry order — do NOT close the position

                    # Check if position is still open
                    pos_check = client.table("paper_positions") \
                        .select("id, status") \
                        .eq("id", pid) \
                        .eq("status", "open") \
                        .execute()
                    if not pos_check.data:
                        continue  # Already closed

                    # Build a minimal alpaca_order dict from stored data
                    alpaca_data = filled_order.get("broker_response") or {}
                    alpaca_data.setdefault("filled_avg_price", filled_order.get("avg_fill_price"))
                    alpaca_data.setdefault("filled_qty", filled_order.get("filled_qty"))
                    alpaca_data.setdefault("filled_at", filled_order.get("filled_at"))

                    try:
                        _close_position_on_fill(
                            client, pid, filled_order, alpaca_data,
                        )
                        stuck_open_closed += 1
                        logger.warning(
                            f"[ALPACA_SYNC] Reconciled stuck-open position {pid[:8]} "
                            f"via filled close order {filled_order['id'][:8]} "
                            f"(source_engine={source_engine})"
                        )
                    except Exception as recon_err:
                        logger.error(
                            f"[ALPACA_SYNC] Reconcile failed for position {pid[:8]}: {recon_err}"
                        )
            except Exception as recon_outer_err:
                logger.error(f"[ALPACA_SYNC] Reconciliation step failed: {recon_outer_err}")

            totals["stuck_open_closed"] = stuck_open_closed

            # ── Step 4: Ghost-position sweep (gated) ────────────────────
            # Leg-level comparison of DB open positions vs Alpaca positions.
            # Catches desync cases where DB says open but Alpaca has no
            # matching OCC legs. Writes severity=warn risk_alerts.
            # Gated by RECONCILE_POSITIONS_ENABLED (default 0) for 48h
            # observation before flipping on.
            ghost_total = 0
            if os.environ.get("RECONCILE_POSITIONS_ENABLED", "0") == "1":
                try:
                    from packages.quantum.brokers.alpaca_order_handler import ghost_position_sweep

                    # Only sweep users who actually have open DB positions
                    open_pos_res = client.table("paper_positions") \
                        .select("user_id") \
                        .eq("status", "open") \
                        .execute()
                    sweep_user_ids = list({r["user_id"] for r in (open_pos_res.data or [])})
                    for uid in sweep_user_ids:
                        try:
                            sweep = ghost_position_sweep(alpaca, client, uid)
                            ghost_total += sweep.get("ghost_count", 0)
                        except Exception as sweep_err:
                            logger.error(f"[ALPACA_SYNC] Ghost sweep failed for {uid[:8]}: {sweep_err}")
                except Exception as sweep_outer_err:
                    logger.error(f"[ALPACA_SYNC] Ghost sweep step failed: {sweep_outer_err}")
            totals["ghost_positions"] = ghost_total

            logger.info(
                f"[ALPACA_SYNC] polled={totals['total_polled']} "
                f"fills={totals['fills']} orphans_repaired={totals['orphans_repaired']} "
                f"stuck_open_closed={stuck_open_closed} "
                f"ghost_positions={ghost_total} "
                f"partials={totals['partials']} cancels={totals['cancels']}"
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
