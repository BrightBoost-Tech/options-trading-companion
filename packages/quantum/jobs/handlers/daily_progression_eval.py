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

            from packages.quantum.services.progression_service import (
                get_alpaca_real_closed_trades,
                cumulative_realized_pl,
            )
            from datetime import datetime as _dt

            today_start_dt = _dt.fromisoformat(today_start)
            today_end_dt = _dt.fromisoformat(today_end)

            for uid in active_users:
                try:
                    # Sum realized PnL from Alpaca-routed positions closed today.
                    # Uses shared helper (see progression_service.py) that filters
                    # to entry-order alpaca_order_id IS NOT NULL — same lens used
                    # by promotion_check for full_auto eligibility.
                    closed_positions = get_alpaca_real_closed_trades(
                        user_id=uid,
                        supabase=client,
                        since=today_start_dt,
                        until=today_end_dt,
                    )

                    print(
                        f"[PROGRESSION] user={uid[:8]}: "
                        f"alpaca_entries_today={len(closed_positions)}",
                        flush=True,
                    )

                    if not closed_positions:
                        results.append({
                            "user_id": uid[:8],
                            "status": "no_closes",
                            "realized_pnl": 0,
                        })
                        continue

                    realized_pnl = cumulative_realized_pl(closed_positions)

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

        # #109 PR-2: global strategy lifecycle evaluation. Sibling step,
        # outside the per-user loop — strategy state is global, not
        # per-user. Failure here is logged + alerted via the
        # function's internal handlers but does NOT undo the user-loop
        # work above.
        strategy_transitions: list = []
        try:
            from packages.quantum.services.progression_service import (
                evaluate_strategy_lifecycle,
            )
            strategy_transitions = evaluate_strategy_lifecycle(client) or []
            if strategy_transitions:
                names = [t["strategy_name"] for t in strategy_transitions]
                print(
                    f"[PROGRESSION] Strategy lifecycle: "
                    f"{len(strategy_transitions)} graduated -> live_full: "
                    f"{names}",
                    flush=True,
                )
        except Exception as e:
            # Last-resort guard: evaluate_strategy_lifecycle handles its
            # own per-strategy failures, but any unexpected escape lands
            # here so the user-loop result envelope still returns.
            print(
                f"[PROGRESSION] Strategy lifecycle eval crashed: {e}",
                flush=True,
            )

        return {
            "ok": True,
            "trade_date": today.isoformat(),
            "users_evaluated": len(user_results),
            "promotions": total_promotions,
            "strategy_transitions": strategy_transitions,
            "timing_ms": (time.time() - start_time) * 1000,
            "results": user_results[:20],
        }

    except ValueError as e:
        raise PermanentJobError(f"Configuration error: {e}")
    except Exception as e:
        raise RetryableJobError(f"Daily progression eval failed: {e}")
