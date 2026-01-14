from typing import Optional, Dict, Any
import os
from datetime import datetime, date
from decimal import Decimal
from enum import Enum
from uuid import UUID
from supabase import create_client, Client

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

def create_supabase_admin_client() -> Client:
    """
    Creates a Supabase client with the service role key for admin access.
    """
    url = os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not url or not key:
        raise ValueError("NEXT_PUBLIC_SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for worker database access.")

    return create_client(url, key)

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
