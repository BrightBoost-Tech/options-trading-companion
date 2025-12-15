from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone, timedelta
import logging
import uuid
import os

from packages.quantum.security import get_current_user
from packages.quantum.models import TradeTicket
from packages.quantum.strategy_registry import STRATEGY_REGISTRY, infer_strategy_key_from_suggestion
from packages.quantum.market_data import PolygonService
from packages.quantum.strategy_profiles import CostModelConfig

# Execution V3
from packages.quantum.execution.transaction_cost_model import TransactionCostModel
from packages.quantum.execution.pnl_attribution import PnlAttribution
from packages.quantum.services.paper_execution_service import PaperExecutionService

# v3 Observability
from packages.quantum.observability.telemetry import TradeContext, emit_trade_event, TradeEventName
from packages.quantum.services.analytics_service import AnalyticsService

router = APIRouter()

def get_supabase():
    # Lazy import to avoid circular imports; use the canonical backend module path.
    from packages.quantum.api import supabase_admin
    return supabase_admin

def get_analytics_service():
    # Lazy import to avoid circular imports; use the canonical backend module path.
    from packages.quantum.api import analytics_service
    return analytics_service

class StageOrderRequest(BaseModel):
    ticket: TradeTicket
    portfolio_id: Optional[str] = None  # if null, use/create default

class PaperCloseRequest(BaseModel):
    position_id: str

@router.post("/paper/order/stage")
def stage_order_endpoint(
    req: StageOrderRequest,
    user_id: str = Depends(get_current_user),
):
    supabase = get_supabase()
    analytics = get_analytics_service()
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    order_id = _stage_order_internal(supabase, analytics, user_id, req.ticket, req.portfolio_id)
    return {"status": "staged", "order_id": order_id}

@router.post("/paper/order/process")
def process_orders_endpoint(
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user), # Optional: restrict to admin or allow user to trigger their own
):
    # This processes orders for ALL users if run by system, but here let's process for the calling user
    # Or, if this is meant to be a cron hook, it might need a secret key.
    # The requirement says "internal task", so maybe we allow it for the user context.

    supabase = get_supabase()
    analytics = get_analytics_service()

    # Process synchronously for immediate feedback in this MVP phase, or queue
    # For better UX, we'll do sync for now, but return count

    processed_count = _process_orders_for_user(supabase, analytics, user_id)
    return {"status": "processed", "count": processed_count}


@router.post("/paper/execute")
def execute_paper_trade(
    req: StageOrderRequest,
    user_id: str = Depends(get_current_user),
):
    """
    Legacy wrapper / Immediate Mode:
    Stages the order then immediately processes it.
    """
    supabase = get_supabase()
    analytics = get_analytics_service()

    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    # 1. Stage
    order_id = _stage_order_internal(supabase, analytics, user_id, req.ticket, req.portfolio_id)

    # 2. Process Immediately (scoped to this order for efficiency?)
    # We'll just run the user process loop, it should pick up this order.
    _process_orders_for_user(supabase, analytics, user_id, target_order_id=order_id)

    # 3. Fetch result
    order_res = supabase.table("paper_orders").select("*").eq("id", order_id).single().execute()
    order = order_res.data

    if not order:
        raise HTTPException(status_code=500, detail="Order lost after processing")

    # Return similar shape to v1 for compatibility
    # Need to fetch portfolio and position
    portfolio_res = supabase.table("paper_portfolios").select("*").eq("id", order["portfolio_id"]).single().execute()
    portfolio = portfolio_res.data

    # Find position if it exists
    # We don't easily know the position ID unless we link it.
    # But we can query by strategy key from ticket
    strategy_key = _derive_strategy_key(req.ticket)
    position_res = supabase.table("paper_positions").select("*").eq("portfolio_id", order["portfolio_id"]).eq("strategy_key", strategy_key).execute()
    position = position_res.data[0] if position_res.data else None

    return {
        "status": order["status"],
        "portfolio": portfolio,
        "order": order,
        "position": position
    }

@router.post("/paper/close")
def close_paper_position(
    req: PaperCloseRequest,
    user_id: str = Depends(get_current_user),
):
    """
    V3 Close: Stages a closing order linked to the position, then processes it.
    """
    supabase = get_supabase()
    analytics = get_analytics_service()

    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    # 1. Lookup position
    pos_res = supabase.table("paper_positions").select("*").eq("id", req.position_id).single().execute()
    if not pos_res.data:
        raise HTTPException(status_code=404, detail="Position not found")
    position = pos_res.data

    # Verify ownership
    port_res = supabase.table("paper_portfolios").select("user_id").eq("id", position["portfolio_id"]).single().execute()
    if not port_res.data or port_res.data["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Unauthorized")

    # 2. Create Closing Ticket
    # Invert direction. If we hold +1 quantity, we sell 1.
    qty = float(position["quantity"])
    side = "sell" if qty > 0 else "buy" # Simplification for now (assuming long holds positive qty)

    # Construct Ticket
    ticket = TradeTicket(
        symbol=position["symbol"],
        quantity=abs(qty),
        order_type="market", # Default close to market for now
        strategy_type=position.get("strategy_key", "").split("_")[-1],
        source_engine="manual_close",
        legs=[
            {"symbol": position["symbol"], "action": side, "quantity": abs(qty)}
        ]
    )

    # 3. Stage Closing Order
    # Reuse trace_id from position
    trace_id_override = position.get("trace_id")
    # Also pass suggestion_id as source_ref for full context lookup
    if position.get("suggestion_id"):
        ticket.source_ref_id = position.get("suggestion_id")

    order_id = _stage_order_internal(
        supabase,
        analytics,
        user_id,
        ticket,
        position["portfolio_id"],
        position_id=req.position_id,
        trace_id_override=trace_id_override
    )

    # 4. Process
    _process_orders_for_user(supabase, analytics, user_id, target_order_id=order_id)

    # 5. Fetch result order
    order_res = supabase.table("paper_orders").select("*").eq("id", order_id).single().execute()
    order = order_res.data

    if order and order["status"] == "filled":
        # Attribution Logic is handled inside _process_orders_for_user upon fill
        pass

    return {
        "status": order["status"] if order else "unknown",
        "order_id": order_id
    }

# --- Internal Helpers ---

def _derive_strategy_key(ticket: TradeTicket) -> str:
    mock_suggestion = {
        "strategy_type": ticket.strategy_type,
        "strategy": ticket.strategy_type,
    }
    normalized_strat = infer_strategy_key_from_suggestion(mock_suggestion)
    if normalized_strat == "unknown":
        normalized_strat = "custom"
    return f"{ticket.symbol}_{normalized_strat}"

def _get_or_create_portfolio(supabase, user_id, portfolio_id=None):
    if portfolio_id:
        res = supabase.table("paper_portfolios").select("*").eq("id", portfolio_id).eq("user_id", user_id).single().execute()
        if res.data:
            return res.data
        raise HTTPException(status_code=404, detail="Portfolio not found")

    # Default
    existing = supabase.table("paper_portfolios").select("*").eq("user_id", user_id).order("created_at", desc=False).limit(1).execute()
    if existing.data:
        return existing.data[0]

    # Create
    new_port = supabase.table("paper_portfolios").insert({
        "user_id": user_id,
        "name": "Main Paper",
        "cash_balance": 100000.0,
        "net_liq": 100000.0
    }).execute()
    if not new_port.data:
        raise HTTPException(status_code=500, detail="Failed to create portfolio")
    return new_port.data[0]

def _stage_order_internal(supabase, analytics, user_id, ticket: TradeTicket, portfolio_id_arg=None, position_id=None, trace_id_override=None):
    portfolio = _get_or_create_portfolio(supabase, user_id, portfolio_id_arg)
    portfolio_id = portfolio["id"]

    # Resolve Context
    suggestion_id = None
    trace_id = trace_id_override

    # Metadata for telemetry
    model_version = None
    features_hash = None
    strategy = None
    window = None
    regime = None

    if ticket.source_ref_id:
        suggestion_id = str(ticket.source_ref_id)
        # Fetch suggestion context
        try:
             s_res = supabase.table("trade_suggestions").select("*").eq("id", suggestion_id).single().execute()
             if s_res.data:
                 s_data = s_res.data
                 # Prefer suggestion's trace_id unless overridden (which shouldn't happen usually if linked)
                 if not trace_id:
                     trace_id = s_data.get("trace_id")

                 model_version = s_data.get("model_version")
                 features_hash = s_data.get("features_hash")
                 strategy = s_data.get("strategy")
                 window = s_data.get("window")
                 regime = s_data.get("regime")
        except:
            pass

    if not trace_id:
        trace_id = str(uuid.uuid4())

    # Fetch Quote
    poly = PolygonService()
    try:
        quote = poly.get_recent_quote(ticket.symbol)
    except:
        quote = None

    # TCM Estimate
    tcm_est = TransactionCostModel.estimate(ticket, quote)

    # Prepare Order
    side = ticket.legs[0].action if ticket.legs else "buy"

    order_payload = {
        "portfolio_id": portfolio_id,
        "status": "staged",
        "staged_at": datetime.now(timezone.utc).isoformat(),
        "trace_id": trace_id,
        "suggestion_id": suggestion_id,
        "order_json": ticket.model_dump(mode="json"),

        # V3 Fields
        "requested_qty": ticket.quantity,
        "requested_price": ticket.limit_price,
        "side": side,
        "order_type": ticket.order_type,
        "quote_at_stage": quote,
        "tcm": tcm_est,
        "position_id": position_id
    }

    res = supabase.table("paper_orders").insert(order_payload).execute()
    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to stage order")

    order_id = res.data[0]["id"]

    # Telemetry
    ctx = TradeContext(
        trace_id=trace_id,
        suggestion_id=suggestion_id,
        model_version=model_version,
        features_hash=features_hash,
        strategy=strategy,
        window=window,
        regime=regime
    )
    emit_trade_event(analytics, user_id, ctx, "order_staged", is_paper=True, properties={"order_id": order_id})

    return order_id

def _compute_fill_deltas(order: dict, fill_res: dict) -> dict:
    """
    Computes incremental deltas for this tick's fill.
    Returns:
        this_fill_qty: float (incremental qty filled this tick)
        this_fill_price: float (price for this incremental fill)
        new_total_filled_qty: float (cumulative)
        new_avg_fill_price: float (cumulative avg)
        fees_total: float (cumulative fees)
        fees_delta: float (incremental fees this tick)
    """

    req_qty = float(order.get("requested_qty") or order.get("quantity") or 0.0)
    prev_total_filled = float(order.get("filled_qty") or 0.0)
    prev_fees_total = float(order.get("fees_usd") or 0.0)

    new_total_filled_qty = float(fill_res.get("filled_qty") or 0.0)
    new_avg_fill_price = float(fill_res.get("avg_fill_price") or 0.0)

    this_fill_qty = float(fill_res.get("last_fill_qty") or 0.0)
    if this_fill_qty <= 0:
        this_fill_qty = max(0.0, new_total_filled_qty - prev_total_filled)

    this_fill_price = float(fill_res.get("last_fill_price") or 0.0)
    if this_fill_price <= 0:
        this_fill_price = float(fill_res.get("avg_fill_price") or 0.0)

    # Fees math
    tcm_est = order.get("tcm") or {}
    est_fees = float(tcm_est.get("fees_usd") or 0.0)

    if req_qty > 0:
        fees_total = (new_total_filled_qty / req_qty) * est_fees
    else:
        fees_total = 0.0

    fees_delta = max(0.0, fees_total - prev_fees_total)

    return {
        "this_fill_qty": this_fill_qty,
        "this_fill_price": this_fill_price,
        "new_total_filled_qty": new_total_filled_qty,
        "new_avg_fill_price": new_avg_fill_price,
        "fees_total": fees_total,
        "fees_delta": fees_delta
    }

def _process_orders_for_user(supabase, analytics, user_id, target_order_id=None):
    # Fetch working orders: staged, working, or partial
    # A1) Replace exact "staged" check with list of in-flight states
    # We need to filter by portfolio owned by user, or join.
    # Simplest is to get user portfolios then filter orders.
    # Or rely on RLS if enabled. Assuming we trust backend:

    # Get user portfolios
    p_res = supabase.table("paper_portfolios").select("id, cash_balance").eq("user_id", user_id).execute()
    if not p_res.data:
        return 0
    p_map = {p["id"]: p for p in p_res.data}
    p_ids = list(p_map.keys())

    # A1 Implementation
    query = supabase.table("paper_orders").select("*").in_("status", ["staged", "working", "partial"])
    orders_res = query.in_("portfolio_id", p_ids).execute()
    orders = orders_res.data

    if target_order_id:
        orders = [o for o in orders if o["id"] == target_order_id]

    processed_count = 0
    poly = PolygonService()

    for order in orders:
        # Fetch fresh quote
        # Extract symbol from order_json
        ticket_data = order.get("order_json", {})
        symbol = ticket_data.get("symbol")

        quote = None
        if symbol:
            try:
                quote = poly.get_recent_quote(symbol)
            except:
                pass

        # Simulate Fill
        fill_res = TransactionCostModel.simulate_fill(order, quote)

        # B) Commit only when a NEW fill happened this tick
        should_commit = False

        last_qty = float(fill_res.get("last_fill_qty") or 0.0)

        # Must be in a valid fill state AND have new quantity
        if fill_res.get("status") in ("partial", "filled") and last_qty > 0:
            should_commit = True

        if should_commit:
            # Commit Fill
            _commit_fill(supabase, analytics, user_id, order, fill_res, quote, p_map[order["portfolio_id"]])
            processed_count += 1
            pass

        elif fill_res["status"] == "working":
            # Update last checked?
            # Optionally update status to 'working' if it was 'staged'
            if order["status"] == "staged":
                supabase.table("paper_orders").update({"status": "working"}).eq("id", order["id"]).execute()

    return processed_count


def _commit_fill(supabase, analytics, user_id, order, fill_res, quote, portfolio):
    # D) Use helper to compute deltas
    deltas = _compute_fill_deltas(order, fill_res)

    this_fill_qty = deltas["this_fill_qty"]
    this_fill_price = deltas["this_fill_price"]

    new_total_filled_qty = deltas["new_total_filled_qty"]
    new_avg_fill_price = deltas["new_avg_fill_price"]

    fees_total = deltas["fees_total"]
    fees_delta = deltas["fees_delta"]

    now = datetime.now(timezone.utc).isoformat()

    # 1. Update Order with CUMULATIVE totals
    # BUT write the order row using cumulative totals
    update_payload = {
        "status": fill_res["status"],
        "filled_qty": new_total_filled_qty,
        "avg_fill_price": new_avg_fill_price,
        "fees_usd": fees_total,
        "filled_at": now,
        "quote_at_fill": quote
    }

    supabase.table("paper_orders").update(update_payload).eq("id", order["id"]).execute()

    # 2. Update Portfolio & Position with INCREMENTAL deltas
    side = order.get("side", "buy")
    multiplier = 100.0

    # Cash Delta uses incremental qty and price + incremental fees
    txn_value = this_fill_qty * this_fill_price * multiplier

    # Cash Impact:
    # Buy: - (Price * Qty) - Fees
    # Sell: + (Price * Qty) - Fees

    cash_delta = 0.0
    if side == "buy":
        cash_delta = -(txn_value + fees_delta)
    else:
        cash_delta = (txn_value - fees_delta)

    # Use fresh cash from portfolio object (which we assume is up to date or we fetch)
    # In _process loop we pass p_map[id], let's trust it but verify
    current_cash = float(portfolio["cash_balance"])
    new_cash = current_cash + cash_delta

    # Update DB
    supabase.table("paper_portfolios").update({"cash_balance": new_cash}).eq("id", portfolio["id"]).execute()

    # Update in-memory portfolio object for subsequent fills in same loop
    portfolio["cash_balance"] = new_cash

    # Ledger uses incremental
    supabase.table("paper_ledger").insert({
        "portfolio_id": portfolio["id"],
        "amount": cash_delta,
        "description": f"Paper fill {side} {this_fill_qty} @ {this_fill_price:.4f} (fees {fees_delta:.2f})",
        "balance_after": new_cash
    }).execute()

    # Position Logic
    pos_id = order.get("position_id")
    ticket = order.get("order_json", {})
    symbol = ticket.get("symbol")
    strategy_key = _derive_strategy_key(TradeTicket(**ticket)) # reconstruct ticket object

    # Signed Quantity logic
    # Buy adds (+), Sell subtracts (-)
    fill_sign = 1.0 if side == "buy" else -1.0
    signed_incremental_qty = this_fill_qty * fill_sign

    # Locate or create position
    if pos_id:
        pos_res = supabase.table("paper_positions").select("*").eq("id", pos_id).single().execute()
        pos = pos_res.data
    else:
        # Opening logic fallback: try to find by strategy key
        pos_res = supabase.table("paper_positions").select("*").eq("portfolio_id", portfolio["id"]).eq("strategy_key", strategy_key).execute()
        pos = pos_res.data[0] if pos_res.data else None

    if pos:
        # Update existing
        current_qty = float(pos["quantity"]) # Signed
        current_avg = float(pos["avg_entry_price"])

        new_qty = current_qty + signed_incremental_qty

        # Average Price Logic
        # Only update avg price if we are increasing exposure in the same direction
        # Or flipping direction.

        new_avg = current_avg

        # Case 1: Increasing exposure (Same sign)
        if (current_qty >= 0 and signed_incremental_qty > 0) or (current_qty <= 0 and signed_incremental_qty < 0):
            # Weighted average of OLD total vs NEW incremental
            total_cost = (abs(current_qty) * current_avg) + (abs(signed_incremental_qty) * this_fill_price)
            if abs(new_qty) > 0:
                new_avg = total_cost / abs(new_qty)

        # Case 2: Reducing exposure (Opposite sign, no flip)
        # Avg price stays same (LIFO/FIFO agnostic for avg cost)

        # Case 3: Flip (Crossed zero)
        # e.g. +5 to -5.
        if (current_qty > 0 and new_qty < 0) or (current_qty < 0 and new_qty > 0):
            # The portion that flipped is new_qty.
            # The cost basis for that portion is this_fill_price.
            # Simplified: if we flip, new avg is the fill price of the flip.
            new_avg = this_fill_price

        if new_qty == 0:
            # Closed completely
            if pos_id: # Was explicit close
                 # E) Attribution invocation should use UPDATED cumulative order values
                 # Merge update_payload into order to get cumulative values
                 order_updated = {**order, **update_payload}
                 # Pass fees_total (cumulative), not delta
                 _run_attribution(supabase, user_id, order_updated, pos, new_avg_fill_price, fees_total, side)

            # We delete the position if 0
            supabase.table("paper_positions").delete().eq("id", pos["id"]).execute()
        else:
            # Update
            supabase.table("paper_positions").update({
                "quantity": new_qty,
                "avg_entry_price": new_avg,
                "updated_at": now
            }).eq("id", pos["id"]).execute()

    else:
        # Create new
        # signed_incremental_qty is the quantity
        pos_payload = {
            "portfolio_id": portfolio["id"],
            "strategy_key": strategy_key,
            "symbol": symbol,
            "quantity": signed_incremental_qty,
            "avg_entry_price": this_fill_price,
            "current_mark": this_fill_price,
            "unrealized_pl": 0.0,
            # Linkage
            "trace_id": order.get("trace_id"),
            "suggestion_id": order.get("suggestion_id")
        }

        # Enrich with model metadata from suggestion if available
        if order.get("suggestion_id"):
            try:
                s_res = supabase.table("trade_suggestions").select("model_version, features_hash, strategy, window, regime").eq("id", order.get("suggestion_id")).single().execute()
                if s_res.data:
                    pos_payload.update(s_res.data)
            except Exception as e:
                logging.warning(f"Failed to fetch suggestion metadata for position: {e}")

        new_pos = supabase.table("paper_positions").insert(pos_payload).execute()

        # Update order with the new position_id
        if new_pos.data:
            new_pos_id = new_pos.data[0]["id"]
            supabase.table("paper_orders").update({"position_id": new_pos_id}).eq("id", order["id"]).execute()

    # Telemetry
    emit_trade_event(analytics, user_id, TradeContext(trace_id=order.get("trace_id")), "order_filled", is_paper=True, properties={"order_id": order["id"]})


def _run_attribution(supabase, user_id, order, position, exit_fill, fees, side):
    """
    Computes PnL attribution and logs to learning_feedback_loops
    """
    try:
        entry_price = float(position["avg_entry_price"])
        quantity = float(order["filled_qty"])

        # Need "Mid" prices for attribution
        # Entry Mid: hard to get if we didn't store it on position.
        # Approximation: entry_price (assuming we paid close to mid or spread cost was burned).
        # Better: if we stored quote_at_fill in the opening order!
        # But we don't have easy link to opening order.
        # Fallback: Use entry_price as entry_mid.
        entry_mid = entry_price

        # Exit Mid
        quote_at_exit = order.get("quote_at_fill") or {}
        bid = quote_at_exit.get("bid_price", 0)
        ask = quote_at_exit.get("ask_price", 0)
        exit_mid = (bid + ask) / 2.0 if (bid and ask) else exit_fill

        attr = PnlAttribution.compute(
            entry_mid=entry_mid,
            entry_fill=entry_price,
            exit_mid=exit_mid,
            exit_fill=exit_fill,
            quantity=quantity,
            fees_total=fees,
            direction="long" if side == "sell" else "short" # We are closing. If selling, we were long.
        )

        # Insert LFL
        trace_id = order.get("trace_id")
        suggestion_id = order.get("suggestion_id")

        reason_codes = []
        if not suggestion_id:
            reason_codes.append("missing_suggestion_link")
        if entry_price == entry_mid:
            reason_codes.append("fallback_entry_mid_used")
        if not quote_at_exit:
            reason_codes.append("missing_quote_at_exit")

        payload = {
            "user_id": user_id,
            "trace_id": trace_id,
            "suggestion_id": suggestion_id,
            "execution_id": order.get("id"),
            "is_paper": True,
            "pnl_realized": attr["pnl_total"],
            "pnl_alpha": attr["pnl_alpha"],
            "pnl_execution_drag": attr["pnl_execution_drag"],
            "fees_total": attr["fees_total"],
            "entry_mid": entry_mid,
            "entry_fill": entry_price,
            "exit_mid": exit_mid,
            "exit_fill": exit_fill,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "outcome_type": "trade_closed",
            "details_json": {"reason_codes": reason_codes}
        }

        # Enrich from suggestion
        if suggestion_id:
            try:
                s_res = supabase.table("trade_suggestions").select("ev, model_version, features_hash, strategy, window, regime").eq("id", suggestion_id).single().execute()
                if s_res.data:
                    data = s_res.data
                    payload["pnl_predicted"] = data.get("ev")
                    payload["model_version"] = data.get("model_version")
                    payload["features_hash"] = data.get("features_hash")
                    payload["strategy"] = data.get("strategy")
                    payload["window"] = data.get("window")
                    payload["regime"] = data.get("regime")
            except Exception as e:
                logging.warning(f"Failed to fetch suggestion data for LFL: {e}")

        # Fallback strategy key if not in suggestion
        if "strategy" not in payload:
            strat_key = position.get("strategy_key","")
            if "_" in strat_key:
                payload["strategy"] = strat_key.split("_")[-1]

        supabase.table("learning_feedback_loops").insert(payload).execute()

    except Exception as e:
        logging.error(f"Attribution failed: {e}")

@router.post("/paper/reset")
def reset_paper_portfolio(
    user_id: str = Depends(get_current_user),
):
    supabase = get_supabase()
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    port_res = supabase.table("paper_portfolios").select("id").eq("user_id", user_id).execute()
    portfolio_ids = [p["id"] for p in port_res.data] if port_res.data else []

    if portfolio_ids:
        supabase.table("paper_orders").delete().in_("portfolio_id", portfolio_ids).execute()
        supabase.table("paper_positions").delete().in_("portfolio_id", portfolio_ids).execute()
        supabase.table("paper_ledger").delete().in_("portfolio_id", portfolio_ids).execute()
        supabase.table("paper_portfolios").delete().in_("id", portfolio_ids).execute()

    new_port = supabase.table("paper_portfolios").insert({
        "user_id": user_id,
        "name": "Main Paper",
        "cash_balance": 100000.0,
        "net_liq": 100000.0
    }).execute()

    if not new_port.data:
        raise HTTPException(status_code=500, detail="Failed to recreate paper portfolio")

    return {
        "status": "reset",
        "portfolio": new_port.data[0]
    }
@router.get("/paper/portfolio")
def get_paper_portfolio(
    user_id: str = Depends(get_current_user),
):
    supabase = get_supabase()
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    # Fetch paper_portfolios for user (limit 1 for v1)
    port_res = supabase.table("paper_portfolios").select("*").eq("user_id", user_id).limit(1).execute()
    if not port_res.data:
        # Check if we should auto-create, or return empty
        return {"portfolio": None, "positions": [], "stats": {}}

    portfolio = port_res.data[0]
    portfolio_id = portfolio["id"]

    # Fetch positions
    pos_res = supabase.table("paper_positions").select("*").eq("portfolio_id", portfolio_id).execute()
    positions = pos_res.data if pos_res.data else []

    # Aggregate basic stats
    total_unrealized_pl = sum([float(p.get("unrealized_pl", 0) or 0) for p in positions])
    open_positions_count = len(positions)

    # Calculate benchmarks
    spy_return_pct = 0.0
    zero_strategy_return_pct = 0.0

    created_at_str = portfolio.get("created_at")
    if created_at_str:
        try:
            start_dt = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            now_dt = datetime.now(timezone.utc)
            days_elapsed = (now_dt - start_dt).days

            # 1. Zero Strategy (Risk Free): 4.5% annualized
            zero_strategy_return_pct = (0.045 / 365.0) * days_elapsed * 100

            # 2. SPY Benchmark
            try:
                poly = PolygonService()
                current_spy = poly.get_recent_quote("SPY") or {}

                bid = float(current_spy.get("bid_price") or current_spy.get("bid") or 0.0)
                ask = float(current_spy.get("ask_price") or current_spy.get("ask") or 0.0)

                # Prefer explicit midpoint if provided by the service; otherwise compute from bid/ask.
                current_price = float(
                    current_spy.get("price")
                    or ((bid + ask) / 2.0 if bid > 0 and ask > 0 else 0.0)
                )

                if current_price > 0:
                    start_date_str = start_dt.strftime("%Y-%m-%d")

                    # Pull a small window ending shortly AFTER the portfolio start date so we can
                    # pick the first trading day on/after start_date_str (handles weekends/holidays).
                    hist = poly.get_historical_prices(
                        "SPY",
                        days=10,
                        to_date=start_dt + timedelta(days=7),
                    )

                    dates = (hist or {}).get("dates") or []
                    prices = (hist or {}).get("prices") or []

                    start_price = 0.0
                    for d, p in zip(dates, prices):
                        if d >= start_date_str:
                            try:
                                start_price = float(p or 0.0)
                            except Exception:
                                start_price = 0.0
                            break

                    if start_price > 0:
                        spy_return_pct = ((current_price - start_price) / start_price) * 100.0

            except Exception as e:
                logging.warning(f"Failed to calc SPY benchmark: {e}")

        except Exception as e:
             logging.error(f"Benchmark calculation error: {e}")


    return {
        "portfolio": portfolio,
        "positions": positions,
        "stats": {
            "total_unrealized_pl": total_unrealized_pl,
            "open_positions_count": open_positions_count,
            "spy_return_pct": round(spy_return_pct, 4),
            "zero_strategy_return_pct": round(zero_strategy_return_pct, 4)
        }
    }
