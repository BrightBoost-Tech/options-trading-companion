"""
Report Seed Review v4 Job Handler

Generates a report of seeded positions that require manual review due to
ambiguous side inference during the Seed v2 process.

Usage:
    Enqueue: {"job_name": "report_seed_review_v4"}
    Payload:
        - user_id: str (optional, filters to single user)
        - include_resolved: bool (optional, default false)
        - limit: int (optional, default 100)
"""

import logging
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from packages.quantum.nested_logging import _get_supabase_client

JOB_NAME = "report_seed_review_v4"

logger = logging.getLogger(__name__)


def run(payload: Dict[str, Any], ctx=None) -> Dict[str, Any]:
    """
    Job handler for generating seed review report.

    Queries position_events for entries where:
    - meta_json->>'opening_balance' = true (seed entries)
    - meta_json->>'needs_review' = true (ambiguous side inference)

    Payload:
        user_id: Optional single user to filter
        include_resolved: If True, include entries even if position is closed (default False)
        limit: Max rows to return (default 100)

    Returns:
        Dict with report data
    """
    logger.info(f"[REPORT_SEED_REVIEW_V4] Starting with payload: {payload}")

    try:
        supabase = _get_supabase_client()
        if not supabase:
            return {"status": "failed", "error": "Database unavailable"}

        user_id = payload.get("user_id")
        include_resolved = payload.get("include_resolved", False)
        limit = min(payload.get("limit", 100), 500)  # Cap at 500

        # Query position_events for needs_review entries
        rows = _query_needs_review_events(
            supabase,
            user_id=user_id,
            include_resolved=include_resolved,
            limit=limit
        )

        if not rows:
            return {
                "status": "completed",
                "count": 0,
                "rows": [],
                "message": "No positions requiring review found"
            }

        # Enrich with leg/group details
        enriched_rows = _enrich_with_details(supabase, rows)

        return {
            "status": "completed",
            "count": len(enriched_rows),
            "rows": enriched_rows,
            "truncated": len(rows) >= limit
        }

    except Exception as e:
        logger.error(f"[REPORT_SEED_REVIEW_V4] Job failed: {e}")
        logger.error(traceback.format_exc())
        return {"status": "failed", "error": str(e)}


def _query_needs_review_events(
    supabase,
    user_id: Optional[str] = None,
    include_resolved: bool = False,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """
    Query position_events for seed entries needing review.

    Args:
        supabase: Supabase client
        user_id: Optional user filter
        include_resolved: Whether to include closed positions
        limit: Max rows to return

    Returns:
        List of event rows with needs_review flag
    """
    try:
        # Build base query - filter on meta_json fields
        # Note: Supabase PostgREST supports JSON path filtering
        query = supabase.table("position_events").select(
            "id, user_id, group_id, leg_id, event_type, meta_json, created_at"
        ).eq(
            "meta_json->>opening_balance", "true"
        ).eq(
            "meta_json->>needs_review", "true"
        )

        if user_id:
            query = query.eq("user_id", user_id)

        query = query.order("created_at", desc=True).limit(limit)

        result = query.execute()
        events = result.data or []

        if not include_resolved and events:
            # Filter out events whose groups are closed
            group_ids = list(set(e["group_id"] for e in events if e.get("group_id")))
            if group_ids:
                open_groups = _get_open_group_ids(supabase, group_ids)
                events = [e for e in events if e.get("group_id") in open_groups]

        return events

    except Exception as e:
        logger.error(f"[REPORT_SEED_REVIEW_V4] Query failed: {e}")
        return []


def _get_open_group_ids(supabase, group_ids: List[str]) -> set:
    """Get subset of group_ids that are still OPEN."""
    try:
        result = supabase.table("position_groups").select(
            "id"
        ).in_("id", group_ids).eq("status", "OPEN").execute()

        return set(g["id"] for g in (result.data or []))

    except Exception as e:
        logger.error(f"[REPORT_SEED_REVIEW_V4] Failed to get open groups: {e}")
        return set(group_ids)  # Return all on error (safe fallback)


def _enrich_with_details(
    supabase,
    events: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Enrich event rows with leg and group details.

    Args:
        supabase: Supabase client
        events: List of position_events rows

    Returns:
        Enriched rows with symbol, side, qty, group status, etc.
    """
    if not events:
        return []

    # Collect unique leg_ids and group_ids
    leg_ids = list(set(e["leg_id"] for e in events if e.get("leg_id")))
    group_ids = list(set(e["group_id"] for e in events if e.get("group_id")))

    # Fetch legs
    legs_map = {}
    if leg_ids:
        try:
            legs_result = supabase.table("position_legs").select(
                "id, symbol, side, qty_current, underlying"
            ).in_("id", leg_ids).execute()

            for leg in (legs_result.data or []):
                legs_map[leg["id"]] = leg
        except Exception as e:
            logger.warning(f"[REPORT_SEED_REVIEW_V4] Failed to fetch legs: {e}")

    # Fetch groups
    groups_map = {}
    if group_ids:
        try:
            groups_result = supabase.table("position_groups").select(
                "id, strategy_key, status, opened_at"
            ).in_("id", group_ids).execute()

            for group in (groups_result.data or []):
                groups_map[group["id"]] = group
        except Exception as e:
            logger.warning(f"[REPORT_SEED_REVIEW_V4] Failed to fetch groups: {e}")

    # Build enriched rows
    enriched = []
    for event in events:
        leg = legs_map.get(event.get("leg_id"), {})
        group = groups_map.get(event.get("group_id"), {})
        meta = event.get("meta_json") or {}
        side_inference = meta.get("side_inference") or {}

        enriched.append({
            "user_id": event.get("user_id"),
            "event_id": event.get("id"),
            "group_id": event.get("group_id"),
            "leg_id": event.get("leg_id"),
            "symbol": leg.get("symbol"),
            "underlying": leg.get("underlying"),
            "inferred_side": leg.get("side"),
            "qty_current": leg.get("qty_current"),
            "side_inference": side_inference,
            "strategy_key": group.get("strategy_key"),
            "group_status": group.get("status"),
            "opened_at": group.get("opened_at"),
            "created_at": event.get("created_at"),
            "note": meta.get("note")
        })

    return enriched


# =============================================================================
# Convenience function for direct invocation
# =============================================================================

def get_needs_review_report(
    user_id: Optional[str] = None,
    include_resolved: bool = False,
    limit: int = 100
) -> Dict[str, Any]:
    """
    Convenience function to get needs_review report.

    Args:
        user_id: Optional user filter
        include_resolved: Include closed positions
        limit: Max rows

    Returns:
        Report dict
    """
    return run({
        "user_id": user_id,
        "include_resolved": include_resolved,
        "limit": limit
    })
