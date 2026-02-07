"""
Suggestions Open Job Handler

11:00 AM Chicago - Generate OPEN/new positions suggestions.

This handler:
1. Ensures holdings are up to date (syncs Plaid if connected)
2. Loads strategy config by name
3. Scans for new entry opportunities
4. Persists suggestions to trade_suggestions table with window='midday_entry'
"""

import os
import time
from datetime import datetime, timezone
from typing import Any, Dict

from packages.quantum.services.workflow_orchestrator import run_midday_cycle
from packages.quantum.services.holdings_sync_service import ensure_holdings_fresh
from packages.quantum.services.strategy_loader import load_strategy_config, ensure_default_strategy_exists
from packages.quantum.jobs.handlers.utils import get_admin_client, get_active_user_ids, run_async
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

        async def process_users():
            processed = 0
            failed = 0
            synced = 0
            skipped = 0
            cycle_results = []  # Capture budget info per user

            for uid in active_users:
                try:
                    # 1. Ensure holdings are fresh
                    if not skip_sync:
                        sync_result = await ensure_holdings_fresh(uid, client)
                        if sync_result.get("synced"):
                            synced += 1
                            notes.append(f"Synced {sync_result.get('holdings_count', 0)} holdings for {uid[:8]}...")
                        elif sync_result.get("error"):
                            notes.append(f"Sync skipped for {uid[:8]}...: {sync_result.get('error')}")

                    # 2. Ensure default strategy exists
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
