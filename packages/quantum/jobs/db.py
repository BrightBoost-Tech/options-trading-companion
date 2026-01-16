from typing import Optional, Dict, Any, List
import os
from pathlib import Path
from datetime import datetime, date
from decimal import Decimal
from enum import Enum
from uuid import UUID
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

    if isinstance(obj, (list, tuple, set)):
        return [_to_jsonable(item) for item in obj]
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

    Environment variables (checked in order):
    - URL: SUPABASE_URL or NEXT_PUBLIC_SUPABASE_URL
    - Key: SUPABASE_SERVICE_ROLE_KEY or SUPABASE_SERVICE_KEY

    Raises ValueError with detailed instructions if required vars are missing.
    """
    # URL: prefer SUPABASE_URL, fallback to NEXT_PUBLIC_SUPABASE_URL
    url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")

    # Key: prefer SUPABASE_SERVICE_ROLE_KEY, fallback to SUPABASE_SERVICE_KEY
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY")

    if not url or not key:
        repo_root = _find_repo_root()
        missing = []
        if not url:
            missing.append("SUPABASE_URL (or NEXT_PUBLIC_SUPABASE_URL)")
        if not key:
            missing.append("SUPABASE_SERVICE_ROLE_KEY")

        # Build helpful error message
        env_files_checked = [
            str(repo_root / ".env.local"),
            str(repo_root / ".env"),
            str(repo_root / "packages" / "quantum" / ".env.local"),
            str(repo_root / "packages" / "quantum" / ".env"),
        ]

        loaded_str = ", ".join(_ENV_FILES_LOADED) if _ENV_FILES_LOADED else "(none found)"

        error_msg = f"""
Missing required environment variables for worker database access.

Missing variables:
  {chr(10).join(f'  - {v}' for v in missing)}

Environment files loaded:
  {loaded_str}

Files searched:
  {chr(10).join(f'  - {f}' for f in env_files_checked)}

To fix:
  1. Copy .env.example to .env in the repo root:
       cp .env.example .env

  2. Fill in the required values:
       SUPABASE_URL=https://<project>.supabase.co
       SUPABASE_SERVICE_ROLE_KEY=<your_service_role_key>

  3. For local Supabase, run 'supabase start' and use the local URL/keys.

See README.md for more details.
"""
        raise ValueError(error_msg.strip())

    return create_client(url, key)


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
