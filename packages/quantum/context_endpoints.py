"""
Public /context endpoint for Task Ranker integration.

Returns app-level signals (win rate, open positions, guardrail violations)
to help external tools prioritize trading-related tasks.

Auth: None (public endpoint).
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request

router = APIRouter(tags=["context"])


@router.get("/context")
def get_context(request: Request):
    """
    Returns aggregate trading signals for Task Ranker.
    No auth required — all values are non-sensitive aggregates.
    """
    try:
        supabase = request.app.state.supabase

        # --- Rule violations this week ---
        # No rule_violations table exists yet; return 0.
        violations = 0

        # --- Win rate (last 30 days) ---
        thirty_days_ago = (
            datetime.now(timezone.utc) - timedelta(days=30)
        ).isoformat()

        win_rate = 0.0
        total_trades = 0
        winning_trades = 0
        try:
            total_res = (
                supabase.table("learning_trade_outcomes_v3")
                .select("id", count="exact")
                .not_.is_("pnl_realized", "null")
                .gte("closed_at", thirty_days_ago)
                .execute()
            )
            total_trades = total_res.count if hasattr(total_res, "count") and total_res.count is not None else 0

            if total_trades > 0:
                win_res = (
                    supabase.table("learning_trade_outcomes_v3")
                    .select("id", count="exact")
                    .gt("pnl_realized", 0)
                    .gte("closed_at", thirty_days_ago)
                    .execute()
                )
                winning_trades = win_res.count if hasattr(win_res, "count") and win_res.count is not None else 0
                win_rate = round(winning_trades / total_trades, 2)
        except Exception:
            # View may not exist yet; fall back to 0.
            pass

        # --- Open positions ---
        open_positions = 0
        try:
            open_res = (
                supabase.table("position_groups")
                .select("id", count="exact")
                .eq("status", "OPEN")
                .execute()
            )
            open_positions = open_res.count if hasattr(open_res, "count") and open_res.count is not None else 0
        except Exception:
            pass

        return {
            "app": "Options Trading Companion",
            "signals": [
                {
                    "type": "rule_violations",
                    "value": violations,
                    "label": f"{violations} guardrail violations this week",
                    "boost": 4,
                    "threshold_dir": "above",
                    "threshold": 0,
                },
                {
                    "type": "win_rate",
                    "value": float(win_rate),
                    "label": f"{int(win_rate * 100)}% win rate",
                    "boost": 2,
                    "threshold_dir": "below",
                    "threshold": 0.50,
                },
                {
                    "type": "open_positions",
                    "value": int(open_positions),
                    "label": f"{open_positions} open positions",
                    "boost": 1,
                    "threshold_dir": "above",
                    "threshold": 3,
                },
            ],
        }
    except Exception as e:
        return {
            "error": str(e),
            "app": "Options Trading Companion",
            "signals": [],
        }
