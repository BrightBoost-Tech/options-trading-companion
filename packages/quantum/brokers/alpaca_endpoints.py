"""
Alpaca Broker API Endpoints — account, orders, positions, approvals, mode.

All endpoints require auth. Alpaca-dependent endpoints return 503 when
ALPACA_API_KEY is not configured.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Body, Request
from packages.quantum.security import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/broker", tags=["broker"])


def _get_alpaca():
    """Get AlpacaClient or raise 503."""
    from packages.quantum.brokers.alpaca_client import get_alpaca_client
    client = get_alpaca_client()
    if not client:
        raise HTTPException(status_code=503, detail="Alpaca not configured (ALPACA_API_KEY not set)")
    return client


# ── Account ───────────────────────────────────────────────────────────

@router.get("/account")
async def broker_account(user_id: str = Depends(get_current_user)):
    """Account summary: balance, buying power, equity, PDT status."""
    alpaca = _get_alpaca()
    return alpaca.get_account()


@router.get("/pdt-status")
async def broker_pdt_status(request: Request, user_id: str = Depends(get_current_user)):
    """PDT status from both our tracker and Alpaca."""
    alpaca = _get_alpaca()

    alpaca_pdt = {
        "restricted": alpaca.is_pdt_restricted(),
        "day_trade_count": alpaca.get_day_trade_count(),
    }

    # Also get our internal PDT tracking
    internal_pdt = {}
    try:
        from packages.quantum.services.pdt_guard_service import get_pdt_status
        supabase = request.app.state.supabase
        internal_pdt = get_pdt_status(supabase, user_id)
    except Exception:
        pass

    return {"alpaca": alpaca_pdt, "internal": internal_pdt}


# ── Orders ────────────────────────────────────────────────────────────

@router.get("/orders")
async def broker_orders(
    user_id: str = Depends(get_current_user),
    status: str = Query(default="open"),
    limit: int = Query(default=50, le=200),
):
    """List Alpaca orders by status."""
    alpaca = _get_alpaca()
    return {"orders": alpaca.get_orders(status=status, limit=limit)}


@router.get("/orders/{order_id}")
async def broker_order_detail(order_id: str, user_id: str = Depends(get_current_user)):
    """Get Alpaca order detail and sync to internal state."""
    alpaca = _get_alpaca()
    return alpaca.get_order(order_id)


@router.post("/orders/{order_id}/cancel")
async def broker_cancel_order(order_id: str, user_id: str = Depends(get_current_user)):
    """Cancel an open Alpaca order."""
    alpaca = _get_alpaca()
    return alpaca.cancel_order(order_id)


# ── Positions ─────────────────────────────────────────────────────────

@router.get("/positions")
async def broker_positions(
    request: Request,
    user_id: str = Depends(get_current_user),
    source: str = Query(default="auto"),
):
    """Get positions from configured source (auto, alpaca, internal)."""
    supabase = request.app.state.supabase

    from packages.quantum.brokers.position_sync import PositionSyncService
    from packages.quantum.brokers.alpaca_client import get_alpaca_client

    svc = PositionSyncService(supabase, get_alpaca_client())
    return svc.get_positions(user_id, source=source)


@router.get("/reconcile")
async def broker_reconcile(request: Request, user_id: str = Depends(get_current_user)):
    """Compare internal vs Alpaca positions."""
    supabase = request.app.state.supabase

    from packages.quantum.brokers.alpaca_order_handler import reconcile_positions
    from packages.quantum.brokers.alpaca_client import get_alpaca_client

    alpaca = get_alpaca_client()
    if not alpaca:
        raise HTTPException(status_code=503, detail="Alpaca not configured")

    return reconcile_positions(alpaca, supabase, user_id)


# ── Approvals (micro-live) ───────────────────────────────────────────

@router.get("/approvals")
async def broker_approvals(request: Request, user_id: str = Depends(get_current_user)):
    """Pending approval queue."""
    supabase = request.app.state.supabase

    res = supabase.table("live_approval_queue") \
        .select("*") \
        .eq("user_id", user_id) \
        .eq("status", "pending") \
        .order("created_at", desc=True) \
        .limit(20) \
        .execute()

    return {"approvals": res.data or []}


@router.post("/approvals/{approval_id}/approve")
async def broker_approve(request: Request, approval_id: str, user_id: str = Depends(get_current_user)):
    """Approve a pending live order."""
    supabase = request.app.state.supabase
    alpaca = _get_alpaca()

    from packages.quantum.brokers.safety_checks import approve_order
    return approve_order(supabase, alpaca, approval_id, user_id)


@router.post("/approvals/{approval_id}/reject")
async def broker_reject(
    request: Request,
    approval_id: str,
    reason: str = Body(..., embed=True),
    user_id: str = Depends(get_current_user),
):
    """Reject a pending live order."""
    supabase = request.app.state.supabase

    from packages.quantum.brokers.safety_checks import reject_order
    return reject_order(supabase, approval_id, user_id, reason)


# ── Mode ──────────────────────────────────────────────────────────────

@router.get("/mode")
async def broker_mode(user_id: str = Depends(get_current_user)):
    """Current execution mode."""
    from packages.quantum.brokers.execution_router import get_execution_mode
    mode = get_execution_mode()
    return {
        "execution_mode": mode.value,
        "description": {
            "internal_paper": "Internal TCM simulation (no broker calls)",
            "alpaca_paper": "Alpaca paper trading API",
            "alpaca_live": "Real money via Alpaca",
            "shadow": "Log only, no execution",
        }.get(mode.value, "Unknown"),
    }
