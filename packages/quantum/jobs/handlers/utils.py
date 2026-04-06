import asyncio
import logging
from datetime import datetime
from typing import List, Any, Tuple
from supabase import create_client, Client
from packages.quantum.security.secrets_provider import SecretsProvider

logger = logging.getLogger(__name__)

def get_admin_client() -> Client:
    """Initializes and returns a Supabase admin client."""
    secrets_provider = SecretsProvider()
    supa_secrets = secrets_provider.get_supabase_secrets()
    url = supa_secrets.url
    key = supa_secrets.service_role_key

    if not url or not key:
        raise ValueError("Supabase URL or Key missing in environment")

    return create_client(url, key)

def get_active_user_ids(client: Client) -> List[str]:
    """
    Get list of active user IDs, restricted by TRADING_USER_IDS when set.

    TRADING_USER_IDS: comma-separated list of user UUIDs that are allowed
    to trade. When set, only these users are returned regardless of what's
    in user_settings. This prevents other users from consuming resources.
    """
    import os
    allowed = os.environ.get("TRADING_USER_IDS", "").strip()
    if allowed:
        user_ids = [uid.strip() for uid in allowed.split(",") if uid.strip()]
        if user_ids:
            return user_ids

    try:
        res = client.table("user_settings").select("user_id").execute()
        return [r["user_id"] for r in res.data or []]
    except Exception as e:
        print(f"Error fetching active users: {e}")
        return []

def is_market_day() -> Tuple[bool, str]:
    """
    Fast check: is today a US equity trading day?
    Returns (is_open, reason).

    Checks weekday only (no holiday calendar — scheduler already handles this).
    For jobs that should only run on trading days, call this before doing any work.
    """
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("America/Chicago"))
    weekday = now.weekday()

    if weekday >= 5:
        day_name = "Saturday" if weekday == 5 else "Sunday"
        return False, f"weekend ({day_name})"

    return True, f"trading_day (Chicago {now.strftime('%H:%M')})"


def run_async(coro: Any) -> Any:
    """Helper to run an async coroutine synchronously."""
    try:
        return asyncio.run(coro)
    except RuntimeError:
        # If an event loop is already running (e.g. in tests or certain workers),
        # we might need loop.run_until_complete, or if nest_asyncio is applied.
        # For now, standard asyncio.run should work for a sync worker process.
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
