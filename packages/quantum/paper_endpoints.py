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

    ticket = req.ticket

    # 1. Ensure portfolio (use provided portfolio_id or auto-find/create "Main Paper")
    # Query paper_portfolios by user_id
    if req.portfolio_id:
        portfolio_res = supabase.table("paper_portfolios").select("*").eq("id", req.portfolio_id).eq("user_id", user_id).single().execute()
        if not portfolio_res.data:
            raise HTTPException(status_code=404, detail="Portfolio not found")
        portfolio = portfolio_res.data
    else:
        # Find default or create
        existing = supabase.table("paper_portfolios").select("*").eq("user_id", user_id).order("created_at", desc=False).limit(1).execute()
        if existing.data:
            portfolio = existing.data[0]
        else:
            # Create default
            new_port = supabase.table("paper_portfolios").insert({
                "user_id": user_id,
                "name": "Main Paper",
                "cash_balance": 100000.0,
                "net_liq": 100000.0
            }).execute()
            if not new_port.data:
                raise HTTPException(status_code=500, detail="Failed to create paper portfolio")
            portfolio = new_port.data[0]

    portfolio_id = portfolio["id"]

    # 2. Compute notional:
    price = ticket.limit_price or 0.0
    multiplier = 100
    notional = price * ticket.quantity * multiplier

    # Cash guardrail
    if notional > 0:
        current_cash = float(portfolio["cash_balance"])
        if current_cash < notional:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient paper cash. Required: ${notional:.2f}, Available: ${current_cash:.2f}. Reset portfolio or reduce size."
            )

    # v3 Observability: Resolve Context from Suggestion
    suggestion_id = None
    trace_id = None
    model_version = "v2"
    features_hash = "unknown"
    regime = None
    window = None
    strategy = ticket.strategy_type

    if ticket.source_ref_id:
        suggestion_id = str(ticket.source_ref_id)
        # Fetch suggestion for trace info
        try:
            s_res = supabase.table("trade_suggestions").select("*").eq("id", suggestion_id).single().execute()
            if s_res.data:
                s_data = s_res.data
                trace_id = s_data.get("trace_id")
                model_version = s_data.get("model_version", "v2")
                features_hash = s_data.get("features_hash", "unknown")
                regime = s_data.get("regime")
                window = s_data.get("window")
                strategy = s_data.get("strategy") or strategy # Prefer suggestion strategy if valid
        except Exception as e:
            logging.warning(f"Failed to fetch suggestion context for paper trade: {e}")

    # Create TradeContext
    if not trace_id:
         # Fallback: create new trace if no suggestion link
         trace_id = str(uuid.uuid4())

    ctx = TradeContext(
        trace_id=trace_id,
        suggestion_id=suggestion_id,
        model_version=model_version,
        window=window,
        strategy=strategy,
        regime=regime,
        features_hash=features_hash
    )

    # Emit suggestion_accepted (if linked)
    if suggestion_id:
        emit_trade_event(analytics, user_id, ctx, "suggestion_accepted", is_paper=True)

    # 3. Insert into paper_orders with status = 'filled', order_json = ticket.model_dump()
    order_payload = {
        "portfolio_id": portfolio_id,
        "status": "filled",
        "order_json": ticket.model_dump(mode="json"),
        "filled_at": datetime.now(timezone.utc).isoformat(),
        "suggestion_id": suggestion_id,
        "trace_id": trace_id # Persist trace_id
    }
    order_res = supabase.table("paper_orders").insert(order_payload).execute()
    if not order_res.data:
        raise HTTPException(status_code=500, detail="Failed to create order")
    order = order_res.data[0]
    execution_id = order["id"]

    # Emit order_filled
    emit_trade_event(analytics, user_id, ctx, "order_filled", execution_id=execution_id, is_paper=True, properties={"symbol": ticket.symbol, "quantity": ticket.quantity, "price": price})

    # 4. Update portfolio cash_balance and net_liq (subtract notional)
    new_cash = float(portfolio["cash_balance"]) - notional
    supabase.table("paper_portfolios").update({
        "cash_balance": new_cash,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", portfolio_id).execute()

    # 5. Insert/merge into paper_positions:
    mock_suggestion = {
        "strategy_type": ticket.strategy_type,
        "strategy": ticket.strategy_type,
    }
    normalized_strat = infer_strategy_key_from_suggestion(mock_suggestion)
    if normalized_strat == "unknown":
        normalized_strat = "custom"

    strategy_key = f"{ticket.symbol}_{normalized_strat}"

    # Check existing position
    existing_pos = supabase.table("paper_positions").select("*").eq("portfolio_id", portfolio_id).eq("strategy_key", strategy_key).execute()

    if existing_pos.data:
        # Update existing
        pos = existing_pos.data[0]
        old_qty = float(pos["quantity"])
        old_avg = float(pos["avg_entry_price"])
        new_qty = old_qty + ticket.quantity

        # Weighted average price
        if new_qty != 0:
            new_avg = ((old_qty * old_avg) + (ticket.quantity * price)) / new_qty
        else:
            new_avg = 0.0

        supabase.table("paper_positions").update({
            "quantity": new_qty,
            "avg_entry_price": new_avg,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", pos["id"]).execute()

        position_data = {**pos, "quantity": new_qty, "avg_entry_price": new_avg}
    else:
        # Insert new
        pos_payload = {
            "portfolio_id": portfolio_id,
            "strategy_key": strategy_key,
            "symbol": ticket.symbol,
            "quantity": ticket.quantity,
            "avg_entry_price": price,
            "current_mark": price,
            "unrealized_pl": 0.0,
            # We could store trace_id here too for easier close attribution, but we rely on lookup or consistent strategy keys
            # or maybe store "opening_trace_id"?
            # For simplicity in v3, we'll try to recover trace_id at close from paper_orders or lookup.
        }
        pos_res = supabase.table("paper_positions").insert(pos_payload).execute()
        if not pos_res.data:
            raise HTTPException(status_code=500, detail="Failed to create position")
        position_data = pos_res.data[0]

    # 6. Insert a row into paper_ledger
    ledger_payload = {
        "portfolio_id": portfolio_id,
        "amount": -notional,
        "description": f"Open paper trade: {ticket.symbol} {ticket.strategy_type}",
        "balance_after": new_cash
    }
    supabase.table("paper_ledger").insert(ledger_payload).execute()

    # 7. Return a summary
    return {
        "status": "filled",
        "portfolio": {**portfolio, "cash_balance": new_cash},
        "order": order,
        "position": position_data
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

@router.post("/paper/close")
def close_paper_position(
    req: PaperCloseRequest,
    user_id: str = Depends(get_current_user),
):
    supabase = get_supabase()
    analytics = get_analytics_service()

    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    # 1. Lookup position by id + user_id.
    pos_res = supabase.table("paper_positions").select("*").eq("id", req.position_id).single().execute()
    if not pos_res.data:
        raise HTTPException(status_code=404, detail="Position not found")

    position = pos_res.data
    portfolio_id = position["portfolio_id"]

    # Verify user owns this portfolio
    port_res = supabase.table("paper_portfolios").select("user_id, cash_balance").eq("id", portfolio_id).single().execute()
    if not port_res.data or port_res.data["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Unauthorized")

    portfolio = port_res.data

    # 2. Assume exit at current_mark (or allow override later).
    exit_price = float(position.get("current_mark") or position.get("avg_entry_price") or 0)
    quantity = float(position["quantity"])
    multiplier = 100

    proceeds = exit_price * quantity * multiplier
    cost_basis = float(position["avg_entry_price"]) * quantity * multiplier

    # 3. Compute realized P/L
    realized_pl = proceeds - cost_basis

    # 4. Update portfolio cash_balance
    current_cash = float(portfolio["cash_balance"])
    new_cash = current_cash + proceeds

    supabase.table("paper_portfolios").update({
        "cash_balance": new_cash,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", portfolio_id).execute()

    # 5. Insert ledger row
    ledger_payload = {
        "portfolio_id": portfolio_id,
        "amount": proceeds,
        "description": f"Close paper trade: {position['symbol']} (P/L: {realized_pl:.2f})",
        "balance_after": new_cash
    }
    supabase.table("paper_ledger").insert(ledger_payload).execute()

    # 6. v3 Observability: Recover Trace Context
    # Try to find original opening order for this symbol/strategy
    # Strategy key is in position: "SYMBOL_strategy_type"
    strategy_key_val = position.get("strategy_key", "")
    strategy_type = strategy_key_val.split("_")[-1] if "_" in strategy_key_val else "unknown"

    # Look for most recent paper_order for this portfolio with this symbol (inside order_json)
    # This is a bit heuristic if we don't link position->order directly.
    # Ideally position has 'opening_order_id'.
    # For now, we search paper_orders.

    trace_id = None
    suggestion_id = None
    model_version = "v2"
    features_hash = "unknown"
    regime = None
    window = "paper_trading"

    try:
        # Search recent order
        # Need to query JSONB? Or just match suggestion_id if we have it?
        # We don't have suggestion_id on position.
        # Let's order by created_at desc.
        # We can try to use suggestion_id if we stored it in position? No.

        # We will query paper_orders for this portfolio_id
        # and iterate to find matching symbol in order_json.
        # This is inefficient but functional for v3 MVP.
        # Or add symbol column to paper_orders?
        # For now, let's just emit event with limited context if trace missing.

        # Better: use the trace_id we added to paper_orders.
        # If we can find the order.
        orders = supabase.table("paper_orders").select("*").eq("portfolio_id", portfolio_id).order("filled_at", desc=True).limit(20).execute()
        for o in orders.data or []:
            o_json = o.get("order_json") or {}
            if o_json.get("symbol") == position["symbol"]:
                 trace_id = o.get("trace_id")
                 suggestion_id = o.get("suggestion_id")
                 break

        # If we have suggestion_id, fetch suggestion for full context
        if suggestion_id:
             s_res = supabase.table("trade_suggestions").select("*").eq("id", suggestion_id).single().execute()
             if s_res.data:
                s = s_res.data
                trace_id = s.get("trace_id") or trace_id
                model_version = s.get("model_version", "v2")
                features_hash = s.get("features_hash", "unknown")
                regime = s.get("regime")
                window = s.get("window")

    except Exception as e:
        logging.warning(f"Failed to recover trace context for close: {e}")

    # Emit trade_closed
    ctx = TradeContext(
        trace_id=trace_id or str(uuid.uuid4()), # New trace if disconnected
        suggestion_id=suggestion_id,
        model_version=model_version,
        window=window,
        strategy=strategy_type,
        regime=regime,
        features_hash=features_hash
    )

    emit_trade_event(
        analytics,
        user_id,
        ctx,
        "trade_closed",
        is_paper=True,
        properties={
            "realized_pl": realized_pl,
            "symbol": position["symbol"]
        }
    )

    # 7. Learning Loop Integration
    try:
        # Update or Insert Learning Feedback Loop
        # If we have trace_id, we can be very specific.
        # v3 req: "Insert a learning_feedback_loops row keyed by trace_id and suggestion_id"

        feedback_payload = {
            "user_id": user_id,
            "trace_id": trace_id,
            "suggestion_id": suggestion_id,
            "strategy": strategy_type,
            "window": window,
            "regime": regime,
            "model_version": model_version,
            "features_hash": features_hash,
            "is_paper": True,
            "pnl_realized": realized_pl,
            # pnl_predicted? From suggestion ev.
            # We need to fetch suggestion ev if not already.
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "outcome_type": "individual_trade" # Mark as per-trade
        }

        # If we have suggestion, get EV
        if suggestion_id and 's' in locals() and s:
             feedback_payload["pnl_predicted"] = s.get("ev")

        supabase.table("learning_feedback_loops").insert(feedback_payload).execute()

        # Also maintain aggregate stats (legacy support)
        # Check if aggregate columns exist and valid strategy
        supports_aggregate = True
        try:
            supabase.table("learning_feedback_loops").select("total_trades").limit(1).execute()
        except:
             supports_aggregate = False # Maybe columns don't exist

        if supports_aggregate:
             # Find aggregate row
            existing_agg = supabase.table("learning_feedback_loops") \
                .select("*") \
                .eq("user_id", user_id) \
                .eq("strategy", strategy_type) \
                .eq("window", window) \
                .eq("outcome_type", "aggregate") \
                .execute()

            if existing_agg.data:
                rec = existing_agg.data[0]
                new_total = (rec.get("total_trades") or 0) + 1
                new_wins = (rec.get("wins") or 0) + (1 if realized_pl > 0 else 0)
                new_losses = (rec.get("losses") or 0) + (1 if realized_pl < 0 else 0)
                current_avg = float(rec.get("avg_return", 0) or 0)
                old_total = rec.get("total_trades") or 0
                new_avg = ((current_avg * old_total) + realized_pl) / new_total

                supabase.table("learning_feedback_loops").update({
                    "total_trades": new_total,
                    "wins": new_wins,
                    "losses": new_losses,
                    "avg_return": new_avg,
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }).eq("id", rec["id"]).execute()
            else:
                 # Create new aggregate row
                 agg_payload = {
                    "user_id": user_id,
                    "strategy": strategy_type,
                    "window": window,
                    "total_trades": 1,
                    "wins": 1 if realized_pl > 0 else 0,
                    "losses": 1 if realized_pl < 0 else 0,
                    "avg_return": realized_pl,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "outcome_type": "aggregate",
                    "model_version": "aggregate"
                }
                 supabase.table("learning_feedback_loops").insert(agg_payload).execute()

    except Exception as e:
        # Non-blocking error
        logging.error(f"Failed to update learning loop: {e}")

    # 8. Delete position
    supabase.table("paper_positions").delete().eq("id", position["id"]).execute()

    return {
        "status": "closed",
        "realized_pl": realized_pl,
        "new_cash_balance": new_cash
    }

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
