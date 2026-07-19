import asyncio
import logging
from typing import List, Any, Tuple
from supabase import create_client, Client
from packages.quantum.security.secrets_provider import SecretsProvider
from packages.quantum.services.market_session import (
    MarketCalendarUnavailable,
    get_market_session,
)

logger = logging.getLogger(__name__)

# Re-export so entry consumers can catch the fail-closed signal from one place.
__all__ = [
    "get_admin_client",
    "get_active_user_ids",
    "is_market_day",
    "MarketCalendarUnavailable",
    "run_async",
]

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
        # F-E8-3 (2026-07-12): a FAILED discovery read must RAISE, not return [].
        # []-as-no-users silently no-ops the job for ALL users (a DB failure looks
        # like "nobody to process"). Callers propagate → the runner records
        # failed_retryable. A genuinely-empty user_settings (query succeeds) still
        # returns [] — only FAILED reads go non-green.
        print(f"Error fetching active users (raising, not empty): {e}")
        raise

def is_market_day() -> Tuple[bool, str]:
    """Is today a US equity trading day? Returns ``(is_trading_day, reason)``.

    Holiday- AND half-day-aware: delegates to the canonical broker-calendar
    source (``services/market_session.get_market_session``), the same broker
    truth the intraday monitor and reentry cooldown trust. This REPLACES the
    prior weekday-only check whose docstring falsely claimed "the scheduler
    already handles" holidays — APScheduler's CronTrigger fires mon–fri
    regardless of exchange holidays (F-A10-HOLIDAY).

    RAISES ``MarketCalendarUnavailable`` when the broker calendar cannot be
    read. This is the fail-closed signal for ENTRY paths (they must generate no
    entries + surface typed job truth, never silently fall back to weekday
    logic). A successfully-determined non-trading day returns
    ``(False, reason)`` — it is NOT an error. Callers that must not be blocked
    by a transient calendar outage (non-entry / exit-management paths) catch
    the exception and preserve their prior always-ran semantics.
    """
    session = get_market_session()
    if not session.is_trading_day:
        return False, f"market_closed (non-trading day {session.session_date})"
    reason = f"trading_day ({session.session_date}"
    if session.is_early_close:
        reason += f", early_close {session.close_at:%H:%M ET}"
    reason += ")"
    return True, reason


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
