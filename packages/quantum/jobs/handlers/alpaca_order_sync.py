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


def _client_order_id_reconcile_enabled() -> bool:
    """PR2 resolve action — default-ON safety flag (§3): unset/empty → ON;
    only an explicit falsy value disables it."""
    raw = (os.environ.get("CLIENT_ORDER_ID_RECONCILE_ENABLED") or "").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _resolve_lost_submit(alpaca, client, row: Dict[str, Any]) -> str:
    """Resolve ONE response-lost order (client_order_id set, alpaca_order_id
    NULL) by broker lookup. Returns 'backfilled' | 'rearmed' | 'noop'.

    FOUND → the prior submit reached the broker: backfill the alpaca_order_id
    (Step 1/3 then manage it normally). NOT FOUND (404) → the broker never
    received it → re-arm to the terminal 'cancelled' state
    (paper_exit_evaluator._TERMINAL_FAILED_STATUS): for a CLOSE, #1046's
    close-re-arm treats a STALE 'cancelled' attempt as re-armable so a fresh
    close is staged on the still-open position; for an ENTRY, 'cancelled' makes
    the suggestion re-executable (the dedup set excludes cancelled). This is the
    auto-resolution of the P0-A needs_manual_review hold
    (paper_exit_evaluator.py:2196) that previously required the operator.
    """
    coid = row.get("client_order_id")
    oid = row.get("id")
    if not coid or not oid:
        return "noop"
    try:
        found = alpaca.get_order_by_client_id(coid)
    except Exception as e:
        logger.error(f"[ALPACA_SYNC] Step 1.5 lookup failed client_order_id={coid}: {e}")
        return "noop"
    if found and found.get("alpaca_order_id"):
        client.table("paper_orders").update({
            "alpaca_order_id": found.get("alpaca_order_id"),
            "broker_status": found.get("status"),
            "broker_response": found,
            "status": "submitted",
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", oid).execute()
        logger.warning(
            f"[ALPACA_SYNC] Step 1.5 backfilled alpaca_order_id for "
            f"order={str(oid)[:8]} via client_order_id={coid} "
            f"(response-lost submit recovered)"
        )
        return "backfilled"
    # 404 → broker never received it → re-arm to terminal 'cancelled' (#1046).
    client.table("paper_orders").update({
        "status": "cancelled",
        "broker_status": "client_order_id_not_at_broker",
        "cancelled_at": datetime.now(timezone.utc).isoformat(),
        "cancelled_reason": (
            "PR2 step1.5: broker has no order for the deterministic "
            "client_order_id — the submit never landed; re-armed"
        ),
    }).eq("id", oid).execute()
    logger.warning(
        f"[ALPACA_SYNC] Step 1.5 re-armed order={str(oid)[:8]} to 'cancelled' "
        f"(client_order_id={coid} not found at broker — never received)"
    )
    return "rearmed"


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
                "errors": 0,
                "error_details": [],
            }

            # ── Step 1: Poll Alpaca for pending orders ──────────────────
            # Include needs_manual_review so users whose only in-flight
            # orders are stuck in that terminal-looking state still get
            # polled. Corrective counterpart to PR #764 Fix A, which
            # expanded the inner poll_pending_orders query but left this
            # outer caller narrower. See PYPL cfe69b28 (2026-04-17) for
            # the motivating ghost-fill incident.
            # #62a-D4-PR2a: belt-and-suspenders — exclude shadow_only
            # portfolios from the sync poll. shadow_only orders shouldn't
            # have alpaca_order_id post-PR2a (gate blocks submission), but
            # any pre-PR2a phantoms or race-condition orders must not have
            # their Alpaca state synced back into paper_orders.
            #
            # Paper-shadow isolation (additive, no-op when off): ALSO exclude
            # 'paper_shadow' portfolios (the paper-shadow executor's, Phase 1b)
            # so the live sync never polls/reconciles the executor's paper
            # orders — the executor self-reconciles its own. Extends this same
            # shadow_only exclusion (see services/paper_shadow_isolation.py
            # PAPER_SHADOW_ROUTING_MODE). When no paper_shadow portfolios exist
            # (always, pre-Phase-1b), the IN-list collects the same ids as
            # before → identical behavior. `shadow_portfolio_ids` is reused by
            # Step 2 (orphan repair) and Step 3 (stuck-open reconcile) below to
            # exclude paper_shadow from those loops too (the Phase-1b safety
            # completion — those loops match by status/source_engine, not
            # routing_mode, so they need the explicit portfolio exclusion).
            shadow_portfolios_res = client.table("paper_portfolios") \
                .select("id") \
                .in_("routing_mode", ["shadow_only", "paper_shadow"]) \
                .execute()
            shadow_portfolio_ids = [
                p["id"] for p in (shadow_portfolios_res.data or [])
            ]

            pending_query = client.table("paper_orders") \
                .select("user_id") \
                .in_("status", ["submitted", "working", "partial", "needs_manual_review"]) \
                .not_.is_("alpaca_order_id", "null")
            if shadow_portfolio_ids:
                pending_query = pending_query.not_.in_("portfolio_id", shadow_portfolio_ids)
            pending_res = pending_query.execute()
            poll_user_ids = list({r["user_id"] for r in (pending_res.data or [])})

            if poll_user_ids:
                totals["users"] = len(poll_user_ids)
                for uid in poll_user_ids:
                    result = poll_pending_orders(alpaca, client, uid)
                    for key in (
                        "total_polled",
                        "fills",
                        "partials",
                        "cancels",
                        "unchanged",
                    ):
                        totals[key] += result.get(key, 0)
                    poll_errors = result.get("errors") or []
                    totals["errors"] += len(poll_errors)
                    totals["error_details"].extend(
                        {
                            "user_id": uid,
                            "order_id": item.get("order_id"),
                            "error": str(item.get("error") or "")[:500],
                        }
                        for item in poll_errors[:20]
                        if isinstance(item, dict)
                    )

            # ── Step 1.5: Targeted resolve of response-lost submits (PR2) ─
            # A submit that raised BEFORE returning an alpaca_order_id (network
            # drop AFTER the broker accepted it) leaves a row with a
            # client_order_id but NO alpaca_order_id — invisible to Step 1
            # (which requires alpaca_order_id NOT NULL) and to the watchdog.
            # Look each up by its deterministic client_order_id: FOUND →
            # backfill; 404 → the broker never got it → re-arm. Flag
            # CLIENT_ORDER_ID_RECONCILE_ENABLED (default-ON). Legacy rows
            # (client_order_id NULL) are excluded by the query, so this is inert
            # until PR2 ids exist.
            if _client_order_id_reconcile_enabled():
                try:
                    lost_q = client.table("paper_orders") \
                        .select("id, client_order_id, status, position_id") \
                        .in_("status", ["needs_manual_review", "submitted", "working"]) \
                        .is_("alpaca_order_id", "null") \
                        .not_.is_("client_order_id", "null")
                    if shadow_portfolio_ids:
                        lost_q = lost_q.not_.in_("portfolio_id", shadow_portfolio_ids)
                    lost_rows = lost_q.execute().data or []
                    for _row in lost_rows:
                        _res = _resolve_lost_submit(alpaca, client, _row)
                        if _res == "backfilled":
                            totals["client_id_backfilled"] = totals.get("client_id_backfilled", 0) + 1
                        elif _res == "rearmed":
                            totals["client_id_rearmed"] = totals.get("client_id_rearmed", 0) + 1
                except Exception as _step15_err:
                    logger.error(
                        f"[ALPACA_SYNC] Step 1.5 client_order_id resolve failed: {_step15_err}"
                    )

            # ── Step 2: Repair orphaned fills (ALWAYS runs) ─────────────
            # Finds orders with status=filled, position_id=NULL, filled_qty > 0
            # These are fills that were synced but never had positions created,
            # e.g. from before the fix, race conditions, or missed cycles.
            orphan_query = client.table("paper_orders") \
                .select("user_id") \
                .eq("status", "filled") \
                .is_("position_id", "null") \
                .gt("filled_qty", 0)
            # Paper-shadow isolation (1b safety completion, additive, no-op when
            # off): exclude paper_shadow (and shadow_only) orders from orphan
            # repair so the live sync never creates positions from the executor's
            # fills — the executor self-reconciles its own. Defense-in-depth with
            # the _process_orders_for_user portfolio exclusion (which is the
            # user-scoping-proof guard, since that fn re-resolves the user's
            # portfolios). Guarded so an empty set leaves the query unchanged.
            if shadow_portfolio_ids:
                orphan_query = orphan_query.not_.in_("portfolio_id", shadow_portfolio_ids)
            orphan_res = orphan_query.execute()
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

                # Set-based reconcile (audit Area 5, 2026-06-09): the prior
                # shape fetched EVERY historical filled order with a
                # position_id (no date bound / no limit — 145 rows and
                # growing +1 per close forever) and then issued one
                # paper_positions "is it still open" query PER close-engine
                # row (55/run) — ~59 serial round-trips every 5 minutes,
                # ~52k queries/14d, all to confirm long-closed positions
                # were still closed; the job's entire ~6.5s runtime floor.
                # Scoping the stuck query to the OPEN position set inverts
                # the complexity to O(open positions): membership in
                # open_position_ids IS the "still open" check (identical
                # read-then-act semantics — both versions read position
                # state once within the same run).
                open_pos_res = client.table("paper_positions") \
                    .select("id") \
                    .eq("status", "open") \
                    .execute()
                open_position_ids = [
                    r["id"] for r in (open_pos_res.data or []) if r.get("id")
                ]

                if open_position_ids:
                    stuck_query = client.table("paper_orders") \
                        .select("id, position_id, side, alpaca_order_id, filled_qty, avg_fill_price, filled_at, broker_response, order_json") \
                        .eq("status", "filled") \
                        .in_("position_id", open_position_ids) \
                        .gt("filled_qty", 0)
                    # Paper-shadow isolation (1b safety completion, additive,
                    # no-op when off): exclude paper_shadow (and shadow_only)
                    # from stuck-open reconcile so the live sync never CLOSES
                    # the executor's positions. Guarded → unchanged query
                    # when empty.
                    if shadow_portfolio_ids:
                        stuck_query = stuck_query.not_.in_("portfolio_id", shadow_portfolio_ids)
                    stuck_res = stuck_query.execute()

                    for filled_order in (stuck_res.data or []):
                        pid = filled_order.get("position_id")
                        if not pid:
                            continue

                        # ── Filter: only close orders ──────────────────────
                        order_json = filled_order.get("order_json") or {}
                        source_engine = order_json.get("source_engine") or ""
                        if source_engine not in CLOSE_SOURCE_ENGINES:
                            continue  # Entry order — do NOT close the position

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

        poll_errors = int(sync_result.get("errors") or 0)
        return {
            "ok": poll_errors == 0,
            "timing_ms": (time.time() - start_time) * 1000,
            "counts": {"errors": poll_errors},
            **sync_result,
        }

    except Exception as e:
        raise RetryableJobError(f"Alpaca order sync failed: {e}")
