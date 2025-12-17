from typing import Dict, Any
from packages.quantum.services.universe_service import UniverseService
from packages.quantum.security.secrets_provider import SecretsProvider
from supabase import create_client, Client
from datetime import datetime
import traceback

JOB_NAME = "universe_sync"

def run(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handler for universe_sync job.
    """
    print(f"[{JOB_NAME}] Starting job with payload: {payload}")

    try:
        # 1. Initialize Supabase Client
        secrets_provider = SecretsProvider()
        supa_secrets = secrets_provider.get_supabase_secrets()
        url = supa_secrets.url
        key = supa_secrets.service_role_key

        if not url or not key:
            raise ValueError("Supabase credentials missing")

        supabase: Client = create_client(url, key)

        # 2. Initialize UniverseService
        service = UniverseService(supabase)

        # 3. Execute Logic
        # Sync Base Universe (Seeds the table)
        service.sync_universe()

        # Update Metrics (Fetches from Polygon)
        service.update_metrics()

        return {
            "ok": True,
            "synced_count": len(UniverseService.BASE_UNIVERSE), # Approximation, since service prints it
            "ts": datetime.now().isoformat()
        }

    except Exception as e:
        print(f"[{JOB_NAME}] Failed: {e}")
        traceback.print_exc()
        # Return error dict for RQ to capture (or raise to mark as failed)
        # RQ jobs failing raises an exception usually.
        raise e
