"""
Policy Lab API endpoints — view cohorts, results, promotions, and manage config.
"""

import os
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, Body, HTTPException, Request
from packages.quantum.security import get_current_user

from packages.quantum.policy_lab.config import (
    PolicyConfig,
    load_cohort_configs,
    is_policy_lab_enabled,
)
from packages.quantum.policy_lab.evaluator import evaluate_cohorts, check_promotion

router = APIRouter(prefix="/policy-lab", tags=["policy-lab"])


def _require_enabled():
    if not is_policy_lab_enabled():
        raise HTTPException(status_code=404, detail="Policy Lab is not enabled")


@router.get("/cohorts")
async def list_cohorts(request: Request, user_id: str = Depends(get_current_user)):
    """List active cohorts with current config."""
    _require_enabled()
    supabase = request.app.state.supabase

    res = supabase.table("policy_lab_cohorts") \
        .select("id, cohort_name, portfolio_id, policy_config, is_active, promoted_at, created_at") \
        .eq("user_id", user_id) \
        .eq("is_active", True) \
        .execute()

    return {"cohorts": res.data or []}


@router.get("/results")
async def get_results(
    request: Request,
    user_id: str = Depends(get_current_user),
    days: int = Query(default=7, ge=1, le=90),
):
    """Daily results comparison table."""
    _require_enabled()
    supabase = request.app.state.supabase

    # Get cohort IDs for this user
    cohorts_res = supabase.table("policy_lab_cohorts") \
        .select("id, cohort_name") \
        .eq("user_id", user_id) \
        .eq("is_active", True) \
        .execute()
    cohorts = cohorts_res.data or []
    if not cohorts:
        return {"results": [], "cohorts": []}

    cohort_ids = [c["id"] for c in cohorts]
    since = (date.today() - timedelta(days=days)).isoformat()

    results_res = supabase.table("policy_lab_daily_results") \
        .select("*") \
        .in_("cohort_id", cohort_ids) \
        .gte("eval_date", since) \
        .order("eval_date", desc=True) \
        .execute()

    return {
        "cohorts": cohorts,
        "results": results_res.data or [],
    }


@router.get("/promotions")
async def get_promotions(request: Request, user_id: str = Depends(get_current_user)):
    """Promotion history."""
    _require_enabled()
    supabase = request.app.state.supabase

    res = supabase.table("policy_lab_promotions") \
        .select("*") \
        .eq("user_id", user_id) \
        .order("created_at", desc=True) \
        .limit(20) \
        .execute()

    return {"promotions": res.data or []}


@router.post("/promote")
async def promote_cohort(
    request: Request,
    cohort_name: str = Body(..., embed=True),
    user_id: str = Depends(get_current_user),
):
    """Manually promote a cohort's policy."""
    _require_enabled()
    supabase = request.app.state.supabase

    # Find the cohort
    res = supabase.table("policy_lab_cohorts") \
        .select("id, policy_config") \
        .eq("user_id", user_id) \
        .eq("cohort_name", cohort_name) \
        .eq("is_active", True) \
        .single() \
        .execute()

    if not res.data:
        raise HTTPException(status_code=404, detail=f"Cohort '{cohort_name}' not found")

    # Record promotion
    supabase.table("policy_lab_promotions").insert({
        "user_id": user_id,
        "promoted_cohort": cohort_name,
        "reason": "Manual promotion",
        "auto_promoted": False,
        "confirmed_by": "user",
    }).execute()

    # Mark as promoted
    supabase.table("policy_lab_cohorts") \
        .update({"promoted_at": date.today().isoformat()}) \
        .eq("id", res.data["id"]) \
        .execute()

    return {"status": "promoted", "cohort": cohort_name}


@router.post("/cohorts/{cohort_name}/config")
async def update_cohort_config(
    request: Request,
    cohort_name: str,
    config: dict = Body(...),
    user_id: str = Depends(get_current_user),
):
    """Update a cohort's policy config."""
    _require_enabled()
    supabase = request.app.state.supabase

    # Validate config fields
    try:
        PolicyConfig.from_dict(config)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid config: {e}")

    res = supabase.table("policy_lab_cohorts") \
        .select("id, policy_config") \
        .eq("user_id", user_id) \
        .eq("cohort_name", cohort_name) \
        .single() \
        .execute()

    if not res.data:
        raise HTTPException(status_code=404, detail=f"Cohort '{cohort_name}' not found")

    # Merge with existing config
    existing = res.data.get("policy_config") or {}
    existing.update(config)

    supabase.table("policy_lab_cohorts") \
        .update({"policy_config": existing}) \
        .eq("id", res.data["id"]) \
        .execute()

    return {"status": "updated", "cohort": cohort_name, "config": existing}


@router.post("/init")
async def init_policy_lab(request: Request, user_id: str = Depends(get_current_user)):
    """
    One-time initialization: create cohort portfolios and config rows.
    Idempotent — safe to call multiple times.
    """
    _require_enabled()
    supabase = request.app.state.supabase

    from packages.quantum.policy_lab.init_lab import initialize_policy_lab
    result = initialize_policy_lab(user_id, supabase)
    return result
