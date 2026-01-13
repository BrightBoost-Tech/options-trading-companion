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
    """
    Attempts to claim a pending job run for the given worker.
    """
    try:
        response = client.rpc('claim_job_run', {'worker_id': worker_id}).execute()
        # RPC returns a single object or None/null
        # supabase-py execute() returns a response object with .data
        data = response.data
        if not data:
            return None
        # If rpc returns a list with one item (common pattern), handle it
        if isinstance(data, list):
            return data[0] if data else None
        return data
    except Exception as e:
        # In case of connection error or other issues, we return None and let the worker retry/sleep
        print(f"Error claiming job run: {e}")
        return None

def complete_job_run(client: Client, job_id: str, result_json: Dict[str, Any]) -> None:
    """
    Marks a job run as completed with the given result.
    """
    payload = _to_jsonable(result_json)
    client.rpc('complete_job_run', {'job_id': job_id, 'result': payload}).execute()

def requeue_job_run(client: Client, job_id: str, run_after: str, error_json: Dict[str, Any]) -> None:
    """
    Requeues a job run for a later time due to a retryable error.
    run_after should be an ISO 8601 formatted string.
    """
    payload = _to_jsonable(error_json)
    client.rpc('requeue_job_run', {
        'job_id': job_id,
        'run_after': run_after,
        'error': payload
    }).execute()

def dead_letter_job_run(client: Client, job_id: str, error_json: Dict[str, Any]) -> None:
    """
    Marks a job run as failed permanently (dead letter).
    """
    payload = _to_jsonable(error_json)
    client.rpc('dead_letter_job_run', {'job_id': job_id, 'error': payload}).execute()
