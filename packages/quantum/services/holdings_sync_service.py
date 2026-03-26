"""
Holdings Sync Service

Generic position retrieval utilities.
Plaid sync logic has been removed — positions now come from
Alpaca (via brokers/position_sync.py) or internal paper_positions.
"""

from typing import Dict, Any, List
from supabase import Client


def _get_holdings_count(user_id: str, supabase: Client) -> int:
    """Get count of current positions for a user."""
    try:
        result = supabase.table("positions") \
            .select("id", count="exact") \
            .eq("user_id", user_id) \
            .execute()
        return result.count or 0
    except Exception:
        return 0


def get_current_positions(user_id: str, supabase: Client) -> List[Dict[str, Any]]:
    """
    Get all current positions for a user from the database.
    """
    try:
        result = supabase.table("positions") \
            .select("*") \
            .eq("user_id", user_id) \
            .execute()
        return result.data or []
    except Exception as e:
        print(f"[holdings_sync] Error fetching positions for {user_id}: {e}")
        return []
