import asyncio
from typing import List, Any
from supabase import create_client, Client
from packages.quantum.security.secrets_provider import SecretsProvider

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
    """Helper to get list of active user IDs."""
    try:
        res = client.table("user_settings").select("user_id").execute()
        return [r["user_id"] for r in res.data or []]
    except Exception as e:
        print(f"Error fetching active users: {e}")
        return []

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
