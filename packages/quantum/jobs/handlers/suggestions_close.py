"""
Suggestions Close Job Handler

8:00 AM Chicago - Generate CLOSE/manage existing positions suggestions.

This handler:
1. Loads strategy config by name
2. Generates exit suggestions for existing positions
3. Persists suggestions to trade_suggestions table with window='morning_limit'
"""

import os
import time
from datetime import datetime, timezone
from typing import Any, Dict

from packages.quantum.services.workflow_orchestrator import run_morning_cycle
from packages.quantum.services.strategy_loader import load_strategy_config, ensure_default_strategy_exists
from packages.quantum.jobs.handlers.utils import get_admin_client, get_active_user_ids, run_async, is_market_day
from packages.quantum.jobs.handlers.exceptions import RetryableJobError, PermanentJobError
from packages.quantum.jobs.db import _to_jsonable

JOB_NAME = "suggestions_close"

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
    Generate CLOSE suggestions for all active users.

    Payload:
        - date: str - Date for idempotency
        - type: str - "close"
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

        async def process_users():
            processed = 0
            failed = 0
            synced = 0
            skipped = 0

            for uid in active_users:
                try:
                    # 0. Dismiss stale pending suggestions from previous days
                    today_str = datetime.now(timezone.utc).date().isoformat()
                    try:
                        stale_res = client.table("trade_suggestions") \
                            .update({"status": "dismissed"}) \
                            .eq("user_id", uid) \
                            .eq("status", "pending") \
                            .lt("cycle_date", today_str) \
                            .execute()
                        dismissed = len(stale_res.data or [])
                        if dismissed > 0:
                            notes.append(f"Dismissed {dismissed} stale suggestions for {uid[:8]}...")
                    except Exception as e:
                        notes.append(f"Stale cleanup error for {uid[:8]}: {e}")

                    # 1. Ensure default strategy exists
                    ensure_default_strategy_exists(uid, strategy_name, client)

                    # 3. Load strategy config (for logging/tracing)
                    strategy_config = load_strategy_config(uid, strategy_name, client)
                    notes.append(f"Using strategy {strategy_name} v{strategy_config.get('version', 1)} for {uid[:8]}...")

                    # 4. Run morning cycle (generates exit suggestions)
                    # Wrap with DecisionContext if replay feature store is enabled
                    DecisionContext = _get_decision_context_class()
                    if DecisionContext:
                        as_of_ts = datetime.now(timezone.utc)
                        git_sha = os.getenv("GIT_SHA")
                        ctx = DecisionContext(
                            strategy_name="suggestions_close",
                            as_of_ts=as_of_ts,
                            user_id=uid,
                            git_sha=git_sha,
                        )
                        ctx.__enter__()
                        try:
                            await run_morning_cycle(client, uid)
                            ctx.commit(client, status="ok")
                        except Exception as cycle_err:
                            ctx.commit(client, status="failed", error_summary=str(cycle_err)[:500])
                            raise
                        finally:
                            ctx.__exit__(None, None, None)
                    else:
                        await run_morning_cycle(client, uid)

                    # 5. Execute exits immediately (don't wait for separate paper_exit_evaluate job)
                    try:
                        from packages.quantum.services.paper_exit_evaluator import PaperExitEvaluator
                        evaluator = PaperExitEvaluator(client)
                        exit_result = evaluator.evaluate_exits(uid)
                        closing = exit_result.get("closing", 0)
                        if closing > 0:
                            notes.append(f"Closed {closing} positions for {uid[:8]}")
                    except Exception as exit_err:
                        notes.append(f"Exit eval error for {uid[:8]}: {exit_err}")

                    processed += 1

                except Exception as e:
                    notes.append(f"Failed for user {uid[:8]}...: {str(e)}")
                    failed += 1

            return processed, failed, synced, skipped

        processed, failed, synced, skipped = run_async(process_users())
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
        })

    except ValueError as e:
        raise PermanentJobError(f"Configuration error: {e}")
    except Exception as e:
        raise RetryableJobError(f"Suggestions close job failed: {e}")
