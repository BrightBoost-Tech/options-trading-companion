"""
Holdings Sync Service

Ensures holdings are up-to-date before generating suggestions.
Syncs from Plaid if connected and data is stale.
"""

from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta, timezone
from supabase import Client

from packages.quantum.services.token_store import PlaidTokenStore


# Holdings are considered stale after this many minutes
STALENESS_THRESHOLD_MINUTES = 60


def get_holdings_freshness(user_id: str, supabase: Client) -> Optional[datetime]:
    """
    Get the timestamp of the most recent holdings sync for a user.

    Returns:
        datetime of last sync, or None if never synced.
    """
    try:
        result = supabase.table("portfolio_snapshots") \
            .select("created_at") \
            .eq("user_id", user_id) \
            .eq("data_source", "plaid") \
            .order("created_at", desc=True) \
            .limit(1) \
            .execute()

        if result.data and len(result.data) > 0:
            timestamp_str = result.data[0].get("created_at")
            if timestamp_str:
                # Parse ISO timestamp
                return datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))

    except Exception as e:
        print(f"[holdings_sync] Error checking freshness for {user_id}: {e}")

    return None


def is_holdings_stale(user_id: str, supabase: Client) -> bool:
    """
    Check if holdings data is stale (older than threshold).
    """
    last_sync = get_holdings_freshness(user_id, supabase)
    if last_sync is None:
        return True

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALENESS_THRESHOLD_MINUTES)
    return last_sync < cutoff


def has_plaid_connection(user_id: str, supabase: Client) -> bool:
    """
    Check if user has an active Plaid connection.
    """
    try:
        token_store = PlaidTokenStore(supabase)
        access_token = token_store.get_access_token(user_id)
        return access_token is not None

    except Exception as e:
        print(f"[holdings_sync] Error checking Plaid connection for {user_id}: {e}")
        return False


async def sync_holdings_from_plaid(user_id: str, supabase: Client) -> Dict[str, Any]:
    """
    Sync holdings from Plaid for a user.

    This is an async wrapper that calls the Plaid sync endpoint logic.

    Returns:
        Dict with sync result: {ok: bool, holdings_count: int, error: str|None}
    """
    try:
        from packages.quantum.services.token_store import PlaidTokenStore
        from packages.quantum import plaid_service

        # Get access token
        token_store = PlaidTokenStore(supabase)
        access_token = token_store.get_access_token(user_id)

        if not access_token:
            return {"ok": False, "holdings_count": 0, "error": "No Plaid access token"}

        # Fetch holdings from Plaid
        result = plaid_service.get_holdings_with_accounts(access_token)

        if not result:
            return {"ok": False, "holdings_count": 0, "error": "Plaid API returned no data"}

        holdings = result.get("holdings", [])
        accounts = result.get("accounts", [])

        # Upsert positions to database
        for h in holdings:
            position_data = {
                "user_id": user_id,
                "symbol": h.get("symbol", "UNKNOWN"),
                "quantity": h.get("quantity", 0),
                "cost_basis": h.get("cost_basis", 0),
                "current_price": h.get("current_price", 0),
                "source": "plaid",
                "asset_type": h.get("asset_type", "EQUITY"),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

            supabase.table("positions") \
                .upsert(position_data, on_conflict="user_id,symbol") \
                .execute()

        # Calculate buying power from accounts
        buying_power = 0.0
        for acc in accounts:
            balances = acc.get("balances", {})
            buying_power += float(balances.get("available") or balances.get("current") or 0)

        # Insert portfolio snapshot
        snapshot = {
            "user_id": user_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "data_source": "plaid",
            "holdings": holdings,
            "buying_power": buying_power,
            "risk_metrics": {"accounts_synced": len(accounts)},
        }

        supabase.table("portfolio_snapshots").insert(snapshot).execute()

        return {
            "ok": True,
            "holdings_count": len(holdings),
            "accounts_count": len(accounts),
            "buying_power": buying_power,
        }

    except Exception as e:
        print(f"[holdings_sync] Error syncing Plaid for {user_id}: {e}")
        return {"ok": False, "holdings_count": 0, "error": str(e)}


async def ensure_holdings_fresh(
    user_id: str,
    supabase: Client,
    force_sync: bool = False
) -> Dict[str, Any]:
    """
    Ensure holdings are fresh for a user.

    If holdings are stale and user has Plaid connected, syncs from Plaid.
    Otherwise, returns current state without syncing.

    Args:
        user_id: User's UUID
        supabase: Supabase client
        force_sync: If True, sync even if not stale

    Returns:
        Dict with status: {
            synced: bool,
            stale: bool,
            has_plaid: bool,
            holdings_count: int,
            error: str|None
        }
    """
    has_plaid = has_plaid_connection(user_id, supabase)
    stale = is_holdings_stale(user_id, supabase)

    if not stale and not force_sync:
        # Holdings are fresh, no sync needed
        return {
            "synced": False,
            "stale": False,
            "has_plaid": has_plaid,
            "holdings_count": _get_holdings_count(user_id, supabase),
            "error": None,
        }

    if not has_plaid:
        # Can't sync without Plaid connection
        return {
            "synced": False,
            "stale": stale,
            "has_plaid": False,
            "holdings_count": _get_holdings_count(user_id, supabase),
            "error": "No Plaid connection - using existing positions",
        }

    # Sync from Plaid
    sync_result = await sync_holdings_from_plaid(user_id, supabase)

    return {
        "synced": sync_result.get("ok", False),
        "stale": False if sync_result.get("ok") else stale,
        "has_plaid": True,
        "holdings_count": sync_result.get("holdings_count", 0),
        "error": sync_result.get("error"),
    }


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
