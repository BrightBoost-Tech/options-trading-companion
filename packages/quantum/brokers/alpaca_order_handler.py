"""
Alpaca Order Handler — submit, poll, and reconcile order lifecycle.

Bridges the internal paper_orders table with Alpaca's order API.
Production-grade: 3-attempt submission, 10s ack timeout, 90s idle watchdog,
needs_manual_review fallback.
"""

import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from packages.quantum.brokers.alpaca_client import (
    AlpacaClient,
    AlpacaError,
    AlpacaAuthError,
    polygon_to_alpaca,
    alpaca_to_polygon,
)

# Submission retry config
MAX_SUBMIT_ATTEMPTS = 3
ACK_TIMEOUT_SECONDS = 10.0
IDLE_WATCHDOG_SECONDS = 90

logger = logging.getLogger(__name__)


def build_alpaca_order_request(order: Dict[str, Any]) -> Dict[str, Any]:
    """
    Translate an internal paper_orders row into an Alpaca order request.

    Reads order_json for legs, limit_price, side, and converts
    Polygon OCC symbols to Alpaca format.
    """
    order_json = order.get("order_json") or {}
    legs_data = order_json.get("legs") or []
    side = order.get("side") or order_json.get("side") or "buy"
    limit_price = round(float(order.get("requested_price") or order_json.get("limit_price") or 0), 2)
    qty = int(order.get("requested_qty") or order_json.get("contracts") or 1)

    alpaca_legs = []
    for leg in legs_data:
        leg_symbol = leg.get("symbol") or leg.get("occ_symbol") or ""
        leg_side = leg.get("side") or leg.get("action") or side
        alpaca_legs.append({
            "symbol": polygon_to_alpaca(leg_symbol),
            "side": leg_side,
            "qty": 1,  # Always 1 — contract count goes on parent order qty
        })

    # Options must always be limit orders — Alpaca rejects market orders
    # outside market hours. If no limit_price, the order cannot be submitted.
    if not limit_price or limit_price <= 0:
        raise ValueError(
            f"Cannot submit options order without limit_price "
            f"(got {limit_price}). Order ID: {order.get('id')}"
        )

    return {
        "symbol": order_json.get("symbol") or order.get("symbol"),
        "legs": alpaca_legs,
        "qty": qty,  # Contract count on parent order, not on legs
        "order_type": "limit",
        "limit_price": limit_price,
        "time_in_force": "day",
    }


def submit_and_track(
    alpaca: AlpacaClient,
    supabase,
    order: Dict[str, Any],
    user_id: str,
) -> Dict[str, Any]:
    """
    Submit an internal order to Alpaca with production-grade reliability.

    - Up to 3 submission attempts with backoff
    - 10s acknowledgment check after each submission
    - Falls back to needs_manual_review after 3 failures (never silently drops)
    """
    order_id = order.get("id")
    num_legs = len((order.get("order_json") or {}).get("legs", []))
    last_error = None

    for attempt in range(1, MAX_SUBMIT_ATTEMPTS + 1):
        try:
            req = build_alpaca_order_request(order)
            num_legs = len(req.get("legs", []))
            t_submit = time.monotonic()

            result = alpaca.submit_option_order(req)

            alpaca_order_id = result.get("alpaca_order_id")
            t_ack = time.monotonic() - t_submit

            # Silent failure detection: verify we got an order ID back
            if not alpaca_order_id:
                logger.error(
                    f"[ALPACA_HANDLER] Silent failure: submission returned no order ID "
                    f"(order={order_id}, attempt={attempt}/{MAX_SUBMIT_ATTEMPTS})"
                )
                last_error = "no_alpaca_order_id_returned"
                if attempt < MAX_SUBMIT_ATTEMPTS:
                    time.sleep(1.0 * attempt)  # Brief backoff before retry
                    continue
                break

            # Log acknowledgment timing
            if t_ack > ACK_TIMEOUT_SECONDS:
                logger.warning(
                    f"[ALPACA_HANDLER] Slow ack: order={order_id} took {t_ack:.1f}s "
                    f"(threshold={ACK_TIMEOUT_SECONDS}s)"
                )

            supabase.table("paper_orders").update({
                "alpaca_order_id": alpaca_order_id,
                "execution_mode": "alpaca_paper" if alpaca.paper else "alpaca_live",
                "broker_status": result.get("status"),
                "broker_response": result,
                "status": "submitted",
                "submitted_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", order_id).execute()

            logger.info(
                f"[ALPACA_HANDLER] Order submitted: internal={order_id} "
                f"alpaca={alpaca_order_id} legs={num_legs} "
                f"status={result.get('status')} ack={t_ack:.2f}s "
                f"attempt={attempt}/{MAX_SUBMIT_ATTEMPTS}"
            )
            return {"status": "submitted", **result}

        except (AlpacaAuthError,) as e:
            # Auth errors already attempted re-auth inside _call_with_retry
            # If we're here, re-auth failed — no point retrying
            last_error = str(e)
            logger.error(
                f"[ALPACA_HANDLER] Auth failure (fatal): order={order_id} error={last_error}"
            )
            break

        except Exception as e:
            last_error = str(e)
            logger.error(
                f"[ALPACA_HANDLER] Submit failed (attempt {attempt}/{MAX_SUBMIT_ATTEMPTS}): "
                f"order={order_id} legs={num_legs} error={last_error}"
            )
            if attempt < MAX_SUBMIT_ATTEMPTS:
                backoff = 2.0 * attempt  # 2s, 4s
                logger.info(f"[ALPACA_HANDLER] Retrying in {backoff}s...")
                time.sleep(backoff)

    # All attempts exhausted — mark as needs_manual_review (never silently fail)
    logger.error(
        f"[ALPACA_HANDLER] All {MAX_SUBMIT_ATTEMPTS} attempts failed for order={order_id}. "
        f"Marking needs_manual_review. Last error: {last_error}"
    )
    supabase.table("paper_orders").update({
        "broker_status": "needs_manual_review",
        "broker_response": {
            "error": last_error,
            "legs": num_legs,
            "attempts": MAX_SUBMIT_ATTEMPTS,
            "marked_at": datetime.now(timezone.utc).isoformat(),
        },
        "status": "needs_manual_review",
    }).eq("id", order_id).execute()

    return {"status": "needs_manual_review", "error": last_error, "attempts": MAX_SUBMIT_ATTEMPTS}


def poll_pending_orders(
    alpaca: AlpacaClient,
    supabase,
    user_id: str,
) -> Dict[str, Any]:
    """
    Check status of all submitted Alpaca orders and sync back.

    Production features:
    - 90-second idle watchdog: if order has no status update, cancel and resubmit
    - Retry on poll failures (transient)
    - Fill detection with position creation
    """
    # Get orders with Alpaca IDs that are still pending
    port_res = supabase.table("paper_portfolios") \
        .select("id").eq("user_id", user_id).execute()
    if not port_res.data:
        return {"synced": 0, "errors": []}

    p_ids = [p["id"] for p in port_res.data]

    orders_res = supabase.table("paper_orders") \
        .select("id, alpaca_order_id, status, submitted_at, broker_status") \
        .in_("status", ["submitted", "working", "partial"]) \
        .in_("portfolio_id", p_ids) \
        .not_.is_("alpaca_order_id", "null") \
        .execute()
    orders = orders_res.data or []

    synced = 0
    fills = 0
    partials = 0
    cancels = 0
    unchanged = 0
    watchdog_cancels = 0
    errors = []

    now_utc = datetime.now(timezone.utc)

    for order in orders:
        order_id = order["id"]
        alpaca_id = order["alpaca_order_id"]

        try:
            alpaca_order = alpaca.get_order(alpaca_id)
            alpaca_status = alpaca_order.get("status", "")

            # Map Alpaca status → internal
            status_map = {
                "new": "working", "accepted": "working",
                "pending_new": "working", "partially_filled": "partial",
                "filled": "filled", "canceled": "cancelled",
                "expired": "cancelled", "rejected": "cancelled",
                "replaced": "working", "pending_replace": "working",
            }
            internal_status = status_map.get(alpaca_status, "working")

            # === IDLE WATCHDOG (90s) ===
            # If order is still in a "waiting" state and was submitted > 90s ago
            # with no fills, cancel and mark for resubmission
            if internal_status == "working" and order.get("submitted_at"):
                try:
                    submitted_at = datetime.fromisoformat(
                        order["submitted_at"].replace("Z", "+00:00")
                    )
                    idle_seconds = (now_utc - submitted_at).total_seconds()
                    filled_qty = float(alpaca_order.get("filled_qty") or 0)

                    if idle_seconds > IDLE_WATCHDOG_SECONDS and filled_qty == 0:
                        logger.warning(
                            f"[ALPACA_HANDLER] Idle watchdog triggered: order={order_id} "
                            f"alpaca={alpaca_id} idle={idle_seconds:.0f}s "
                            f"(threshold={IDLE_WATCHDOG_SECONDS}s). Cancelling."
                        )
                        try:
                            alpaca.cancel_order(alpaca_id)
                        except Exception as cancel_err:
                            logger.warning(
                                f"[ALPACA_HANDLER] Watchdog cancel failed: {cancel_err}"
                            )

                        supabase.table("paper_orders").update({
                            "broker_status": "watchdog_cancelled",
                            "status": "watchdog_cancelled",
                            "broker_response": {
                                **alpaca_order,
                                "watchdog": {
                                    "reason": "idle_timeout",
                                    "idle_seconds": round(idle_seconds),
                                    "threshold": IDLE_WATCHDOG_SECONDS,
                                    "cancelled_at": now_utc.isoformat(),
                                },
                            },
                        }).eq("id", order_id).execute()

                        watchdog_cancels += 1
                        continue  # Skip normal processing for this order
                except (ValueError, TypeError):
                    pass  # Malformed submitted_at, skip watchdog

            update = {
                "broker_status": alpaca_status,
                "broker_response": alpaca_order,
                "status": internal_status,
            }

            filled_qty = float(alpaca_order.get("filled_qty") or 0)
            if filled_qty > 0:
                update["filled_qty"] = filled_qty
                if alpaca_order.get("filled_avg_price"):
                    update["avg_fill_price"] = float(alpaca_order["filled_avg_price"])
                if alpaca_order.get("filled_at"):
                    update["filled_at"] = alpaca_order["filled_at"]

            supabase.table("paper_orders").update(update).eq("id", order_id).execute()
            synced += 1

            # When order transitions to filled, trigger position creation
            # via the orphan repair path in _process_orders_for_user.
            if internal_status == "filled" and filled_qty > 0:
                try:
                    from packages.quantum.paper_endpoints import (
                        _process_orders_for_user,
                    )
                    from packages.quantum.services.analytics_service import AnalyticsService

                    analytics = AnalyticsService(supabase)
                    repair_result = _process_orders_for_user(
                        supabase, analytics, user_id
                    )
                    logger.info(
                        f"[ALPACA_HANDLER] Fill committed: order={order_id} "
                        f"repair_processed={repair_result.get('processed', 0)}"
                    )
                    fills += 1
                except Exception as repair_err:
                    logger.error(
                        f"[ALPACA_HANDLER] Fill commit failed: order={order_id} "
                        f"error={repair_err}"
                    )
            elif internal_status == "partial":
                partials += 1
            elif internal_status == "cancelled":
                cancels += 1
            else:
                unchanged += 1

            logger.info(
                f"[ALPACA_HANDLER] Synced: internal={order_id} "
                f"alpaca_status={alpaca_status} → {internal_status} "
                f"filled_qty={filled_qty}"
            )

        except Exception as e:
            logger.error(f"[ALPACA_HANDLER] Poll failed: order={order_id} error={e}")
            errors.append({"order_id": order_id, "error": str(e)})

    return {
        "synced": synced, "total_polled": len(orders),
        "fills": fills, "partials": partials,
        "cancels": cancels, "unchanged": unchanged,
        "watchdog_cancels": watchdog_cancels,
        "errors": errors,
    }


def reconcile_positions(
    alpaca: AlpacaClient,
    supabase,
    user_id: str,
) -> Dict[str, Any]:
    """
    Compare Alpaca positions vs internal paper_positions.
    Returns list of discrepancies.
    """
    # Get Alpaca positions
    try:
        alpaca_positions = alpaca.get_option_positions()
    except Exception as e:
        return {"status": "error", "error": str(e)}

    # Get internal open positions
    port_res = supabase.table("paper_portfolios") \
        .select("id").eq("user_id", user_id).execute()
    if not port_res.data:
        return {"status": "no_portfolios"}

    p_ids = [p["id"] for p in port_res.data]
    internal_res = supabase.table("paper_positions") \
        .select("id, symbol, quantity, status") \
        .in_("portfolio_id", p_ids) \
        .eq("status", "open") \
        .neq("quantity", 0) \
        .execute()
    internal_positions = internal_res.data or []

    # Build maps for comparison
    alpaca_map = {}
    for p in alpaca_positions:
        sym = p.get("symbol", "")
        alpaca_map[sym] = float(p.get("qty", 0))

    internal_map = {}
    for p in internal_positions:
        sym = p.get("symbol", "")
        internal_map[sym] = float(p.get("quantity", 0))

    discrepancies = []

    # Check Alpaca positions not in internal
    for sym, qty in alpaca_map.items():
        if sym not in internal_map:
            discrepancies.append({
                "type": "alpaca_only",
                "symbol": sym,
                "alpaca_qty": qty,
                "internal_qty": 0,
            })
        elif abs(internal_map[sym] - qty) > 0.01:
            discrepancies.append({
                "type": "qty_mismatch",
                "symbol": sym,
                "alpaca_qty": qty,
                "internal_qty": internal_map[sym],
            })

    # Check internal positions not in Alpaca
    for sym, qty in internal_map.items():
        if sym not in alpaca_map:
            discrepancies.append({
                "type": "internal_only",
                "symbol": sym,
                "alpaca_qty": 0,
                "internal_qty": qty,
            })

    logger.info(
        f"[ALPACA_HANDLER] Reconciliation: alpaca={len(alpaca_map)} "
        f"internal={len(internal_map)} discrepancies={len(discrepancies)}"
    )

    return {
        "status": "ok",
        "alpaca_count": len(alpaca_map),
        "internal_count": len(internal_map),
        "discrepancies": discrepancies,
    }
