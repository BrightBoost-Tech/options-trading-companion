from typing import Optional, Dict, Any, List
import os
from pathlib import Path
from datetime import datetime, date
from decimal import Decimal
from enum import Enum
from uuid import UUID
try:
    import numpy as np
except ImportError:
    np = None
from supabase import create_client, Client

# ---------------------------------------------------------------------------
# Environment Loading
# ---------------------------------------------------------------------------

def _find_repo_root() -> Path:
    """
    Find the repository root by looking for marker files.
    Walks up from this file's location until we find pnpm-workspace.yaml or .git.
    """
    current = Path(__file__).resolve().parent
    for _ in range(10):  # Max 10 levels up
        if (current / "pnpm-workspace.yaml").exists() or (current / ".git").exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    # Fallback: assume packages/quantum/jobs/db.py -> repo root is 3 levels up
    return Path(__file__).resolve().parent.parent.parent.parent


def _load_env_files() -> List[str]:
    """
    Load environment files in priority order using python-dotenv.
    Returns list of files that were successfully loaded.

    Priority (first match wins for each var):
    1. repo_root/.env.local
    2. repo_root/.env
    3. repo_root/packages/quantum/.env.local
    4. repo_root/packages/quantum/.env
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        # python-dotenv not installed, skip loading
        return []

    repo_root = _find_repo_root()
    loaded_files = []

    # Files to check in priority order (later files don't override earlier)
    env_files = [
        repo_root / ".env.local",
        repo_root / ".env",
        repo_root / "packages" / "quantum" / ".env.local",
        repo_root / "packages" / "quantum" / ".env",
    ]

    for env_file in env_files:
        if env_file.exists():
            # override=False means existing env vars won't be overwritten
            load_dotenv(env_file, override=False)
            loaded_files.append(str(env_file))

    return loaded_files


# Load env files on module import
_ENV_FILES_LOADED = _load_env_files()


# ---------------------------------------------------------------------------
# JSON Serialization Helper
# ---------------------------------------------------------------------------

def _to_jsonable(obj: Any) -> Any:
    """
    Recursively converts objects to JSON-serializable types.
    """
    if obj is None:
        return None
    # exact bool check before int, though both are safe for json.dumps
    if isinstance(obj, bool):
        return obj

    # Numpy support
    if np is not None:
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return _to_jsonable(obj.tolist())

    if isinstance(obj, (str, int, float)):
        return obj
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, Enum):
        return obj.value

    # Pydantic v2
    if hasattr(obj, 'model_dump'):
        return _to_jsonable(obj.model_dump())
    # Pydantic v1
    if hasattr(obj, 'dict'):
        return _to_jsonable(obj.dict())

    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(item) for item in obj]
    if isinstance(obj, set):
        items = [_to_jsonable(item) for item in obj]
        try:
            return sorted(items)
        except TypeError:
            # Fallback for non-comparable types: sort by string representation then type name
            return sorted(items, key=lambda x: (str(x), type(x).__name__))
    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}

    # Fallback
    return str(obj)


# ---------------------------------------------------------------------------
# Supabase Client Creation
# ---------------------------------------------------------------------------

def create_supabase_admin_client() -> Client:
    """
    Creates a Supabase client with the service role key for admin access.

    Uses the unified supabase_config module for consistent env var resolution.
    Worker MUST have valid service role key - fails fast if missing.

    Raises ValueError with detailed instructions if required vars are missing.
    """
    # Import here to avoid circular imports
    from packages.quantum.security.supabase_config import (
        load_supabase_config, create_admin_client, KeyType
    )

    config = load_supabase_config()
    client, key_type, warnings = create_admin_client(config)

    # Print any warnings
    for w in warnings:
        print(f"[worker] ⚠️  {w}")

    # Worker requires service role key - fail fast if not available
    if key_type == KeyType.NONE:
        repo_root = _find_repo_root()
        loaded_str = ", ".join(_ENV_FILES_LOADED) if _ENV_FILES_LOADED else "(none found)"

        error_msg = f"""
Missing required environment variables for worker database access.

Missing: SUPABASE_URL and/or SUPABASE_SERVICE_ROLE_KEY

Environment files loaded:
  {loaded_str}

To fix:
  1. Copy .env.example to .env in the repo root:
       cp .env.example .env

  2. Fill in the required values:
       SUPABASE_URL=https://<project>.supabase.co
       SUPABASE_SERVICE_ROLE_KEY=<your_service_role_key>

  3. For local Supabase, run 'supabase start' and use the local URL/keys.

See README.md "Supabase Configuration" section for more details.
"""
        raise ValueError(error_msg.strip())

    if key_type == KeyType.ANON:
        raise ValueError(
            "Worker requires SUPABASE_SERVICE_ROLE_KEY for admin access.\n"
            "Only anon key was found. Set SUPABASE_SERVICE_ROLE_KEY in .env"
        )

    print(f"[worker] ✅ Supabase client created (key_type={key_type.value})")
    return client


# ---------------------------------------------------------------------------
# Job Queue Database Operations
# ---------------------------------------------------------------------------

def claim_job_run(client: Client, worker_id: str) -> Optional[Dict[str, Any]]:
    try:
        # FIX: function signature is claim_job_run(p_worker_id text)
        response = client.rpc('claim_job_run', {'p_worker_id': worker_id}).execute()
        data = response.data
        if not data:
            return None
        if isinstance(data, list):
            return data[0] if data else None
        return data
    except Exception as e:
        print(f"Error claiming job run: {e}")
        return None


def complete_job_run(client: Client, job_id: str, result_json: Dict[str, Any]) -> None:
    payload = _to_jsonable(result_json)
    # FIX: function signature is complete_job_run(p_job_id uuid, p_result jsonb)
    client.rpc('complete_job_run', {'p_job_id': job_id, 'p_result': payload}).execute()


def requeue_job_run(client: Client, job_id: str, run_after: str, error_json: Dict[str, Any]) -> None:
    payload = _to_jsonable(error_json)
    # FIX: function signature is requeue_job_run(p_job_id uuid, p_run_after timestamptz, p_error jsonb)
    client.rpc('requeue_job_run', {
        'p_job_id': job_id,
        'p_run_after': run_after,
        'p_error': payload
    }).execute()


def dead_letter_job_run(client: Client, job_id: str, error_json: Dict[str, Any]) -> None:
    payload = _to_jsonable(error_json)
    # FIX: function signature is dead_letter_job_run(p_job_id uuid, p_error jsonb)
    client.rpc('dead_letter_job_run', {'p_job_id': job_id, 'p_error': payload}).execute()
