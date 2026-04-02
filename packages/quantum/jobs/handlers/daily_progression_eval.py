"""
Daily Progression Eval Job Handler

Runs once daily after market close (replaces validation_eval).

1. Queries paper_positions closed today → sums realized_pl
2. Calls progression_service.record_trading_day()
3. Logs result to job_runs
4. If promotion happens, it's recorded in go_live_progression_log
"""

import time
from datetime import datetime, timezone
from typing import Any, Dict

from packages.quantum.jobs.handlers.utils import get_admin_client, get_active_user_ids, run_async
from packages.quantum.jobs.handlers.exceptions import RetryableJobError, PermanentJobError

JOB_NAME = "daily_progression_eval"


def _chicago_today():
    """Get today's date in Chicago timezone."""
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("America/Chicago")).date()


def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """
    Evaluate each active user's trading day and update progression.
    """
    start_time = time.time()
    target_user_id = payload.get("user_id")

    try:
        client = get_admin_client()

        if target_user_id:
            active_users = [target_user_id]
        else:
            active_users = get_active_user_ids(client)

        today = _chicago_today()
        today_start = f"{today.isoformat()}T00:00:00-05:00"
        today_end = f"{today.isoformat()}T23:59:59-05:00"

        async def process_users():
            from packages.quantum.services.progression_service import ProgressionService
            svc = ProgressionService(client)

            results = []
            promotions = 0

            for uid in active_users:
                try:
                    # Sum realized PnL from Alpaca-routed positions closed today.
                    # Only count positions whose ENTRY order went through Alpaca
                    # (execution_mode='alpaca_paper' AND alpaca_order_id IS NOT NULL).
                    # Internal paper fills are excluded from green day calculation.
                    res = client.table("paper_positions") \
                        .select("id, realized_pl") \
                        .eq("user_id", uid) \
                        .eq("status", "closed") \
                        .gte("closed_at", today_start) \
                        .lte("closed_at", today_end) \
                        .execute()

                    all_closed = res.data or []

                    # Filter to Alpaca-only: check the entry order for each position
                    alpaca_positions = []
                    if all_closed:
                        pos_ids = [p["id"] for p in all_closed]
                        orders_res = client.table("paper_orders") \
                            .select("position_id, execution_mode, alpaca_order_id") \
                            .in_("position_id", pos_ids) \
                            .eq("execution_mode", "alpaca_paper") \
                            .not_.is_("alpaca_order_id", "null") \
                            .execute()
                        alpaca_pos_ids = {o["position_id"] for o in (orders_res.data or [])}
                        alpaca_positions = [p for p in all_closed if p["id"] in alpaca_pos_ids]

                    closed_positions = alpaca_positions
                    if not closed_positions:
                        results.append({
                            "user_id": uid[:8],
                            "status": "no_closes",
                            "realized_pnl": 0,
                        })
                        continue

                    realized_pnl = sum(
                        float(p.get("realized_pl") or 0) for p in closed_positions
                    )

                    # Record the day
                    result = svc.record_trading_day(uid, today, realized_pnl)
                    promoted = result.get("promoted", False)
                    if promoted:
                        promotions += 1

                    results.append({
                        "user_id": uid[:8],
                        "status": "green" if realized_pnl > 0 else "red",
                        "realized_pnl": round(realized_pnl, 2),
                        "alpaca_positions": len(closed_positions),
                        "total_closed": len(all_closed),
                        "internal_excluded": len(all_closed) - len(closed_positions),
                        "promoted": promoted,
                        "green_days": result["state"].get("alpaca_paper_green_days"),
                    })

                except Exception as e:
                    results.append({
                        "user_id": uid[:8],
                        "status": "error",
                        "error": str(e),
                    })

            return results, promotions

        user_results, total_promotions = run_async(process_users())

        return {
            "ok": True,
            "trade_date": today.isoformat(),
            "users_evaluated": len(user_results),
            "promotions": total_promotions,
            "timing_ms": (time.time() - start_time) * 1000,
            "results": user_results[:20],
        }

    except ValueError as e:
        raise PermanentJobError(f"Configuration error: {e}")
    except Exception as e:
        raise RetryableJobError(f"Daily progression eval failed: {e}")
