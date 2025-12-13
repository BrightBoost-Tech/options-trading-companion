from fastapi import APIRouter, HTTPException, Depends
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
from packages.quantum.services.paper_execution_service import PaperExecutionService

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

class PaperExecuteRequest(BaseModel):
    ticket: TradeTicket
    portfolio_id: Optional[str] = None  # if null, use/create default

class PaperCloseRequest(BaseModel):
    position_id: str

@router.post("/paper/execute")
def execute_paper_trade(
    req: PaperExecuteRequest,
    user_id: str = Depends(get_current_user),
):
    supabase = get_supabase()
    analytics = get_analytics_service()

    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    svc = PaperExecutionService(supabase)

    # 1. Ensure portfolio
    if req.portfolio_id:
        portfolio_id = req.portfolio_id
    else:
        # Find default or create
        existing = supabase.table("paper_portfolios").select("*").eq("user_id", user_id).order("created_at", desc=False).limit(1).execute()
        if existing.data:
            portfolio_id = existing.data[0]["id"]
        else:
            new_port = supabase.table("paper_portfolios").insert({
                "user_id": user_id,
                "name": "Main Paper",
                "cash_balance": 100000.0,
                "net_liq": 100000.0
            }).execute()
            if not new_port.data:
                raise HTTPException(status_code=500, detail="Failed to create paper portfolio")
            portfolio_id = new_port.data[0]["id"]

    # 2. Stage Order
    try:
        order, ctx = svc.stage_order(
            user_id=user_id,
            ticket=req.ticket,
            portfolio_id=portfolio_id,
            suggestion_id=str(req.ticket.source_ref_id) if req.ticket.source_ref_id else None
        )

        # Emit staged event
        emit_trade_event(analytics, user_id, ctx, "order_staged", is_paper=True)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stage order: {e}")

    # 3. Process Order (Instant execution for now, but via pipeline)
    try:
        result = svc.process_order(order["id"], user_id, analytics)

        # Emit filled event
        if result["status"] == "filled":
             emit_trade_event(
                 analytics,
                 user_id,
                 ctx,
                 "order_filled",
                 execution_id=order["id"],
                 is_paper=True,
                 properties={
                     "symbol": req.ticket.symbol,
                     "quantity": result.get("filled_quantity"),
                     "price": result.get("fill_price"),
                     "slippage": result.get("slippage")
                 }
             )

        return {
            "status": result["status"],
            "order": result,
            "portfolio_id": portfolio_id
        }

    except Exception as e:
        # If process fails, order stays staged/failed
        raise HTTPException(status_code=500, detail=f"Failed to process order: {e}")

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

@router.post("/paper/close")
def close_paper_position(
    req: PaperCloseRequest,
    user_id: str = Depends(get_current_user),
):
    """
    Closes a position by generating a sell order.
    """
    supabase = get_supabase()
    analytics = get_analytics_service()

    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    svc = PaperExecutionService(supabase)

    # 1. Lookup position
    pos_res = supabase.table("paper_positions").select("*").eq("id", req.position_id).single().execute()
    if not pos_res.data:
        raise HTTPException(status_code=404, detail="Position not found")

    position = pos_res.data

    # 2. Create Closing Ticket
    # We need to sell the quantity we have.
    # Current mark is best guess for price.
    price = float(position.get("current_mark") or position.get("avg_entry_price") or 0)

    ticket = TradeTicket(
        symbol=position["symbol"],
        quantity=float(position["quantity"]),
        action="Sell to Close",
        strategy_type=position.get("strategy_key", "").split("_")[-1],
        limit_price=price,
        order_type="limit"
    )

    # 3. Stage & Process
    try:
        order, ctx = svc.stage_order(user_id, ticket, position["portfolio_id"])

        emit_trade_event(analytics, user_id, ctx, "trade_closed", is_paper=True) # Intent to close

        result = svc.process_order(order["id"], user_id, analytics)

        return {
            "status": "closed",
            "execution": result
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to close position: {e}")

@router.post("/paper/reset")
def reset_paper_portfolio(
    user_id: str = Depends(get_current_user),
):
    """
    Resets the user's paper trading account.
    Deletes all positions, orders, ledger entries, and the portfolio itself.
    Creates a new portfolio with $100k.
    """
    supabase = get_supabase()
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    # 1. Fetch existing portfolio(s)
    port_res = supabase.table("paper_portfolios").select("id").eq("user_id", user_id).execute()
    portfolio_ids = [p["id"] for p in port_res.data] if port_res.data else []

    if portfolio_ids:
        # 2. Delete related data
        supabase.table("paper_orders").delete().in_("portfolio_id", portfolio_ids).execute()
        supabase.table("paper_positions").delete().in_("portfolio_id", portfolio_ids).execute()
        supabase.table("paper_ledger").delete().in_("portfolio_id", portfolio_ids).execute()

        # 3. Delete portfolios
        supabase.table("paper_portfolios").delete().in_("id", portfolio_ids).execute()

    # 4. Create fresh portfolio
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
