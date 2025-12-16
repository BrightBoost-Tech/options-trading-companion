from typing import Dict, Any, Optional
from uuid import UUID
from supabase import Client
from datetime import datetime

def enqueue_idempotent(
    client: Client,
    job_name: str,
    idempotency_key: str,
    payload: Optional[Dict[str, Any]] = None,
    run_after: Optional[datetime] = None
) -> UUID:
    """
    Enqueues a job into the job_runs table idempotently.
    Returns the job_run_id (new or existing).
    """
    if payload is None:
        payload = {}

    data = {
        "job_name": job_name,
        "idempotency_key": idempotency_key,
        "payload": payload,
        "status": "queued"
    }
    if run_after:
        data["run_after"] = run_after.isoformat()

    # Try to insert (ignore duplicates)
    res = client.table("job_runs").upsert(
        data,
        on_conflict="job_name, idempotency_key",
        ignore_duplicates=True
    ).execute()

    if res.data:
        return UUID(res.data[0]["id"])

    # If duplicate, fetch existing
    res = client.table("job_runs").select("id")\
        .eq("job_name", job_name)\
        .eq("idempotency_key", idempotency_key)\
        .single().execute()

    if res.data:
        return UUID(res.data["id"])

    raise Exception(f"Failed to enqueue job {job_name} and failed to retrieve existing job.")
