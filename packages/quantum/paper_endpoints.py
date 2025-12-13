from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
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

# v3 Observability
from packages.quantum.observability.telemetry import TradeContext, emit_trade_event, TradeEventName
from packages.quantum.services.analytics_service import AnalyticsService

router = APIRouter()

def get_supabase():
    from api import supabase  # reuse global supabase client
    return supabase

def get_analytics_service():
    from api import analytics_service
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
    order_id = _stage_order_internal(supabase, analytics, user_id, ticket, position["portfolio_id"], position_id=req.position_id)

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

def _stage_order_internal(supabase, analytics, user_id, ticket: TradeTicket, portfolio_id_arg=None, position_id=None):
    portfolio = _get_or_create_portfolio(supabase, user_id, portfolio_id_arg)
    portfolio_id = portfolio["id"]

    # Resolve Context
    suggestion_id = None
    trace_id = None
    if ticket.source_ref_id:
        suggestion_id = str(ticket.source_ref_id)
        # Fetch suggestion context
        try:
             s_res = supabase.table("trade_suggestions").select("trace_id").eq("id", suggestion_id).single().execute()
             if s_res.data:
                 trace_id = s_res.data.get("trace_id")
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
    ctx = TradeContext(trace_id=trace_id, suggestion_id=suggestion_id)
    emit_trade_event(analytics, user_id, ctx, "order_staged", is_paper=True, properties={"order_id": order_id})

    return order_id

def _process_orders_for_user(supabase, analytics, user_id, target_order_id=None):
    # Fetch working orders
    query = supabase.table("paper_orders").select("*").eq("status", "staged") # Add 'working' later
    # We need to filter by portfolio owned by user, or join.
    # Simplest is to get user portfolios then filter orders.
    # Or rely on RLS if enabled. Assuming we trust backend:

    # Get user portfolios
    p_res = supabase.table("paper_portfolios").select("id, cash_balance").eq("user_id", user_id).execute()
    if not p_res.data:
        return 0
    p_map = {p["id"]: p for p in p_res.data}
    p_ids = list(p_map.keys())

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

        if fill_res["status"] in ["filled", "partial"]:
            # Commit Fill
            _commit_fill(supabase, analytics, user_id, order, fill_res, quote, p_map[order["portfolio_id"]])
            processed_count += 1

        elif fill_res["status"] == "working":
            # Update last checked?
            pass

    return processed_count

def _commit_fill(supabase, analytics, user_id, order, fill_res, quote, portfolio):
    # 1. Update Order
    now = datetime.now(timezone.utc).isoformat()

    fees = 0.0 # TCM might return fees in simulate_fill if we updated it, but estimate has it.
    # Re-calc fees based on actual fill qty
    # Simple logic:
    filled_qty = fill_res["filled_qty"]
    fill_price = fill_res["avg_fill_price"]

    # Get fees from TCM estimate in order if available, pro-rated
    tcm_est = order.get("tcm") or {}
    est_fees = tcm_est.get("fees_usd", 0.0)
    req_qty = float(order.get("requested_qty") or 1)
    fees = (filled_qty / req_qty) * est_fees if req_qty > 0 else 0

    update_payload = {
        "status": fill_res["status"],
        "filled_qty": filled_qty,
        "avg_fill_price": fill_price,
        "fees_usd": fees,
        "filled_at": now,
        "quote_at_fill": quote
    }

    supabase.table("paper_orders").update(update_payload).eq("id", order["id"]).execute()

    # 2. Update Portfolio & Position
    side = order.get("side", "buy")
    multiplier = 100.0

    txn_value = filled_qty * fill_price * multiplier

    # Cash Impact:
    # Buy: - (Price * Qty) - Fees
    # Sell: + (Price * Qty) - Fees

    cash_delta = 0.0
    if side == "buy":
        cash_delta = -(txn_value + fees)
    else:
        cash_delta = (txn_value - fees)

    new_cash = float(portfolio["cash_balance"]) + cash_delta

    supabase.table("paper_portfolios").update({"cash_balance": new_cash}).eq("id", portfolio["id"]).execute()

    # Ledger
    supabase.table("paper_ledger").insert({
        "portfolio_id": portfolio["id"],
        "amount": cash_delta,
        "description": f"Fill {side} {filled_qty} {order.get('order_json', {}).get('symbol')} @ {fill_price}",
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
    signed_filled_qty = filled_qty * fill_sign

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

        new_qty = current_qty + signed_filled_qty

        # Average Price Logic
        # Only update avg price if we are increasing exposure in the same direction
        # Or flipping direction.

        new_avg = current_avg

        # Case 1: Increasing exposure (Same sign)
        if (current_qty >= 0 and signed_filled_qty > 0) or (current_qty <= 0 and signed_filled_qty < 0):
            total_cost = (abs(current_qty) * current_avg) + (abs(signed_filled_qty) * fill_price)
            if abs(new_qty) > 0:
                new_avg = total_cost / abs(new_qty)

        # Case 2: Reducing exposure (Opposite sign, no flip)
        # Avg price stays same (LIFO/FIFO agnostic for avg cost)

        # Case 3: Flip (Crossed zero)
        # e.g. +5 to -5.
        if (current_qty > 0 and new_qty < 0) or (current_qty < 0 and new_qty > 0):
            # The portion that flipped is new_qty.
            # The cost basis for that portion is fill_price.
            new_avg = fill_price

        if new_qty == 0:
            # Closed completely
            if pos_id: # Was explicit close
                 _run_attribution(supabase, user_id, order, pos, fill_price, fees, side)

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
        # signed_filled_qty is the quantity
        pos_payload = {
            "portfolio_id": portfolio["id"],
            "strategy_key": strategy_key,
            "symbol": symbol,
            "quantity": signed_filled_qty,
            "avg_entry_price": fill_price,
            "current_mark": fill_price,
            "unrealized_pl": 0.0
        }
        supabase.table("paper_positions").insert(pos_payload).execute()

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

        payload = {
            "user_id": user_id,
            "trace_id": trace_id,
            "suggestion_id": suggestion_id,
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
            "outcome_type": "individual_trade"
        }

        # Strategy context
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
                current_spy = poly.get_recent_quote("SPY")
                current_price = (current_spy.get("bid_price", 0) + current_spy.get("ask_price", 0)) / 2 if current_spy else 0

                if current_price > 0:
                    start_date_str = start_dt.strftime("%Y-%m-%d")
                    # Fetch 1 day of data
                    hist = poly.get_historical_prices("SPY", from_date=start_date_str, to_date=start_date_str)
                    if hist and len(hist) > 0:
                        start_price = hist[0].get("close", 0) # or open
                        if start_price > 0:
                            spy_return_pct = ((current_price - start_price) / start_price) * 100
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
