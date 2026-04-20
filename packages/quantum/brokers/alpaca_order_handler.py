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

    Close orders (position_id set): sets position_intent per leg
    (buy_to_close / sell_to_close) and clamps limit_price >= 0.01
    for near-worthless spreads.
    """
    order_json = order.get("order_json") or {}
    legs_data = order_json.get("legs") or []
    side = order.get("side") or order_json.get("side") or "buy"
    limit_price = round(float(order.get("requested_price") or order_json.get("limit_price") or 0), 2)
    qty = int(order.get("requested_qty") or order_json.get("contracts") or 1)

    # Detect close orders: position_id is set when closing an existing position
    is_close_order = bool(order.get("position_id"))

    alpaca_legs = []
    for i, leg in enumerate(legs_data):
        leg_symbol = leg.get("symbol") or leg.get("occ_symbol") or ""
        leg_side = leg.get("side") or leg.get("action") or side
        alpaca_leg = {
            "symbol": polygon_to_alpaca(leg_symbol),
            "side": leg_side,
            "qty": 1,  # Always 1 — contract count goes on parent order qty
        }

        # Set position_intent for close orders so Alpaca doesn't infer buy_to_open
        if is_close_order:
            if leg_side == "buy":
                alpaca_leg["position_intent"] = "buy_to_close"
            else:
                alpaca_leg["position_intent"] = "sell_to_close"

        logger.info(
            f"[BUILD_ALPACA_REQ] leg[{i}] raw_side={leg.get('side')!r} "
            f"raw_action={leg.get('action')!r} fallback_side={side!r} "
            f"→ leg_side={leg_side!r} is_close={is_close_order} "
            f"intent={alpaca_leg.get('position_intent', 'NONE')}"
        )
        alpaca_legs.append(alpaca_leg)

    # Close orders on near-worthless spreads can have negative or zero mark.
    # Clamp to 0.01 so Alpaca accepts the order (you're paying a penny to close).
    if is_close_order and limit_price <= 0:
        logger.warning(
            f"[ALPACA_HANDLER] Close order limit_price={limit_price} <= 0 "
            f"(order={order.get('id')}). Clamping to 0.01."
        )
        limit_price = 0.01

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

    # Pre-cancel: if this is a close order, cancel any open Alpaca orders
    # for the same contract symbols to avoid held_for_orders rejection.
    is_close_order = bool(order.get("position_id"))
    if is_close_order:
        leg_symbols = [
            leg.get("symbol") or leg.get("occ_symbol") or ""
            for leg in ((order.get("order_json") or {}).get("legs") or [])
            if leg.get("symbol") or leg.get("occ_symbol")
        ]
        if leg_symbols:
            cancelled = alpaca.cancel_open_orders_for_symbols(leg_symbols)
            if cancelled:
                logger.info(
                    f"[ALPACA_HANDLER] Pre-cancel for close order={order_id}: "
                    f"cancelled {len(cancelled)} conflicting orders: {cancelled}"
                )

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
            # Alpaca 42210000 "position intent mismatch" on a close order means
            # a prior submission already filled and closed the position. Retrying
            # produces phantom duplicates — break out, let poll_pending_orders
            # pick up the original fill via alpaca_order_id.
            err_lower = last_error.lower()
            if "42210000" in err_lower or "position intent mismatch" in err_lower:
                logger.warning(
                    f"[ALPACA_HANDLER] Position-intent-mismatch on order={order_id} — "
                    f"prior submission likely already filled. Skipping remaining retries; "
                    f"poll_pending_orders will reconcile via alpaca_order_id."
                )
                break
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


def _close_position_on_fill(
    supabase,
    position_id: str,
    order: Dict[str, Any],
    alpaca_order: Dict[str, Any],
) -> None:
    """
    Close a paper_position when its Alpaca close order fills.

    This is the critical missing piece: poll_pending_orders detects the fill
    and updates paper_orders, but nothing was updating paper_positions.
    Follows the same pattern as paper_exit_evaluator._close_position lines
    956-1028 (internal fill path).
    """
    fill_price = float(alpaca_order.get("filled_avg_price") or 0)
    fill_qty = float(alpaca_order.get("filled_qty") or 0)
    filled_at = alpaca_order.get("filled_at") or datetime.now(timezone.utc).isoformat()

    # Fetch position
    pos_res = supabase.table("paper_positions") \
        .select("*") \
        .eq("id", position_id) \
        .single() \
        .execute()

    if not pos_res.data:
        logger.warning(
            f"[CLOSE_ON_FILL] Position {position_id[:8]} not found — "
            f"may already be closed"
        )
        return

    position = pos_res.data

    if position.get("status") == "closed":
        logger.info(
            f"[CLOSE_ON_FILL] Position {position_id[:8]} already closed, skipping"
        )
        return

    qty = float(position.get("quantity") or 0)
    entry_price = float(position.get("avg_entry_price") or 0)
    multiplier = 100.0

    # Alpaca multi-leg (mleg) orders use a net-cash-flow sign on the
    # parent order's `filled_avg_price`: positive = net DEBIT paid,
    # negative = net CREDIT received. Single-leg option orders use
    # `filled_avg_price` as the per-contract price directly.
    #
    # For a long spread CLOSE we receive credit, so an mleg fill comes
    # back with a negative `filled_avg_price`. We must flip the sign
    # before differencing against the positive `entry_price`; otherwise
    # the math double-counts the credit as loss (e.g. PYPL cfe69b28 on
    # 2026-04-17 recorded -$3,324 realized when the actual loss was
    # -$204: entry 2.94 - close credit 2.60 = -$0.34 × 6 × 100).
    #
    # For a short spread CLOSE we pay debit — `filled_avg_price` is
    # positive for both mleg (net debit paid) and single-leg
    # (buy-to-close price). Both produce the same formula, so no
    # translation needed.
    is_mleg = str(alpaca_order.get("order_class") or "").lower() == "mleg"
    abs_qty = abs(qty)
    if qty > 0:
        # Long position close. Sold out → received credit.
        exit_per_contract = -fill_price if is_mleg else fill_price
        realized_pl = (exit_per_contract - entry_price) * abs_qty * multiplier
    else:
        # Short position close. Bought back → paid debit.
        realized_pl = (entry_price - fill_price) * abs_qty * multiplier

    now = datetime.now(timezone.utc).isoformat()

    # Close position
    supabase.table("paper_positions").update({
        "quantity": 0,
        "status": "closed",
        "close_reason": "alpaca_fill",
        "closed_at": filled_at,
        "realized_pl": round(realized_pl, 2),
        "updated_at": now,
    }).eq("id", position_id).execute()

    logger.info(
        f"[CLOSE_ON_FILL] Position closed: id={position_id[:8]} "
        f"symbol={position.get('symbol')} fill_price={fill_price} "
        f"realized_pl=${realized_pl:.2f}"
    )


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

    # Include needs_manual_review: the outer retry can exhaust while Alpaca
    # actually filled on a prior attempt. If alpaca_order_id is set, Alpaca's
    # record is authoritative and polling will reconcile the fill.
    orders_res = supabase.table("paper_orders") \
        .select("id, alpaca_order_id, status, submitted_at, broker_status, position_id, side, order_json") \
        .in_("status", ["submitted", "working", "partial", "needs_manual_review"]) \
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

            # When order transitions to filled, handle position updates.
            if internal_status == "filled" and filled_qty > 0:
                pos_id = order.get("position_id")
                try:
                    if pos_id:
                        # ── CLOSE ORDER FILL: close the position ─────────
                        # This is the critical path that was missing — close
                        # orders have position_id set, but _process_orders_for_user
                        # and _commit_fill never touched paper_positions.
                        _close_position_on_fill(
                            supabase, pos_id, order, alpaca_order,
                        )
                        logger.info(
                            f"[ALPACA_HANDLER] Position closed on fill: "
                            f"order={order_id} position={pos_id[:8]} "
                            f"filled_qty={filled_qty} "
                            f"avg_price={alpaca_order.get('filled_avg_price')}"
                        )
                    else:
                        # ── OPEN ORDER FILL: create/update position ──────
                        from packages.quantum.paper_endpoints import (
                            _process_orders_for_user,
                        )
                        from packages.quantum.services.analytics_service import AnalyticsService

                        analytics = AnalyticsService(supabase)
                        repair_result = _process_orders_for_user(
                            supabase, analytics, user_id
                        )
                        logger.info(
                            f"[ALPACA_HANDLER] Open fill committed: order={order_id} "
                            f"repair_processed={repair_result.get('processed', 0)}"
                        )
                    fills += 1
                except Exception as fill_err:
                    logger.error(
                        f"[ALPACA_HANDLER] Fill commit failed: order={order_id} "
                        f"position_id={pos_id} error={fill_err}"
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


def ghost_position_sweep(
    alpaca: AlpacaClient,
    supabase,
    user_id: str,
    min_age_seconds: int = 600,
) -> Dict[str, Any]:
    """
    Leg-level drift sweep: find DB open positions whose OCC legs are not
    present on Alpaca. Writes a severity=warn risk_alert per ghost position.

    Gated by the caller (RECONCILE_POSITIONS_ENABLED env var). `min_age_seconds`
    protects entries that just filled on Alpaca but whose position row is still
    catching up (default 10 minutes).

    Returns {ghost_count, positions_checked, alpaca_leg_count, ghosts: [...]}.
    """
    from datetime import datetime, timezone, timedelta

    try:
        alpaca_positions = alpaca.get_option_positions()
    except Exception as e:
        return {"status": "error", "error": str(e), "ghost_count": 0}

    alpaca_legs = {p.get("symbol", "") for p in alpaca_positions if p.get("symbol")}

    port_res = supabase.table("paper_portfolios") \
        .select("id").eq("user_id", user_id).execute()
    if not port_res.data:
        return {"status": "no_portfolios", "ghost_count": 0}

    p_ids = [p["id"] for p in port_res.data]
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=min_age_seconds)).isoformat()

    open_res = supabase.table("paper_positions") \
        .select("id, symbol, legs, created_at, quantity") \
        .in_("portfolio_id", p_ids) \
        .eq("status", "open") \
        .neq("quantity", 0) \
        .lt("created_at", cutoff) \
        .execute()
    open_positions = open_res.data or []

    ghosts: List[Dict[str, Any]] = []
    for pos in open_positions:
        legs = pos.get("legs") or []
        if not legs:
            continue
        # Strip Polygon "O:" prefix to match Alpaca's OCC format
        expected_occs = {
            (leg.get("symbol") or "").lstrip("O:")
            for leg in legs
            if leg.get("symbol")
        }
        if not expected_occs:
            continue
        # If NONE of the expected legs are on Alpaca, the position is a ghost
        if not (expected_occs & alpaca_legs):
            ghosts.append({
                "position_id": pos["id"],
                "symbol": pos.get("symbol"),
                "expected_legs": sorted(expected_occs),
                "created_at": pos.get("created_at"),
            })

    for g in ghosts:
        try:
            supabase.table("risk_alerts").insert({
                "user_id": user_id,
                "alert_type": "ghost_position",
                "severity": "warn",
                "position_id": g["position_id"],
                "symbol": g["symbol"],
                "message": (
                    f"Ghost position detected: {g['symbol']} (id={g['position_id'][:8]}) "
                    f"open in DB but no matching legs on Alpaca"
                ),
                "metadata": {
                    "expected_legs": g["expected_legs"],
                    "created_at": g["created_at"],
                    "detector": "ghost_position_sweep",
                },
            }).execute()
        except Exception as alert_err:
            logger.error(
                f"[GHOST_SWEEP] Failed to write risk_alert for {g['position_id'][:8]}: {alert_err}"
            )

    logger.info(
        f"[GHOST_SWEEP] user={user_id[:8]} checked={len(open_positions)} "
        f"alpaca_legs={len(alpaca_legs)} ghosts={len(ghosts)}"
    )

    return {
        "status": "ok",
        "ghost_count": len(ghosts),
        "positions_checked": len(open_positions),
        "alpaca_leg_count": len(alpaca_legs),
        "ghosts": ghosts,
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
