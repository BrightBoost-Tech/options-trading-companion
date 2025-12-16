from typing import Optional, Dict, Any
import os
from supabase import create_client, Client

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
    client.rpc('complete_job_run', {'job_id': job_id, 'result': result_json}).execute()

def requeue_job_run(client: Client, job_id: str, run_after: str, error_json: Dict[str, Any]) -> None:
    """
    Requeues a job run for a later time due to a retryable error.
    run_after should be an ISO 8601 formatted string.
    """
    client.rpc('requeue_job_run', {
        'job_id': job_id,
        'run_after': run_after,
        'error': error_json
    }).execute()

def dead_letter_job_run(client: Client, job_id: str, error_json: Dict[str, Any]) -> None:
    """
    Marks a job run as failed permanently (dead letter).
    """
    client.rpc('dead_letter_job_run', {'job_id': job_id, 'error': error_json}).execute()
