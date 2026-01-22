from typing import Dict, List, Optional, Any
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from supabase import Client
from postgrest.exceptions import APIError
from pydantic import ValidationError, BaseModel
from datetime import datetime, timedelta, timezone
import traceback
import json
import logging

from packages.quantum.security import get_current_user, get_supabase_user_client
from packages.quantum.services.journal_service import JournalService
from packages.quantum.services.cash_service import CashService
from packages.quantum.analytics.progress_engine import ProgressEngine, get_week_id_for_last_full_week
from packages.quantum.models import RiskDashboardResponse, PortfolioSnapshot, TradeTicket
from packages.quantum.inbox.ranker import rank_suggestions
from packages.quantum.market_data import PolygonService
from packages.quantum.execution.transaction_cost_model import TransactionCostModel

logger = logging.getLogger(__name__)

# Table names
TRADE_SUGGESTIONS_TABLE = "trade_suggestions"
WEEKLY_REPORTS_TABLE = "weekly_trade_reports"

router = APIRouter()

# --- Inbox v3.0 Endpoints ---

class DismissSuggestionRequest(BaseModel):
    reason: str

# PR4: Active statuses include both pending and NOT_EXECUTABLE (blocked by quality gate)
# NOT_EXECUTABLE suggestions should appear in the queue so users can see/manage them.
ACTIVE_STATUSES = ["pending", "NOT_EXECUTABLE"]


def compute_today_window(now: Optional[datetime] = None) -> tuple:
    """
    PR4.1: Compute explicit today window bounds for deterministic queries.

    Returns:
        (today_start_iso, tomorrow_start_iso): Both as ISO strings for Postgrest queries.

    The window is [today_start, tomorrow_start) - inclusive start, exclusive end.
    This ensures "today" is strictly bounded to a single calendar day UTC.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)

    return today_start.isoformat(), tomorrow_start.isoformat()


@router.get("/inbox")
async def get_inbox(
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_user_client),
    include_backlog: bool = Query(False, description="Include older active items beyond today")
):
    """
    Returns the Inbox State with explicit bucketing for UI truthfulness:

    New buckets (v4):
    - active_executable: Pending suggestions that can be staged
    - active_blocked: NOT_EXECUTABLE suggestions (blocked by quality gate)
    - staged_today: Suggestions staged today (for paper trading)
    - completed_today: Dismissed/superseded suggestions today

    Legacy fields (backwards compat):
    - hero: Top ranked active suggestion
    - queue: Remaining active suggestions (derived from active_executable)
    - completed: Today's non-active suggestions (derived from completed_today)

    meta: { total_ev_available, deployable_capital, stale_after_seconds, include_backlog }

    PR4: NOT_EXECUTABLE suggestions appear in active_blocked for visibility.
    v4-Inbox: Staged items are now explicitly separated from completed.
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Database Unavailable")

    try:
        # Compute explicit today window bounds
        today_start, tomorrow_start = compute_today_window()

        # Fetch Active suggestions (pending or NOT_EXECUTABLE)
        active_query = supabase.table(TRADE_SUGGESTIONS_TABLE) \
            .select("*") \
            .eq("user_id", user_id) \
            .in_("status", ACTIVE_STATUSES)

        if not include_backlog:
            active_query = active_query \
                .gte("created_at", today_start) \
                .lt("created_at", tomorrow_start)

        active_res = active_query.execute()
        active_list = active_res.data or []

        # Fetch staged suggestions (today only)
        staged_res = supabase.table(TRADE_SUGGESTIONS_TABLE) \
            .select("*") \
            .eq("user_id", user_id) \
            .eq("status", "staged") \
            .gte("created_at", today_start) \
            .lt("created_at", tomorrow_start) \
            .execute()
        staged_list = staged_res.data or []

        # Fetch all today's suggestions for completed bucket
        today_res = supabase.table(TRADE_SUGGESTIONS_TABLE) \
            .select("*") \
            .eq("user_id", user_id) \
            .gte("created_at", today_start) \
            .lt("created_at", tomorrow_start) \
            .execute()
        today_list = today_res.data or []

        # v4: Explicit bucketing
        # completed_today = dismissed/superseded/executed (NOT staged, NOT active)
        non_completed_statuses = set(ACTIVE_STATUSES + ["staged"])
        completed_list = [
            s for s in today_list
            if s.get("status") not in non_completed_statuses
        ]

        # Split active into executable vs blocked
        active_executable = [s for s in active_list if s.get("status") == "pending"]
        active_blocked = [s for s in active_list if s.get("status") == "NOT_EXECUTABLE"]

        # Rank Active suggestions (all active for hero selection)
        ranked_active = rank_suggestions(active_list)

        # Split Hero vs Queue (for legacy compat)
        hero = ranked_active[0] if ranked_active else None
        queue = ranked_active[1:] if len(ranked_active) > 1 else []

        # Compute Meta - total_ev_available only for executable suggestions
        total_ev = sum(s.get("ev", 0) for s in active_executable if s.get("ev"))

        # v4: Use CashService for deployable_capital (accurate calculation)
        deployable_capital = 0.0
        try:
            cash_service = CashService(supabase)
            # CashService.get_deployable_capital is async, but we can call it synchronously
            # by using a sync wrapper or just accessing it directly since Supabase-py is sync
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If already in async context, create task
                deployable_capital = await cash_service.get_deployable_capital(user_id)
            else:
                deployable_capital = loop.run_until_complete(
                    cash_service.get_deployable_capital(user_id)
                )
        except Exception as e:
            # Safe fallback: log warning and return 0
            logger.warning(f"CashService.get_deployable_capital failed for user {user_id}: {e}")
            deployable_capital = 0.0

        return {
            # v4: New explicit buckets
            "active_executable": active_executable,
            "active_blocked": active_blocked,
            "staged_today": staged_list,
            "completed_today": completed_list,
            # Legacy fields (backwards compat)
            "hero": hero,
            "queue": queue,
            "completed": completed_list,  # Legacy: maps to completed_today
            "meta": {
                "total_ev_available": total_ev,
                "deployable_capital": deployable_capital,
                "stale_after_seconds": 300,
                "include_backlog": include_backlog
            }
        }
    except Exception as e:
        logger.error(f"Inbox Error: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to fetch inbox")

@router.post("/suggestions/{suggestion_id}/dismiss")
async def dismiss_suggestion(
    suggestion_id: str,
    body: DismissSuggestionRequest,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_user_client)
):
    if not supabase:
        raise HTTPException(status_code=503, detail="Database Unavailable")

    # VALIDATION: Allowed reasons
    valid_reasons = {"too_risky", "bad_price", "wrong_timing"}
    if body.reason not in valid_reasons:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid reason. Must be one of: {', '.join(valid_reasons)}"
        )

    try:
        # Fetch existing to merge sizing_metadata
        res = supabase.table(TRADE_SUGGESTIONS_TABLE).select("*").eq("id", suggestion_id).single().execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="Suggestion not found")

        suggestion = res.data
        if suggestion["user_id"] != user_id:
            raise HTTPException(status_code=403, detail="Unauthorized")

        # If already dismissed, return existing record (Do NOT overwrite)
        if suggestion.get("status") == "dismissed":
            return suggestion

        # Update logic
        sizing_metadata = suggestion.get("sizing_metadata") or {}
        sizing_metadata["dismiss"] = {
            "reason": body.reason,
            "dismissed_at": datetime.now(timezone.utc).isoformat()
        }

        update_payload = {
            "status": "dismissed",
            "sizing_metadata": sizing_metadata
        }

        upd_res = supabase.table(TRADE_SUGGESTIONS_TABLE).update(update_payload).eq("id", suggestion_id).execute()

        if upd_res.data:
            return upd_res.data[0]
        else:
            raise HTTPException(status_code=500, detail="Failed to update suggestion")

    except APIError as e:
        raise HTTPException(status_code=500, detail=f"Database Error: {e}")
    except HTTPException:
        raise
    except Exception as e:
        print(f"Dismiss Error: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

@router.post("/suggestions/{suggestion_id}/refresh-quote")
async def refresh_quote(
    suggestion_id: str,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_user_client)
):
    if not supabase:
        raise HTTPException(status_code=503, detail="Database Unavailable")

    try:
        # Fetch suggestion
        res = supabase.table(TRADE_SUGGESTIONS_TABLE).select("*").eq("id", suggestion_id).single().execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="Suggestion not found")

        suggestion = res.data

        # Enforce ownership
        if suggestion["user_id"] != user_id:
            raise HTTPException(status_code=403, detail="Unauthorized")

        # Symbol resolution (symbol OR ticker)
        symbol = suggestion.get("symbol") or suggestion.get("ticker")
        if not symbol:
            raise HTTPException(status_code=422, detail="Suggestion missing symbol or ticker")

        # Get fresh quote
        poly = PolygonService()
        try:
            quote = poly.get_recent_quote(symbol)
        except Exception as e:
            # Per edge case instructions: 502 with clear message
            print(f"Quote refresh failed for {symbol}: {e}")
            # SECURITY: Do not return detailed error message (may contain API key in URL)
            raise HTTPException(status_code=502, detail="Quote provider error")

        # Calculate TCM Estimate
        tcm_est = None
        try:
            # Best effort ticket reconstruction
            order_json = suggestion.get("order_json") or {}

            # Helper to map suggestion to ticket
            legs = order_json.get("legs", [])
            # ensure valid legs structure

            ticket = TradeTicket(
                symbol=symbol,
                strategy_type=suggestion.get("strategy"),
                legs=legs,
                quantity=order_json.get("quantity", 1),
                limit_price=order_json.get("limit_price"),
                order_type=order_json.get("order_type", "limit")
            )

            tcm_est = TransactionCostModel.estimate(ticket, quote)
        except Exception as e:
            print(f"TCM Estimate failed: {e}")
            # TCM failure is not critical enough to fail the whole request, but prompt said "Quote/TCM failures: HTTP 502"
            # However, typically quote failure is critical, TCM is supplementary.
            # "Quote/TCM failures" implies either. Let's be strict.
            raise HTTPException(status_code=502, detail="TCM calculation error")

        return {
            "suggestion_id": suggestion_id,
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
            "quote": quote,
            "tcm_estimate": tcm_est
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"Refresh Quote Error: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Internal Server Error")

# --- Existing Endpoints (Preserved) ---

@router.get("/journal/stats")
async def get_journal_stats(
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_user_client)
):
    """
    Returns aggregated journal stats (win rate, total pnl, recent activity).
    Wraps JournalService.get_journal_stats.
    """
    if not supabase:
        # Fallback empty structure if DB not available (though dependency usually raises 500)
        return {
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "trade_count": 0,
            "recent_trades": []
        }

    service = JournalService(supabase)
    return service.get_journal_stats(user_id)

@router.get("/risk/dashboard", response_model=RiskDashboardResponse)
async def get_risk_dashboard(
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_user_client)
):
    """
    Returns risk dashboard metrics.
    Currently returns a safe shell to prevent 404s/500s.
    """
    default_response = RiskDashboardResponse(
        summary={"status": "ok", "message": "No risk data available yet"},
        exposure={"long_exposure": 0.0, "short_exposure": 0.0, "net_exposure": 0.0},
        greeks={"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    )

    if not supabase:
        return default_response

    # Future: fetch real risk aggregation logic
    return default_response

@router.get("/portfolio/snapshot", response_model=PortfolioSnapshot)
async def get_portfolio_snapshot(
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_user_client)
):
    """
    Returns the latest portfolio snapshot.
    Returns safe default if none exists.
    """
    empty_snapshot = PortfolioSnapshot(
        user_id=user_id,
        created_at=datetime.now(),
        snapshot_type="empty",
        holdings=[],
        spreads=[],
        risk_metrics={}
    )

    if not supabase:
        return empty_snapshot

    try:
        # Try to fetch latest snapshot
        res = supabase.table("portfolio_snapshots") \
            .select("*") \
            .eq("user_id", user_id) \
            .order("created_at", desc=True) \
            .limit(1) \
            .execute()

        if res.data and len(res.data) > 0:
            raw_data = res.data[0]
            # Need to convert dictionary to Pydantic model
            try:
                # Ensure holdings is populated if missing but positions exists
                if "holdings" not in raw_data or not raw_data["holdings"]:
                    if "positions" in raw_data and raw_data["positions"]:
                         raw_data["holdings"] = raw_data["positions"]
                    else:
                         raw_data["holdings"] = []

                # Ensure risk_metrics is at least an empty dict
                if "risk_metrics" not in raw_data or raw_data["risk_metrics"] is None:
                    raw_data["risk_metrics"] = {}

                return PortfolioSnapshot(**raw_data)
            except ValidationError as e:
                # Fallback: Construct a minimal valid snapshot from raw data instead of failing silently
                print(f"⚠️ Snapshot Parse Error (recovering): {e}")

                # Recover holdings
                holdings = raw_data.get("holdings")
                if not isinstance(holdings, list):
                     holdings = raw_data.get("positions")

                if not isinstance(holdings, list):
                     holdings = []

                return PortfolioSnapshot(
                    id=raw_data.get("id"),
                    user_id=user_id,
                    created_at=raw_data.get("created_at", datetime.now()),
                    snapshot_type="recovery", # Mark as recovered
                    holdings=holdings,
                    spreads=raw_data.get("spreads") or [],
                    risk_metrics=raw_data.get("risk_metrics") or {},
                    buying_power=raw_data.get("buying_power")
                )

        return empty_snapshot
    except Exception as e:
        print(f"❌ Error fetching snapshot: {e}")
        # If table doesn't exist or other error, return empty
        return empty_snapshot

@router.get("/rebalance/suggestions")
async def get_rebalance_suggestions(
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_user_client)
):
    """
    Returns pending rebalance suggestions.
    """
    if not supabase:
        return {"suggestions": []}

    # We can reuse generic suggestions endpoint logic but filter for rebalance window
    # or just return empty for now as requested by prompt
    try:
        query = supabase.table(TRADE_SUGGESTIONS_TABLE).select("*").eq("user_id", user_id).eq("window", "rebalance")
        res = query.order("created_at", desc=True).limit(50).execute()
        return {"suggestions": res.data or []}
    except Exception:
        return {"suggestions": []}


@router.get("/journal/drift-summary")
async def get_drift_summary(
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_user_client)
):
    """
    Returns execution discipline summary.
    Tries pre-computed view 'discipline_score_per_user' first.
    Falls back to aggregating 'execution_drift_logs'.
    """
    default_response = {
        "window_days": 30,
        "total_suggestions": 0,
        "disciplined_execution": 0,
        "impulse_trades": 0,
        "size_violations": 0,
        "disciplined_rate": 0.0,
        "impulse_rate": 0.0,
        "size_violation_rate": 0.0
    }

    if not supabase:
        return default_response

    # 1. Try View
    try:
        res = supabase.table("discipline_score_per_user").select("*").eq("user_id", user_id).single().execute()
        data = res.data
        if data:
            # Check if data already matches the frontend shape
            if "total_suggestions" in data:
                return data

            # Normalize logic
            disc = data.get("disciplined_count", 0)
            impulse = data.get("impulse_count", 0)
            size = data.get("size_violation_count", 0)
            total = disc + impulse + size

            return {
                "window_days": 30,
                "total_suggestions": total,
                "disciplined_execution": disc,
                "impulse_trades": impulse,
                "size_violations": size,
                "disciplined_rate": data.get("discipline_score", 0.0),
                "impulse_rate": impulse / total if total > 0 else 0.0,
                "size_violation_rate": size / total if total > 0 else 0.0
            }
    except Exception:
        # View might not exist or return 406 if no rows found by .single()
        pass

    # 2. Fallback: Aggregate logs manually
    try:
        cutoff = (datetime.now() - timedelta(days=30)).isoformat()
        res = supabase.table("execution_drift_logs") \
            .select("*") \
            .eq("user_id", user_id) \
            .gte("created_at", cutoff) \
            .execute()

        logs = res.data or []
        if not logs:
            return default_response

        total = len(logs)
        # Assuming discipline_tag in ['disciplined_execution', 'impulse_trade', 'size_violation']
        disc_count = sum(1 for x in logs if x.get("discipline_tag") == "disciplined_execution")
        impulse_count = sum(1 for x in logs if x.get("discipline_tag") == "impulse_trade")
        size_count = sum(1 for x in logs if x.get("discipline_tag") == "size_violation")

        return {
            "window_days": 30,
            "total_suggestions": total,
            "disciplined_execution": disc_count,
            "impulse_trades": impulse_count,
            "size_violations": size_count,
            "disciplined_rate": disc_count / total if total > 0 else 0.0,
            "impulse_rate": impulse_count / total if total > 0 else 0.0,
            "size_violation_rate": size_count / total if total > 0 else 0.0
        }

    except Exception as e:
        print(f"Error computing drift summary fallback: {e}")
        return default_response

@router.get("/progress/weekly")
async def get_weekly_progress(
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_user_client)
):
    """
    Returns the weekly snapshot for the last full week.
    """
    week_id = get_week_id_for_last_full_week()

    if not supabase:
         raise HTTPException(status_code=503, detail="Database Context Unavailable")

    try:
        res = supabase.table("weekly_snapshots") \
            .select("*") \
            .eq("user_id", user_id) \
            .eq("week_id", week_id) \
            .limit(1) \
            .execute()

        if res.data and len(res.data) > 0:
            return res.data[0]
        else:
            # Return stable "empty" response instead of 404/500
            return {
                "id": None,
                "user_id": user_id,
                "week_id": week_id,
                "date_start": None,
                "date_end": None,
                "status": "empty",
                "message": f"No snapshot yet for week {week_id}",
                "user_metrics": {"overall_score": 0, "components": {}},
                "system_metrics": {"overall_quality": 0, "components": {}},
                "synthesis": None
            }

    except APIError as e:
        # Handle Supabase API Errors (e.g. Invalid API Key, RLS policy)
        print(f"Supabase API Error in weekly progress: {e}")
        raise HTTPException(status_code=502, detail={
            "error": "Upstream API Error",
            "message": str(e),
            "hint": "Check SUPABASE_URL and Keys"
        })
    except ValidationError as e:
        # Handle Pydantic Validation Errors (often from malformed Supabase responses)
        print(f"Validation Error in weekly progress: {e}")
        raise HTTPException(status_code=502, detail="Invalid Data from Upstream")
    except Exception as e:
        print(f"Error fetching weekly progress: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Internal Server Error")

@router.get("/suggestions")
async def get_suggestions(
    window: Optional[str] = None,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_user_client)
):
    """
    Returns trade suggestions.
    """
    if not supabase:
        return {"suggestions": []}

    try:
        query = supabase.table(TRADE_SUGGESTIONS_TABLE).select("*").eq("user_id", user_id)
        if window:
            query = query.eq("window", window)

        res = query.order("created_at", desc=True).limit(50).execute()
        return {"suggestions": res.data or []}
    except Exception as e:
        print(f"Error fetching suggestions: {e}")
        return {"suggestions": []}

@router.get("/weekly-reports")
async def get_weekly_reports(
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_user_client)
):
    """
    Returns list of weekly trade reports.
    """
    if not supabase:
        return {"reports": []}

    try:
        res = supabase.table(WEEKLY_REPORTS_TABLE) \
            .select("*") \
            .eq("user_id", user_id) \
            .order("week_ending", desc=True) \
            .limit(20) \
            .execute()
        return {"reports": res.data or []}
    except Exception as e:
        print(f"Error fetching weekly reports: {e}")
        return {"reports": []}
