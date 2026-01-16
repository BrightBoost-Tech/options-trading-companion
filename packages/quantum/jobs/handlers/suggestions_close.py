"""
Suggestions Close Job Handler

8:00 AM Chicago - Generate CLOSE/manage existing positions suggestions.

This handler:
1. Ensures holdings are up to date (syncs Plaid if connected)
2. Loads strategy config by name
3. Generates exit suggestions for existing positions
4. Persists suggestions to trade_suggestions table with window='morning_limit'
"""

import time
from typing import Any, Dict

from packages.quantum.services.workflow_orchestrator import run_morning_cycle
from packages.quantum.services.holdings_sync_service import ensure_holdings_fresh
from packages.quantum.services.strategy_loader import load_strategy_config, ensure_default_strategy_exists
from packages.quantum.jobs.handlers.utils import get_admin_client, get_active_user_ids, run_async
from packages.quantum.jobs.handlers.exceptions import RetryableJobError, PermanentJobError

JOB_NAME = "suggestions_close"


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

                    # 4. Run morning cycle (generates exit suggestions)
                    await run_morning_cycle(client, uid)
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

        return {
            "ok": failed == 0,
            "counts": counts,
            "timing_ms": timing_ms,
            "strategy_name": strategy_name,
            "notes": notes[:20],  # Limit notes to avoid huge payloads
        }

    except ValueError as e:
        raise PermanentJobError(f"Configuration error: {e}")
    except Exception as e:
        raise RetryableJobError(f"Suggestions close job failed: {e}")
