from typing import Dict, List, Optional, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from supabase import Client
from postgrest.exceptions import APIError
from pydantic import ValidationError
from datetime import datetime, timedelta
import traceback

from packages.quantum.security import get_current_user, get_supabase_user_client
from packages.quantum.services.journal_service import JournalService
from packages.quantum.analytics.progress_engine import ProgressEngine, get_week_id_for_last_full_week
from packages.quantum.models import RiskDashboardResponse, PortfolioSnapshot

# Table names
TRADE_SUGGESTIONS_TABLE = "trade_suggestions"
WEEKLY_REPORTS_TABLE = "weekly_trade_reports"

router = APIRouter()

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
            # Need to convert dictionary to Pydantic model
            # Assuming data structure matches roughly
            return PortfolioSnapshot(**res.data[0])

        return empty_snapshot
    except Exception:
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
