"""
Refresh Ledger Marks v4 Job Handler

Refreshes mark-to-market snapshots and unrealized PnL for open positions.

Usage:
    Enqueue: {"job_name": "refresh_ledger_marks_v4"}
    Payload:
        - user_id: str (optional, runs for all users with open positions if omitted)
        - group_ids: List[str] (optional, specific groups to refresh)
        - source: str (optional, mark source label - MARKET, EOD, MANUAL)
        - max_users: int (optional, cap on users to process in batch mode)
        - max_symbols_per_user: int (optional, cap on symbols per user)
        - batch_size: int (optional, quote fetch batch size, default 50)
        - max_groups: int (optional, cap on groups per user)
"""

import logging
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from packages.quantum.nested_logging import _get_supabase_client
from packages.quantum.services.position_pnl_service import PositionPnLService

JOB_NAME = "refresh_ledger_marks_v4"

logger = logging.getLogger(__name__)


def run(payload: Dict[str, Any], ctx=None) -> Dict[str, Any]:
    """
    Job handler for refreshing v4 position ledger marks.

    Fetches current market quotes for all open positions and updates
    the position_leg_marks table and materialized PnL columns.

    Payload:
        user_id: Optional single user to refresh (if omitted, all users with open positions)
        group_ids: Optional list of specific group IDs to refresh
        source: Mark source label (default "MARKET")
        max_users: Optional cap on users to process in batch mode
        max_symbols_per_user: Optional cap on symbols per user
        batch_size: Quote fetch batch size (default 50)
        max_groups: Optional cap on groups per user

    Returns:
        Dict with refresh summary including throttle diagnostics
    """
    logger.info(f"[REFRESH_MARKS_V4] Starting with payload: {payload}")

    try:
        supabase = _get_supabase_client()

        user_id = payload.get("user_id")
        group_ids = payload.get("group_ids")
        source = payload.get("source", "MARKET")
        max_users = payload.get("max_users")
        max_symbols_per_user = payload.get("max_symbols_per_user")
        batch_size = payload.get("batch_size", 50)
        max_groups = payload.get("max_groups")

        # Get users to process
        if user_id:
            user_ids = [user_id]
        else:
            user_ids = _get_users_with_open_positions(supabase)

        users_selected = len(user_ids)

        # Apply max_users cap (sort for determinism, then truncate)
        if max_users is not None and len(user_ids) > max_users:
            user_ids = sorted(user_ids)[:max_users]
            logger.info(f"[REFRESH_MARKS_V4] Truncated users from {users_selected} to {max_users}")

        if not user_ids:
            return {
                "success": True,
                "message": "No users with open positions",
                "users_selected": 0,
                "users_processed": 0,
                "total_legs_marked": 0,
                "total_groups_updated": 0,
                "total_marks_inserted": 0,
                "total_symbols_processed": 0,
                "total_stale_skips": 0,
                "total_missing_quote_skips": 0,
                "total_truncation_skips": 0,
                "total_truncated_symbols": 0,
                "errors": []
            }

        logger.info(f"[REFRESH_MARKS_V4] Processing {len(user_ids)} users (selected: {users_selected})")

        # Process each user
        total_legs_marked = 0
        total_groups_updated = 0
        total_marks_inserted = 0
        total_symbols_processed = 0
        total_stale_skips = 0
        total_missing_quote_skips = 0
        total_truncation_skips = 0
        total_truncated_symbols = 0
        all_errors = []
        users_processed = 0

        for uid in user_ids:
            try:
                pnl_service = PositionPnLService(supabase)
                result = pnl_service.refresh_marks_for_user(
                    user_id=uid,
                    group_ids=group_ids,
                    source=source,
                    max_symbols=max_symbols_per_user,
                    batch_size=batch_size,
                    max_groups=max_groups
                )

                if result["success"]:
                    total_legs_marked += result["legs_marked"]
                    total_groups_updated += result["groups_updated"]
                    total_marks_inserted += result["marks_inserted"]
                    users_processed += 1

                # Aggregate diagnostics
                diag = result.get("diagnostics", {})
                total_symbols_processed += diag.get("symbols_processed", 0)
                total_stale_skips += diag.get("stale_skips", 0)
                total_missing_quote_skips += diag.get("missing_quote_skips", 0)
                total_truncation_skips += diag.get("truncation_skips", 0)
                total_truncated_symbols += diag.get("truncated_symbols", 0)

                if not result["success"]:
                    all_errors.extend([f"User {uid}: {e}" for e in result.get("errors", [])])

                logger.info(
                    f"[REFRESH_MARKS_V4] User {uid}: "
                    f"legs={result['legs_marked']}, "
                    f"groups={result['groups_updated']}, "
                    f"marks={result['marks_inserted']}, "
                    f"symbols={diag.get('symbols_processed', 0)}"
                )

            except Exception as e:
                err_msg = f"User {uid}: {str(e)}"
                all_errors.append(err_msg)
                logger.error(f"[REFRESH_MARKS_V4] Error processing user {uid}: {e}")

        return {
            "success": len(all_errors) == 0,
            "users_selected": users_selected,
            "users_processed": users_processed,
            "total_legs_marked": total_legs_marked,
            "total_groups_updated": total_groups_updated,
            "total_marks_inserted": total_marks_inserted,
            "total_symbols_processed": total_symbols_processed,
            "total_stale_skips": total_stale_skips,
            "total_missing_quote_skips": total_missing_quote_skips,
            "total_truncation_skips": total_truncation_skips,
            "total_truncated_symbols": total_truncated_symbols,
            "errors": all_errors[:20]  # Cap errors for payload size
        }

    except Exception as e:
        logger.error(f"[REFRESH_MARKS_V4] Fatal error: {e}")
        logger.error(traceback.format_exc())
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()[:1000]
        }


def _get_users_with_open_positions(client) -> List[str]:
    """
    Get list of user IDs that have open position groups.

    Returns:
        List of user_id strings (sorted for deterministic processing)
    """
    try:
        result = client.table("position_groups").select(
            "user_id"
        ).eq("status", "OPEN").execute()

        if not result.data:
            return []

        # Deduplicate and sort user IDs for determinism
        user_ids = sorted(set(row["user_id"] for row in result.data))
        return user_ids

    except Exception as e:
        logger.error(f"Failed to get users with open positions: {e}")
        return []


# =============================================================================
# Convenience functions for direct invocation
# =============================================================================

def refresh_user_marks(
    user_id: str,
    group_ids: Optional[List[str]] = None,
    source: str = "MARKET",
    max_symbols: Optional[int] = None,
    batch_size: int = 50,
    max_groups: Optional[int] = None
) -> Dict[str, Any]:
    """
    Convenience function to refresh marks for a single user.

    Args:
        user_id: User UUID
        group_ids: Optional specific groups to refresh
        source: Mark source label
        max_symbols: Optional cap on symbols to fetch
        batch_size: Quote fetch batch size (default 50)
        max_groups: Optional cap on groups to process

    Returns:
        Result dict from PositionPnLService.refresh_marks_for_user()
    """
    supabase = _get_supabase_client()
    pnl_service = PositionPnLService(supabase)

    return pnl_service.refresh_marks_for_user(
        user_id=user_id,
        group_ids=group_ids,
        source=source,
        max_symbols=max_symbols,
        batch_size=batch_size,
        max_groups=max_groups
    )


def get_group_nlv(group_id: str) -> Dict[str, Any]:
    """
    Convenience function to get NLV for a position group.

    Args:
        group_id: Position group UUID

    Returns:
        Result dict from PositionPnLService.compute_group_nlv()
    """
    supabase = _get_supabase_client()
    pnl_service = PositionPnLService(supabase)

    return pnl_service.compute_group_nlv(group_id)
