"""
Reconcile Positions v4 Job Handler

Compares canonical position ledger against broker snapshot (positions table)
and records any discrepancies to reconciliation_breaks.

Usage:
    Enqueue: {"job_name": "reconcile_positions_v4"}
    Payload:
        - user_id: str (optional, runs for all active users if omitted)
        - dry_run: bool (optional, if True skips writing breaks)
"""

import logging
import traceback
from typing import Dict, Any

from packages.quantum.nested_logging import _get_supabase_client
from packages.quantum.services.position_ledger_service import PositionLedgerService

JOB_NAME = "reconcile_positions_v4"

logger = logging.getLogger(__name__)


def run(payload: Dict[str, Any], ctx=None) -> Dict[str, Any]:
    """
    Job handler for v4 position reconciliation.

    Compares canonical position ledger against broker positions table
    and records discrepancies to reconciliation_breaks.

    Payload:
        user_id: Optional single user to reconcile
        dry_run: If True, compare but don't write breaks (default False)

    Returns:
        Dict with reconciliation summary
    """
    logger.info(f"[RECONCILE_V4] Starting with payload: {payload}")

    try:
        supabase = _get_supabase_client()
        if not supabase:
            return {"status": "failed", "error": "Database unavailable"}

        dry_run = payload.get("dry_run", False)
        user_id = payload.get("user_id")

        # If single user specified, run for that user only
        if user_id:
            result = _reconcile_user(supabase, user_id, dry_run)
            return {
                "status": "completed",
                "users_processed": 1,
                "results": {user_id: result},
            }

        # Batch mode: fetch all users with active positions
        users = _get_users_with_positions(supabase)

        if not users:
            logger.info("[RECONCILE_V4] No users with positions found")
            return {
                "status": "completed",
                "users_processed": 0,
                "results": {},
            }

        logger.info(f"[RECONCILE_V4] Processing {len(users)} users")

        results = {}
        total_breaks = 0
        errors = 0

        for uid in users:
            try:
                result = _reconcile_user(supabase, uid, dry_run)
                results[uid] = result
                total_breaks += result.get("breaks_found", 0)
            except Exception as ex:
                logger.error(f"[RECONCILE_V4] Error for user {uid}: {ex}")
                results[uid] = {"status": "error", "error": str(ex)}
                errors += 1

        return {
            "status": "completed",
            "users_processed": len(users),
            "total_breaks": total_breaks,
            "errors": errors,
            "dry_run": dry_run,
            "results": results,
        }

    except Exception as e:
        logger.error(f"[RECONCILE_V4] Job failed: {e}")
        logger.error(traceback.format_exc())
        return {"status": "failed", "error": str(e)}


def _reconcile_user(supabase, user_id: str, dry_run: bool) -> Dict[str, Any]:
    """
    Reconcile positions for a single user.

    Fetches broker positions from `positions` table and compares
    against canonical ledger via PositionLedgerService.
    """
    logger.info(f"[RECONCILE_V4] Reconciling user: {user_id}")

    # Fetch broker positions from positions table
    broker_positions = _get_broker_positions(supabase, user_id)

    if dry_run:
        # Compare without writing breaks
        ledger = PositionLedgerService(supabase)
        ledger_positions = ledger._get_ledger_positions_by_symbol(user_id)

        # Calculate differences
        all_symbols = set(ledger_positions.keys()) | set(
            p.get("symbol") for p in broker_positions if p.get("symbol")
        )

        differences = []
        for symbol in all_symbols:
            ledger_qty = ledger_positions.get(symbol, 0)
            broker_qty = sum(
                int(p.get("qty", 0) or p.get("quantity", 0))
                for p in broker_positions
                if p.get("symbol") == symbol
            )

            if ledger_qty != broker_qty:
                differences.append({
                    "symbol": symbol,
                    "ledger_qty": ledger_qty,
                    "broker_qty": broker_qty,
                    "diff": ledger_qty - broker_qty,
                })

        return {
            "status": "dry_run",
            "ledger_positions": len(ledger_positions),
            "broker_positions": len(broker_positions),
            "breaks_found": len(differences),
            "breaks": differences[:10],  # Cap for payload size
        }

    # Full reconciliation with break recording
    ledger = PositionLedgerService(supabase)
    result = ledger.reconcile_snapshot(
        user_id=user_id,
        snapshot_rows=broker_positions,
    )

    return {
        "status": "reconciled",
        "run_id": result.get("run_id"),
        "ledger_positions": result.get("ledger_positions", 0),
        "broker_positions": result.get("broker_positions", 0),
        "breaks_found": result.get("breaks_found", 0),
        "error": result.get("error"),
    }


def _get_users_with_positions(supabase) -> list:
    """
    Get list of users with either ledger positions or broker positions.

    Sources:
    - v3_go_live_state: users with go-live state
    - position_groups: users with ledger groups
    - positions: users with broker positions
    """
    users = set()

    # From v3_go_live_state (active users)
    try:
        res = supabase.table("v3_go_live_state").select("user_id").execute()
        users.update(r["user_id"] for r in (res.data or []))
    except Exception as e:
        logger.warning(f"[RECONCILE_V4] Could not fetch v3_go_live_state: {e}")

    # From position_groups (users with ledger data)
    try:
        res = supabase.table("position_groups") \
            .select("user_id") \
            .eq("status", "OPEN") \
            .execute()
        users.update(r["user_id"] for r in (res.data or []))
    except Exception as e:
        logger.warning(f"[RECONCILE_V4] Could not fetch position_groups: {e}")

    # From positions (users with broker positions)
    try:
        res = supabase.table("positions") \
            .select("user_id") \
            .neq("qty", 0) \
            .execute()
        users.update(r["user_id"] for r in (res.data or []))
    except Exception as e:
        logger.warning(f"[RECONCILE_V4] Could not fetch positions: {e}")

    return list(users)


def _get_broker_positions(supabase, user_id: str) -> list:
    """
    Fetch broker positions from positions table for a user.

    Returns list of position dicts with symbol, qty, etc.
    """
    try:
        res = supabase.table("positions") \
            .select("symbol, qty, quantity, underlying, position_type") \
            .eq("user_id", user_id) \
            .execute()
        return res.data or []
    except Exception as e:
        logger.error(f"[RECONCILE_V4] Error fetching positions for {user_id}: {e}")
        return []
