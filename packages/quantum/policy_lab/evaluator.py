"""
Daily cohort evaluator — compares performance across Policy Lab cohorts
and checks promotion eligibility.
"""

import logging
import os
from datetime import date, timedelta
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

PROMOTION_WINDOW = int(os.environ.get("POLICY_LAB_PROMOTION_WINDOW", "5"))
AUTO_PROMOTE = os.environ.get("POLICY_LAB_AUTO_PROMOTE", "").lower() in ("1", "true")


def evaluate_cohorts(
    user_id: str,
    eval_date: date,
    supabase,
) -> Dict[str, Any]:
    """
    Compute daily performance metrics for each active cohort and upsert
    into policy_lab_daily_results.

    Returns comparison summary dict.
    """
    # Fetch active cohorts
    cohorts_res = supabase.table("policy_lab_cohorts") \
        .select("id, cohort_name, portfolio_id, policy_config") \
        .eq("user_id", user_id) \
        .eq("is_active", True) \
        .execute()
    cohorts = cohorts_res.data or []

    if not cohorts:
        return {"status": "no_cohorts", "results": []}

    eval_date_str = eval_date.isoformat()
    results = []

    for cohort in cohorts:
        cohort_id = cohort["id"]
        portfolio_id = cohort["portfolio_id"]
        cohort_name = cohort["cohort_name"]

        try:
            metrics = _compute_cohort_metrics(
                supabase, portfolio_id, eval_date_str,
            )

            # Upsert daily result
            row = {
                "cohort_id": cohort_id,
                "eval_date": eval_date_str,
                **metrics,
            }
            supabase.table("policy_lab_daily_results") \
                .upsert(row, on_conflict="cohort_id,eval_date") \
                .execute()

            results.append({
                "cohort_name": cohort_name,
                "cohort_id": cohort_id,
                **metrics,
            })

            logger.info(
                f"policy_lab_eval: cohort={cohort_name} date={eval_date_str} "
                f"realized={metrics['realized_pl']:.2f} unrealized={metrics['unrealized_pl']:.2f} "
                f"total={metrics['total_pl']:.2f} win_rate={metrics.get('win_rate')}"
            )

        except Exception as e:
            logger.error(f"policy_lab_eval_error: cohort={cohort_name} error={e}")
            results.append({"cohort_name": cohort_name, "error": str(e)})

    return {"status": "ok", "eval_date": eval_date_str, "results": results}


def _compute_cohort_metrics(
    supabase,
    portfolio_id: str,
    eval_date_str: str,
) -> Dict[str, Any]:
    """Compute performance metrics for a single cohort portfolio on a given date."""

    # Positions closed today
    closed_res = supabase.table("paper_positions") \
        .select("realized_pl") \
        .eq("portfolio_id", portfolio_id) \
        .eq("status", "closed") \
        .gte("closed_at", f"{eval_date_str}T00:00:00") \
        .lt("closed_at", f"{eval_date_str}T23:59:59.999") \
        .execute()
    closed = closed_res.data or []

    realized_pls = [float(p.get("realized_pl") or 0) for p in closed]
    realized_pl = sum(realized_pls)
    positions_closed = len(closed)
    wins = sum(1 for pl in realized_pls if pl > 0)
    win_rate = (wins / positions_closed) if positions_closed > 0 else None

    # Open positions (unrealized P&L)
    open_res = supabase.table("paper_positions") \
        .select("unrealized_pl") \
        .eq("portfolio_id", portfolio_id) \
        .eq("status", "open") \
        .neq("quantity", 0) \
        .execute()
    open_positions = open_res.data or []
    unrealized_pl = sum(float(p.get("unrealized_pl") or 0) for p in open_positions)

    # Positions opened today
    opened_res = supabase.table("paper_positions") \
        .select("id", count="exact") \
        .eq("portfolio_id", portfolio_id) \
        .gte("created_at", f"{eval_date_str}T00:00:00") \
        .lt("created_at", f"{eval_date_str}T23:59:59.999") \
        .execute()
    positions_opened = opened_res.count or 0

    # Portfolio capital for budget utilization
    port_res = supabase.table("paper_portfolios") \
        .select("cash_balance, net_liq") \
        .eq("id", portfolio_id) \
        .single() \
        .execute()
    portfolio = port_res.data or {}
    net_liq = float(portfolio.get("net_liq") or portfolio.get("cash_balance") or 100000)
    cash = float(portfolio.get("cash_balance") or 0)
    capital_deployed = max(0, net_liq - cash)

    total_pl = realized_pl + unrealized_pl

    return {
        "positions_opened": positions_opened,
        "positions_closed": positions_closed,
        "realized_pl": round(realized_pl, 2),
        "unrealized_pl": round(unrealized_pl, 2),
        "total_pl": round(total_pl, 2),
        "win_rate": round(win_rate, 4) if win_rate is not None else None,
        "capital_deployed": round(capital_deployed, 2),
        "risk_budget_used": round(capital_deployed / net_liq, 4) if net_liq > 0 else 0,
    }


def check_promotion(
    user_id: str,
    supabase,
) -> Dict[str, Any]:
    """
    Check if any cohort qualifies for promotion.

    A cohort must rank #1 on total_pl AND win_rate for PROMOTION_WINDOW
    consecutive days to be promoted.

    Returns promotion decision dict.
    """
    cohorts_res = supabase.table("policy_lab_cohorts") \
        .select("id, cohort_name") \
        .eq("user_id", user_id) \
        .eq("is_active", True) \
        .execute()
    cohorts = cohorts_res.data or []

    if len(cohorts) < 2:
        return {"status": "insufficient_cohorts"}

    # Fetch last N days of results
    window_start = (date.today() - timedelta(days=PROMOTION_WINDOW)).isoformat()
    cohort_ids = [c["id"] for c in cohorts]
    id_to_name = {c["id"]: c["cohort_name"] for c in cohorts}

    results_res = supabase.table("policy_lab_daily_results") \
        .select("cohort_id, eval_date, total_pl, win_rate") \
        .in_("cohort_id", cohort_ids) \
        .gte("eval_date", window_start) \
        .order("eval_date", desc=True) \
        .execute()
    rows = results_res.data or []

    if not rows:
        return {"status": "no_results"}

    # Group by date and find daily winner
    from collections import defaultdict
    by_date: Dict[str, List[Dict]] = defaultdict(list)
    for r in rows:
        by_date[r["eval_date"]].append(r)

    # Count consecutive days each cohort was #1 on total_pl
    sorted_dates = sorted(by_date.keys(), reverse=True)
    streak: Dict[str, int] = {c["id"]: 0 for c in cohorts}
    leader_id = None

    for d in sorted_dates[:PROMOTION_WINDOW]:
        day_rows = by_date[d]
        if not day_rows:
            break
        # Rank by total_pl
        best = max(day_rows, key=lambda r: float(r.get("total_pl") or 0))
        best_id = best["cohort_id"]

        if leader_id is None:
            leader_id = best_id
        if best_id == leader_id:
            streak[best_id] = streak.get(best_id, 0) + 1
        else:
            break  # Streak broken

    # Check if any cohort has a full-window streak
    winner_id = None
    for cid, count in streak.items():
        if count >= PROMOTION_WINDOW:
            winner_id = cid
            break

    if not winner_id:
        return {
            "status": "no_consensus",
            "streaks": {id_to_name.get(cid, cid): cnt for cid, cnt in streak.items()},
            "window": PROMOTION_WINDOW,
        }

    winner_name = id_to_name.get(winner_id, "unknown")

    # Build metrics snapshot
    metrics_snapshot = {
        "streaks": {id_to_name.get(cid, cid): cnt for cid, cnt in streak.items()},
        "window": PROMOTION_WINDOW,
        "latest_results": rows[:len(cohorts)],
    }

    promotion_row = {
        "user_id": user_id,
        "promoted_cohort": winner_name,
        "reason": f"Ranked #1 on total_pl for {PROMOTION_WINDOW} consecutive days",
        "metrics_snapshot": metrics_snapshot,
        "auto_promoted": AUTO_PROMOTE,
        "confirmed_by": "auto" if AUTO_PROMOTE else None,
    }

    supabase.table("policy_lab_promotions").insert(promotion_row).execute()

    if AUTO_PROMOTE:
        supabase.table("policy_lab_cohorts") \
            .update({"promoted_at": date.today().isoformat()}) \
            .eq("id", winner_id) \
            .execute()

    logger.info(
        f"policy_lab_promotion: user={user_id} winner={winner_name} "
        f"auto_promoted={AUTO_PROMOTE} streak={streak.get(winner_id, 0)}"
    )

    return {
        "status": "promoted" if AUTO_PROMOTE else "recommended",
        "winner": winner_name,
        "auto_promoted": AUTO_PROMOTE,
        "metrics_snapshot": metrics_snapshot,
    }
