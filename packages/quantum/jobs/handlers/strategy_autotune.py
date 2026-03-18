"""
Strategy Autotune Job Handler

Weekly strategy auto-tuning based on trade outcomes.

This handler:
1. Reads learning_feedback_loops for past 30 days
2. Uses normalized outcome classification (win/loss/breakeven) that handles
   both live outcomes and paper outcomes with outcome_type="trade_closed"
3. Computes win_rate, avg_pnl per strategy
4. If performance below threshold, mutates strategy config
5. Persists new version to strategy_configs table

Paper-autotune guard:
  Paper outcomes are always included in metric computation, but parameter
  mutations sourced from paper outcomes are blocked unless
  ENABLE_PAPER_AUTOTUNE=true.
"""

import time
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta, timezone

from packages.quantum.jobs.handlers.utils import get_admin_client, get_active_user_ids, run_async
from packages.quantum.jobs.handlers.exceptions import RetryableJobError, PermanentJobError
from packages.quantum.jobs.handlers.outcome_normalizer import classify_outcome
from packages.quantum.services.strategy_loader import load_strategy_config
from packages.quantum.config import ENABLE_PAPER_AUTOTUNE

JOB_NAME = "strategy_autotune"

# Thresholds for triggering mutation
MIN_WIN_RATE = 0.45  # Below this, consider mutation
MIN_AVG_PNL = 0.0    # Below this, consider mutation


def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """
    Auto-tune strategy configs based on trade outcomes.

    Payload:
        - week: str - Week identifier for idempotency
        - user_id: str|None - Specific user, or all users if None
        - strategy_name: str - Strategy to tune (default: spy_opt_autolearn_v6)
        - min_samples: int - Minimum trades required (default: 10)
    """
    start_time = time.time()
    notes = []
    counts = {"users_checked": 0, "strategies_updated": 0, "skipped_low_samples": 0}

    strategy_name = payload.get("strategy_name", "spy_opt_autolearn_v6")
    target_user_id = payload.get("user_id")
    min_samples = payload.get("min_samples", 10)

    try:
        client = get_admin_client()

        # Get target users
        if target_user_id:
            active_users = [target_user_id]
        else:
            active_users = get_active_user_ids(client)

        async def process_users():
            users_checked = 0
            strategies_updated = 0
            skipped = 0

            for uid in active_users:
                try:
                    result = await _evaluate_and_update(uid, strategy_name, client, min_samples)
                    users_checked += 1

                    if result.get("skipped"):
                        skipped += 1
                        notes.append(f"Skipped {uid[:8]}...: {result.get('reason')}")
                    elif result.get("updated"):
                        strategies_updated += 1
                        notes.append(f"Updated {strategy_name} to v{result.get('new_version')} for {uid[:8]}...")
                    else:
                        notes.append(f"No update needed for {uid[:8]}... (win_rate={result.get('win_rate', 0):.1%})")

                except Exception as e:
                    notes.append(f"Failed for {uid[:8]}...: {str(e)}")

            return users_checked, strategies_updated, skipped

        users_checked, updated, skipped = run_async(process_users())

        counts["users_checked"] = users_checked
        counts["strategies_updated"] = updated
        counts["skipped_low_samples"] = skipped

        timing_ms = (time.time() - start_time) * 1000

        return {
            "ok": True,
            "counts": counts,
            "timing_ms": timing_ms,
            "strategy_name": strategy_name,
            "min_samples": min_samples,
            "notes": notes[:20],
        }

    except ValueError as e:
        raise PermanentJobError(f"Configuration error: {e}")
    except Exception as e:
        raise RetryableJobError(f"Strategy autotune job failed: {e}")


def _compute_metrics(outcomes_with_pnl: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Compute win_rate, avg_pnl, and paper/live breakdown from outcomes
    using normalized outcome classification.

    Returns dict with: wins, losses, breakevens, win_rate, avg_pnl,
    paper_count, live_count, samples.
    """
    wins = 0
    losses = 0
    breakevens = 0
    paper_count = 0
    live_count = 0

    for o in outcomes_with_pnl:
        classification = classify_outcome(o)
        if classification == "win":
            wins += 1
        elif classification == "loss":
            losses += 1
        else:
            breakevens += 1

        if _is_paper(o):
            paper_count += 1
        else:
            live_count += 1

    total = len(outcomes_with_pnl)
    win_rate = wins / total if total > 0 else 0.0

    pnl_values = [float(o.get("pnl_realized", 0)) for o in outcomes_with_pnl]
    avg_pnl = sum(pnl_values) / len(pnl_values) if pnl_values else 0.0

    return {
        "wins": wins,
        "losses": losses,
        "breakevens": breakevens,
        "win_rate": win_rate,
        "avg_pnl": avg_pnl,
        "paper_count": paper_count,
        "live_count": live_count,
        "samples": total,
    }


def _is_paper(record: Dict[str, Any]) -> bool:
    """Check if an outcome record is from a paper trade."""
    if record.get("is_paper"):
        return True
    details = record.get("details_json") or {}
    return bool(details.get("is_paper"))


async def _evaluate_and_update(
    user_id: str,
    strategy_name: str,
    supabase,
    min_samples: int
) -> Dict[str, Any]:
    """
    Evaluate outcomes and update strategy if needed.

    Returns:
        Dict with result: {
            skipped: bool,
            reason: str,
            updated: bool,
            new_version: int,
            win_rate: float,
            avg_pnl: float,
            samples: int,
            paper_guard_blocked: bool
        }
    """
    # 1. Fetch recent outcomes
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

    result = supabase.table("learning_feedback_loops") \
        .select("pnl_realized, pnl_predicted, outcome_type, details_json, is_paper") \
        .eq("user_id", user_id) \
        .gte("created_at", cutoff) \
        .execute()

    outcomes = result.data or []

    # Filter to outcomes with PnL data
    outcomes_with_pnl = [o for o in outcomes if o.get("pnl_realized") is not None]

    if len(outcomes_with_pnl) < min_samples:
        return {
            "skipped": True,
            "reason": f"Only {len(outcomes_with_pnl)} samples (need {min_samples})",
            "samples": len(outcomes_with_pnl),
        }

    # 2. Compute metrics using normalized classification
    metrics = _compute_metrics(outcomes_with_pnl)
    win_rate = metrics["win_rate"]
    avg_pnl = metrics["avg_pnl"]
    paper_count = metrics["paper_count"]
    live_count = metrics["live_count"]

    # 3. Check if mutation needed
    needs_mutation = win_rate < MIN_WIN_RATE or avg_pnl < MIN_AVG_PNL

    if not needs_mutation:
        return {
            "skipped": False,
            "updated": False,
            "win_rate": win_rate,
            "avg_pnl": avg_pnl,
            "samples": metrics["samples"],
            "paper_count": paper_count,
            "live_count": live_count,
        }

    # 4. Paper-autotune guard
    has_paper = paper_count > 0
    paper_only = has_paper and live_count == 0

    if has_paper:
        print(
            f"[strategy_autotune] Paper outcomes observed for {user_id[:8]}...: "
            f"paper={paper_count}, live={live_count}"
        )

    if has_paper and not ENABLE_PAPER_AUTOTUNE:
        print(
            f"[strategy_autotune] Mutation skipped for {user_id[:8]}...: "
            f"paper outcomes present and ENABLE_PAPER_AUTOTUNE=false"
        )
        return {
            "skipped": False,
            "updated": False,
            "paper_guard_blocked": True,
            "win_rate": win_rate,
            "avg_pnl": avg_pnl,
            "samples": metrics["samples"],
            "paper_count": paper_count,
            "live_count": live_count,
        }

    # 5. Load current config and mutate
    current_config = load_strategy_config(user_id, strategy_name, supabase)
    current_version = current_config.get("version", 1)

    # Determine mutation based on failure mode
    if win_rate < MIN_WIN_RATE:
        fail_reason = "low_win_rate"
    else:
        fail_reason = "negative_pnl"

    mutated_params = _mutate_params(current_config, fail_reason)

    # 6. Persist new version
    new_version = current_version + 1
    _persist_strategy_config(
        supabase,
        user_id,
        strategy_name,
        new_version,
        mutated_params,
        f"Auto-tuned due to {fail_reason}: win_rate={win_rate:.1%}, avg_pnl=${avg_pnl:.2f}"
    )

    return {
        "skipped": False,
        "updated": True,
        "new_version": new_version,
        "win_rate": win_rate,
        "avg_pnl": avg_pnl,
        "samples": metrics["samples"],
        "mutation_reason": fail_reason,
        "paper_count": paper_count,
        "live_count": live_count,
    }


def _mutate_params(config: Dict, fail_reason: str) -> Dict:
    """
    Mutate strategy parameters based on failure reason.

    Uses similar logic to go_live_validation_service._mutate_config()
    """
    params = dict(config)

    if fail_reason == "low_win_rate":
        # Tighten entry criteria - be more selective
        conviction_floor = params.get("conviction_floor", 0.40)
        if conviction_floor < 0.55:
            params["conviction_floor"] = min(conviction_floor + 0.05, 0.55)

        # Tighten stop loss
        stop_loss = params.get("stop_loss_pct", 0.05)
        if stop_loss > 0.03:
            params["stop_loss_pct"] = max(stop_loss - 0.01, 0.03)

    elif fail_reason == "negative_pnl":
        # Reduce risk exposure
        max_risk = params.get("max_risk_pct_portfolio", 0.10)
        if max_risk > 0.05:
            params["max_risk_pct_portfolio"] = max(max_risk * 0.85, 0.05)

        # Lower take profit to exit earlier
        take_profit = params.get("take_profit_pct", 0.10)
        if take_profit > 0.05:
            params["take_profit_pct"] = max(take_profit - 0.02, 0.05)

        # Reduce holding time
        max_days = params.get("max_holding_days", 14)
        if max_days > 5:
            params["max_holding_days"] = max(max_days - 2, 5)

    return params


def _persist_strategy_config(
    supabase,
    user_id: str,
    name: str,
    version: int,
    params: Dict,
    description: str
) -> None:
    """
    Persist a new version of the strategy config.
    """
    try:
        config_data = {
            "user_id": user_id,
            "name": name,
            "version": version,
            "description": description,
            "params": params,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        supabase.table("strategy_configs").insert(config_data).execute()
        print(f"[strategy_autotune] Persisted {name} v{version} for user {user_id[:8]}...")

    except Exception as e:
        print(f"[strategy_autotune] Error persisting config: {e}")
        raise
