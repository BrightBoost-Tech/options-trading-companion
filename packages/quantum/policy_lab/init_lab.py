"""
Policy Lab initialization — one-time setup of cohort portfolios and config.
"""

import logging
from typing import Dict, Any

from packages.quantum.policy_lab.config import DEFAULT_CONFIGS

logger = logging.getLogger(__name__)

INITIAL_CAPITAL = 100_000.0


def initialize_policy_lab(
    user_id: str,
    supabase,
    existing_portfolio_id: str = None,
) -> Dict[str, Any]:
    """
    One-time setup: create cohort portfolios and policy_lab_cohorts rows.

    - Creates 2 new paper_portfolios (conservative, neutral)
    - Maps existing portfolio to aggressive cohort
    - Creates 3 policy_lab_cohorts rows with default configs
    - Idempotent: skips cohorts that already exist

    Args:
        user_id: Target user
        supabase: Admin Supabase client
        existing_portfolio_id: Existing portfolio to assign as aggressive.
            If None, uses the user's first portfolio.

    Returns:
        Dict with created cohort details.
    """
    # Find existing portfolio
    if not existing_portfolio_id:
        port_res = supabase.table("paper_portfolios") \
            .select("id") \
            .eq("user_id", user_id) \
            .order("created_at", desc=False) \
            .limit(1) \
            .execute()
        if port_res.data:
            existing_portfolio_id = port_res.data[0]["id"]

    if not existing_portfolio_id:
        return {"status": "error", "reason": "No existing portfolio found for user"}

    # Check for existing cohorts (idempotent)
    existing_res = supabase.table("policy_lab_cohorts") \
        .select("cohort_name") \
        .eq("user_id", user_id) \
        .execute()
    existing_names = {r["cohort_name"] for r in (existing_res.data or [])}

    created = {}

    for cohort_name, config in DEFAULT_CONFIGS.items():
        if cohort_name in existing_names:
            logger.info(f"policy_lab_init: cohort={cohort_name} already exists, skipping")
            created[cohort_name] = {"status": "exists"}
            continue

        # Determine portfolio ID
        if cohort_name == "aggressive":
            portfolio_id = existing_portfolio_id
        else:
            # Create new portfolio
            port = supabase.table("paper_portfolios").insert({
                "user_id": user_id,
                "name": f"Policy Lab — {cohort_name.title()}",
                "cash_balance": INITIAL_CAPITAL,
                "net_liq": INITIAL_CAPITAL,
            }).execute()
            portfolio_id = port.data[0]["id"]

        # Create cohort row
        supabase.table("policy_lab_cohorts").insert({
            "user_id": user_id,
            "cohort_name": cohort_name,
            "portfolio_id": portfolio_id,
            "policy_config": config.to_dict(),
        }).execute()

        created[cohort_name] = {
            "status": "created",
            "portfolio_id": portfolio_id,
        }
        logger.info(f"policy_lab_init: cohort={cohort_name} portfolio={portfolio_id}")

    return {"status": "ok", "cohorts": created}
