from typing import Dict, List, Optional, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from supabase import Client
from datetime import datetime, timedelta

from packages.quantum.security import get_current_user, get_supabase_user_client
from packages.quantum.services.journal_service import JournalService
from packages.quantum.analytics.progress_engine import ProgressEngine, get_week_id_for_last_full_week

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
         raise HTTPException(status_code=404, detail="No database connection")

    try:
        res = supabase.table("weekly_snapshots") \
            .select("*") \
            .eq("user_id", user_id) \
            .eq("week_id", week_id) \
            .single() \
            .execute()

        if res.data:
            return res.data
        else:
             # UI expects 404 behavior for "no data yet" based on catch block analysis
             # or simply empty. The UI component throws 404 in fetchWithAuth usually.
             raise HTTPException(status_code=404, detail=f"No snapshot found for week {week_id}")

    except Exception as e:
        # If .single() fails (e.g. returns nothing), or table missing
        raise HTTPException(status_code=404, detail=f"No snapshot found for week {week_id}")

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
