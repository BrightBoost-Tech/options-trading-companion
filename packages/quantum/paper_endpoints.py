from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

from security import get_current_user
from models import TradeTicket

router = APIRouter()

def get_supabase():
    from api import supabase  # reuse global supabase client
    return supabase

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
    # notional = (ticket.limit_price or 0) * ticket.quantity * 100  (options) or * 1 (stock)
    # For v1, we can assume options with 100 multiplier when legs present or typical option strategies.
    # Defaulting to 100 multiplier for now as this is an options platform.
    price = ticket.limit_price or 0.0
    multiplier = 100
    notional = price * ticket.quantity * multiplier

    # Cash guardrail: check sufficient funds for debit trades
    # We assume positive notional means a debit (paying cash).
    if notional > 0:
        current_cash = float(portfolio["cash_balance"])
        if current_cash < notional:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient paper cash. Required: ${notional:.2f}, Available: ${current_cash:.2f}. Reset portfolio or reduce size."
            )

    # 3. Insert into paper_orders with status = 'filled', order_json = ticket.model_dump()
    suggestion_id = None
    if ticket.source_ref_id:
        suggestion_id = str(ticket.source_ref_id)

    order_payload = {
        "portfolio_id": portfolio_id,
        "status": "filled",
        "order_json": ticket.model_dump(mode="json"),
        "filled_at": datetime.now(timezone.utc).isoformat(),
        "suggestion_id": suggestion_id
    }
    order_res = supabase.table("paper_orders").insert(order_payload).execute()
    if not order_res.data:
        raise HTTPException(status_code=500, detail="Failed to create order")
    order = order_res.data[0]

    # 4. Update portfolio cash_balance and net_liq (subtract notional)
    # Buying (debit) reduces cash. Selling (credit) increases cash.
    # We assume 'debit' by default if price > 0, but usually spread strategies specify net_cost (positive for debit).
    # If the strategy was a credit spread, limit_price might be the credit received.
    # However, standard convention often uses positive price for debit and negative for credit, or specifies 'debit'/'credit'.
    # In TradeTicket, we don't explicitly have 'debit/credit' flag, but usually `limit_price` is the price we pay or receive.
    # If `action` is 'buy', we pay. If 'sell', we receive.
    # TradeTicket doesn't have top-level action, but usually suggests 'entry'.
    # For now, let's assume a Debit entry (positive cost) reduces cash.
    # If it's a credit entry (like short iron condor), usually represented as a credit.
    # The prompt says: "Insert a row into paper_ledger with amount = -notional".
    # This implies we treat the trade as a debit (cost) by default.

    new_cash = float(portfolio["cash_balance"]) - notional
    # Net Liq change depends on whether we value the position immediately.
    # If we mark-to-market immediately at entry price, Net Liq is unchanged (Cash went down, Position Value went up).
    # But often transaction costs or spread might cause slight drop. For simplicty, keep Net Liq roughly same or just update cash.
    # Let's update cash.

    supabase.table("paper_portfolios").update({
        "cash_balance": new_cash,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", portfolio_id).execute()

    # 5. Insert/merge into paper_positions:
    # Strategy_key can be f"{ticket.symbol}_{ticket.strategy_type or 'custom'}"
    strategy_key = f"{ticket.symbol}_{ticket.strategy_type or 'custom'}"

    # Check existing position
    existing_pos = supabase.table("paper_positions").select("*").eq("portfolio_id", portfolio_id).eq("strategy_key", strategy_key).execute()

    if existing_pos.data:
        # Update existing
        pos = existing_pos.data[0]
        old_qty = float(pos["quantity"])
        old_avg = float(pos["avg_entry_price"])
        new_qty = old_qty + ticket.quantity

        # Weighted average price
        # (old_qty * old_avg + new_qty_added * price) / new_qty
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
            "current_mark": price, # Assume mark is entry price initially
            "unrealized_pl": 0.0
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
        return {"portfolio": None, "positions": [], "stats": {}}

    portfolio = port_res.data[0]
    portfolio_id = portfolio["id"]

    # Fetch positions
    pos_res = supabase.table("paper_positions").select("*").eq("portfolio_id", portfolio_id).execute()
    positions = pos_res.data if pos_res.data else []

    # Aggregate basic stats
    total_unrealized_pl = sum([float(p.get("unrealized_pl", 0) or 0) for p in positions])
    open_positions_count = len(positions)

    return {
        "portfolio": portfolio,
        "positions": positions,
        "stats": {
            "total_unrealized_pl": total_unrealized_pl,
            "open_positions_count": open_positions_count
        }
    }

@router.post("/paper/close")
def close_paper_position(
    req: PaperCloseRequest,
    user_id: str = Depends(get_current_user),
):
    supabase = get_supabase()
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    # 1. Lookup position by id + user_id.
    # Check ownership via portfolio
    # (Actually RLS handles this, but we need to fetch it first)
    # We can join or just 2-step query.

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
    # Since we don't have live mark in this request, we use `current_mark` from DB if updated,
    # or just `avg_entry_price` if no mark update mechanism is running yet.
    # For a realistic close, we probably want to fetch live price, but for v1 let's assume
    # the frontend or some background job updated `current_mark`.
    # If `current_mark` is null, fall back to `avg_entry_price` (break even) or 0.

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

    # 5. Insert ledger row with +realized_pl? No, ledger tracks cash flow.
    # The cash flow is +proceeds. The P/L is derived.
    # Description can mention P/L.

    ledger_payload = {
        "portfolio_id": portfolio_id,
        "amount": proceeds,
        "description": f"Close paper trade: {position['symbol']} (P/L: {realized_pl:.2f})",
        "balance_after": new_cash
    }
    supabase.table("paper_ledger").insert(ledger_payload).execute()

    # 6. Delete or mark the position as closed (for v1, it’s okay to delete).
    supabase.table("paper_positions").delete().eq("id", position["id"]).execute()

    return {
        "status": "closed",
        "realized_pl": realized_pl,
        "new_cash_balance": new_cash
    }
