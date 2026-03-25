"""
Pre-submission safety checks and manual approval queue for live trading.

ALL checks must pass before any live order is submitted to Alpaca.
Paper orders (internal_paper, alpaca_paper) bypass safety checks.
"""

import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

CHICAGO_TZ = ZoneInfo("America/Chicago")

# Config
LIVE_MAX_CAPITAL_PCT = float(os.environ.get("LIVE_MAX_CAPITAL_PCT", "5")) / 100
LIVE_MAX_ORDER_NOTIONAL = float(os.environ.get("LIVE_MAX_ORDER_NOTIONAL", "2500"))
LIVE_DAILY_LOSS_LIMIT = float(os.environ.get("LIVE_DAILY_LOSS_LIMIT", "500"))
APPROVAL_TTL_MINUTES = int(os.environ.get("APPROVAL_TTL_MINUTES", "15"))
MANUAL_APPROVAL = os.environ.get("LIVE_MANUAL_APPROVAL", "true").lower() in ("true", "1")


def run_pre_submit_checks(
    alpaca_client,
    supabase,
    order: Dict[str, Any],
    user_id: str,
) -> Dict[str, Any]:
    """
    Run all safety checks before submitting a live order.

    Returns:
        {approved: bool, checks: [...], blocked_reason: str|None}
    """
    checks = []
    blocked_reason = None

    order_json = order.get("order_json") or {}
    limit_price = float(order.get("requested_price") or order_json.get("limit_price") or 0)
    qty = int(order.get("requested_qty") or order_json.get("contracts") or 1)
    notional = limit_price * qty * 100  # Options multiplier

    # 1. Account buying power
    try:
        bp = alpaca_client.get_buying_power()
        passed = notional <= bp
        checks.append({"name": "buying_power", "passed": passed,
                       "detail": f"notional={notional:.0f} bp={bp:.0f}"})
        if not passed:
            blocked_reason = f"Insufficient buying power: need ${notional:.0f}, have ${bp:.0f}"
    except Exception as e:
        checks.append({"name": "buying_power", "passed": False, "detail": str(e)})
        blocked_reason = f"Could not verify buying power: {e}"

    # 2. PDT guard
    try:
        day_trades = alpaca_client.get_day_trade_count()
        pdt_limit = int(os.environ.get("PDT_MAX_DAY_TRADES", "3"))
        passed = day_trades < pdt_limit
        checks.append({"name": "pdt_guard", "passed": passed,
                       "detail": f"day_trades={day_trades}/{pdt_limit}"})
        if not passed and not blocked_reason:
            blocked_reason = f"PDT limit: {day_trades}/{pdt_limit} day trades used"
    except Exception as e:
        checks.append({"name": "pdt_guard", "passed": False, "detail": str(e)})

    # 3. PDT restriction flag
    try:
        restricted = alpaca_client.is_pdt_restricted()
        checks.append({"name": "pdt_restricted", "passed": not restricted,
                       "detail": f"restricted={restricted}"})
        if restricted and not blocked_reason:
            blocked_reason = "Account is PDT restricted"
    except Exception as e:
        checks.append({"name": "pdt_restricted", "passed": False, "detail": str(e)})

    # 4. Capital allocation cap
    try:
        acct = alpaca_client.get_account()
        equity = float(acct.get("equity", 0))
        max_allocation = equity * LIVE_MAX_CAPITAL_PCT
        passed = notional <= max_allocation
        checks.append({"name": "capital_cap", "passed": passed,
                       "detail": f"notional={notional:.0f} max={max_allocation:.0f} ({LIVE_MAX_CAPITAL_PCT:.0%})"})
        if not passed and not blocked_reason:
            blocked_reason = f"Exceeds {LIVE_MAX_CAPITAL_PCT:.0%} capital cap: ${notional:.0f} > ${max_allocation:.0f}"
    except Exception as e:
        checks.append({"name": "capital_cap", "passed": False, "detail": str(e)})

    # 5. Max order notional
    passed = notional <= LIVE_MAX_ORDER_NOTIONAL
    checks.append({"name": "max_notional", "passed": passed,
                   "detail": f"notional={notional:.0f} limit={LIVE_MAX_ORDER_NOTIONAL:.0f}"})
    if not passed and not blocked_reason:
        blocked_reason = f"Order notional ${notional:.0f} exceeds limit ${LIVE_MAX_ORDER_NOTIONAL:.0f}"

    # 6. Market hours check
    now_chicago = datetime.now(CHICAGO_TZ)
    market_open = now_chicago.hour >= 8 and now_chicago.hour < 16
    weekday = now_chicago.weekday() < 5
    passed = market_open and weekday
    checks.append({"name": "market_hours", "passed": passed,
                   "detail": f"chicago_time={now_chicago.strftime('%H:%M')} weekday={weekday}"})
    if not passed and not blocked_reason:
        blocked_reason = "Market is closed"

    # 7. Daily loss limit
    try:
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        closed_res = supabase.table("paper_positions") \
            .select("realized_pl") \
            .eq("user_id", user_id) \
            .eq("status", "closed") \
            .gte("closed_at", f"{today_str}T00:00:00") \
            .execute()
        daily_pl = sum(float(p.get("realized_pl") or 0) for p in (closed_res.data or []))
        passed = daily_pl > -LIVE_DAILY_LOSS_LIMIT
        checks.append({"name": "daily_loss_limit", "passed": passed,
                       "detail": f"daily_pl={daily_pl:.0f} limit=-{LIVE_DAILY_LOSS_LIMIT:.0f}"})
        if not passed and not blocked_reason:
            blocked_reason = f"Daily loss limit breached: ${daily_pl:.0f}"
    except Exception as e:
        checks.append({"name": "daily_loss_limit", "passed": False, "detail": str(e)})

    all_passed = all(c["passed"] for c in checks)

    return {
        "approved": all_passed,
        "checks": checks,
        "blocked_reason": blocked_reason if not all_passed else None,
    }


def run_post_fill_checks(
    alpaca_client,
    supabase,
    fill: Dict[str, Any],
    order: Dict[str, Any],
    user_id: str,
) -> Dict[str, Any]:
    """
    After a fill, verify the fill is reasonable and log for calibration.
    """
    checks = []

    fill_price = float(fill.get("filled_avg_price") or fill.get("avg_fill_price") or 0)
    limit_price = float(order.get("requested_price") or 0)

    # 1. Fill price within expected range
    if limit_price > 0 and fill_price > 0:
        slippage_pct = abs(fill_price - limit_price) / limit_price
        passed = slippage_pct < 0.10  # 10% tolerance
        checks.append({"name": "fill_price_range", "passed": passed,
                       "detail": f"fill={fill_price:.4f} limit={limit_price:.4f} slippage={slippage_pct:.2%}"})

    # 2. Log for TCM calibration
    tcm_estimate = order.get("tcm") or {}
    tcm_price = float(tcm_estimate.get("expected_fill_price") or 0)
    if tcm_price > 0 and fill_price > 0:
        tcm_error = fill_price - tcm_price
        checks.append({"name": "tcm_calibration", "passed": True,
                       "detail": f"tcm_predicted={tcm_price:.4f} actual={fill_price:.4f} error={tcm_error:+.4f}"})

    logger.info(
        f"[SAFETY] Post-fill checks: order={order.get('id')} "
        f"fill_price={fill_price} checks={checks}"
    )

    return {"checks": checks}


# ---------------------------------------------------------------------------
# Manual Approval Queue
# ---------------------------------------------------------------------------

def stage_for_approval(
    supabase,
    order: Dict[str, Any],
    safety_result: Dict[str, Any],
    user_id: str,
) -> Dict[str, Any]:
    """
    Stage order for human approval instead of immediate submission.
    Sets TTL — auto-cancels if not approved within APPROVAL_TTL_MINUTES.
    """
    expires_at = (
        datetime.now(timezone.utc) + timedelta(minutes=APPROVAL_TTL_MINUTES)
    ).isoformat()

    row = {
        "user_id": user_id,
        "order_id": order.get("id"),
        "suggestion_id": order.get("suggestion_id"),
        "order_details": order.get("order_json") or {},
        "safety_checks": safety_result,
        "status": "pending",
        "expires_at": expires_at,
    }

    result = supabase.table("live_approval_queue").insert(row).execute()
    approval_id = result.data[0]["id"] if result.data else None

    logger.info(
        f"[SAFETY] Order staged for approval: order={order.get('id')} "
        f"approval={approval_id} expires={expires_at}"
    )

    return {"approval_id": approval_id, "expires_at": expires_at, "status": "pending"}


def approve_order(
    supabase,
    alpaca_client,
    approval_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """
    Human approves an order. Re-run safety checks, then submit.
    """
    # Fetch approval
    res = supabase.table("live_approval_queue") \
        .select("*") \
        .eq("id", approval_id) \
        .eq("user_id", user_id) \
        .eq("status", "pending") \
        .single() \
        .execute()

    if not res.data:
        return {"status": "not_found"}

    approval = res.data

    # Check TTL
    expires_at = datetime.fromisoformat(approval["expires_at"].replace("Z", "+00:00"))
    if datetime.now(timezone.utc) > expires_at:
        supabase.table("live_approval_queue").update(
            {"status": "expired"}
        ).eq("id", approval_id).execute()
        return {"status": "expired"}

    # Fetch the order
    order_res = supabase.table("paper_orders") \
        .select("*") \
        .eq("id", approval["order_id"]) \
        .single() \
        .execute()
    if not order_res.data:
        return {"status": "order_not_found"}

    order = order_res.data

    # Re-run safety checks at approval time
    safety = run_pre_submit_checks(alpaca_client, supabase, order, user_id)
    if not safety["approved"]:
        supabase.table("live_approval_queue").update({
            "status": "rejected",
            "rejection_reason": f"Safety re-check failed: {safety['blocked_reason']}",
            "rejected_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", approval_id).execute()
        return {"status": "safety_blocked", "reason": safety["blocked_reason"]}

    # Submit to Alpaca
    from packages.quantum.brokers.alpaca_order_handler import submit_and_track
    result = submit_and_track(alpaca_client, supabase, order, user_id)

    # Mark approved
    supabase.table("live_approval_queue").update({
        "status": "approved",
        "approved_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", approval_id).execute()

    return {"status": "approved", "submission": result}


def reject_order(supabase, approval_id: str, user_id: str, reason: str) -> Dict[str, Any]:
    """Human rejects an order."""
    supabase.table("live_approval_queue").update({
        "status": "rejected",
        "rejection_reason": reason,
        "rejected_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", approval_id).eq("user_id", user_id).execute()

    logger.info(f"[SAFETY] Order rejected: approval={approval_id} reason={reason}")
    return {"status": "rejected", "reason": reason}


def expire_stale_approvals(supabase) -> Dict[str, Any]:
    """Cancel approvals past their TTL. Called by periodic sweep."""
    now_iso = datetime.now(timezone.utc).isoformat()
    res = supabase.table("live_approval_queue") \
        .update({"status": "expired"}) \
        .eq("status", "pending") \
        .lt("expires_at", now_iso) \
        .execute()
    count = len(res.data or [])
    if count > 0:
        logger.info(f"[SAFETY] Expired {count} stale approval(s)")
    return {"expired": count}
