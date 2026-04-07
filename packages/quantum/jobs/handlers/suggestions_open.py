"""
Suggestions Open Job Handler

11:00 AM Chicago - Generate OPEN/new positions suggestions.

This handler:
1. Loads strategy config by name
2. Scans for new entry opportunities
3. Persists suggestions to trade_suggestions table with window='midday_entry'
"""

import os
import time
from datetime import datetime, timezone
from typing import Any, Dict

from packages.quantum.services.workflow_orchestrator import run_midday_cycle
from packages.quantum.services.strategy_loader import load_strategy_config, ensure_default_strategy_exists
from packages.quantum.jobs.handlers.utils import get_admin_client, get_active_user_ids, run_async, is_market_day
from packages.quantum.jobs.handlers.exceptions import RetryableJobError, PermanentJobError
from packages.quantum.jobs.db import _to_jsonable

JOB_NAME = "suggestions_open"

# Replay feature store integration (lazy import to avoid circular deps)
def _get_decision_context_class():
    """Lazy import DecisionContext to avoid circular imports."""
    try:
        from packages.quantum.services.replay.decision_context import (
            DecisionContext,
            is_replay_enabled,
        )
        return DecisionContext if is_replay_enabled() else None
    except ImportError:
        return None


def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """
    Generate OPEN suggestions for all active users.

    Payload:
        - date: str - Date for idempotency
        - type: str - "open"
        - strategy_name: str - Strategy config name (default: spy_opt_autolearn_v6)
        - user_id: str|None - Specific user, or all users if None
        - skip_sync: bool - Skip holdings sync (default: False)
    """
    start_time = time.time()
    notes = []
    counts = {"processed": 0, "failed": 0, "synced": 0, "skipped": 0}

    # === FAST PATH: skip on weekends ===
    is_trading, market_reason = is_market_day()
    if not is_trading:
        return {"ok": True, "fast_path": True, "reason": market_reason,
                "counts": counts, "timing_ms": 0}

    strategy_name = payload.get("strategy_name", "spy_opt_autolearn_v6")
    target_user_id = payload.get("user_id")
    skip_sync = payload.get("skip_sync", False)

    try:
        client = get_admin_client()

        # Get target users
        if target_user_id:
            active_users = [target_user_id]
        else:
            active_users = get_active_user_ids(client)

        # === FAST PATH: no active users ===
        if not active_users:
            return {"ok": True, "fast_path": True, "reason": "no_active_users",
                    "counts": counts, "timing_ms": (time.time() - start_time) * 1000}

        # Staleness gate: block suggestion generation if market data is stale
        try:
            from packages.quantum.risk.staleness_gate import check_staleness_gate
            stale = check_staleness_gate()
            if stale.blocked:
                return {
                    "ok": True,
                    "fast_path": True,
                    "reason": f"staleness_gate: {stale.reason}",
                    "age_seconds": stale.age_seconds,
                    "stale_symbols": stale.stale_symbols,
                    "counts": counts,
                    "timing_ms": (time.time() - start_time) * 1000,
                }
        except Exception as sg_err:
            import logging as _lg
            _lg.getLogger(__name__).warning(f"[STALENESS_GATE] Check failed (non-fatal): {sg_err}")

        async def process_users():
            processed = 0
            failed = 0
            synced = 0
            skipped = 0
            cycle_results = []  # Capture budget info per user

            for uid in active_users:
                try:
                    # 1. Ensure default strategy exists
                    ensure_default_strategy_exists(uid, strategy_name, client)

                    # 3. Load strategy config (for logging/tracing)
                    strategy_config = load_strategy_config(uid, strategy_name, client)
                    notes.append(f"Using strategy {strategy_name} v{strategy_config.get('version', 1)} for {uid[:8]}...")

                    # 4. Run midday cycle (generates entry suggestions)
                    # Wrap with DecisionContext if replay feature store is enabled
                    DecisionContext = _get_decision_context_class()
                    if DecisionContext:
                        as_of_ts = datetime.now(timezone.utc)
                        git_sha = os.getenv("GIT_SHA")
                        ctx = DecisionContext(
                            strategy_name="suggestions_open",
                            as_of_ts=as_of_ts,
                            user_id=uid,
                            git_sha=git_sha,
                        )
                        ctx.__enter__()
                        try:
                            cycle_result = await run_midday_cycle(client, uid)
                            ctx.commit(client, status="ok")
                        except Exception as cycle_err:
                            ctx.commit(client, status="failed", error_summary=str(cycle_err)[:500])
                            raise
                        finally:
                            ctx.__exit__(None, None, None)
                    else:
                        cycle_result = await run_midday_cycle(client, uid)

                    # Policy Lab: fork scored suggestions into cohort variants
                    try:
                        from packages.quantum.policy_lab.config import is_policy_lab_enabled
                        if is_policy_lab_enabled():
                            from packages.quantum.policy_lab.fork import fork_suggestions_for_cohorts
                            fork_result = fork_suggestions_for_cohorts(uid, client)
                            if fork_result.get("status") == "ok":
                                notes.append(f"Policy Lab fork: {fork_result.get('created', {})}")
                    except Exception as fork_err:
                        notes.append(f"Policy Lab fork error: {fork_err}")

                    # Capture cycle result for observability
                    if cycle_result:
                        cycle_results.append({"user_id": uid[:8], **cycle_result})

                    processed += 1

                except Exception as e:
                    notes.append(f"Failed for user {uid[:8]}...: {str(e)}")
                    failed += 1

            return processed, failed, synced, skipped, cycle_results

        processed, failed, synced, skipped, cycle_results = run_async(process_users())
        counts["processed"] = processed
        counts["failed"] = failed
        counts["synced"] = synced
        counts["skipped"] = skipped

        timing_ms = (time.time() - start_time) * 1000

        # Ensure all values are JSON-serializable (datetime -> isoformat, etc.)
        return _to_jsonable({
            "ok": failed == 0,
            "counts": counts,
            "timing_ms": timing_ms,
            "strategy_name": strategy_name,
            "notes": notes[:20],  # Limit notes to avoid huge payloads
            "cycle_results": cycle_results[:10],  # Budget/reason info per user
        })

    except ValueError as e:
        raise PermanentJobError(f"Configuration error: {e}")
    except Exception as e:
        raise RetryableJobError(f"Suggestions open job failed: {e}")
