from typing import Dict, Any, Optional
from uuid import UUID
from supabase import Client
from datetime import datetime

def enqueue_idempotent(
    client: Client,
    job_name: str,
    idempotency_key: str,
    payload: Optional[Dict[str, Any]] = None,
    run_after: Optional[datetime] = None,
    origin: Optional[Dict[str, Any]] = None,
) -> UUID:
    """
    Enqueues a job into the job_runs table idempotently.
    Returns the job_run_id (new or existing).

    Legacy DB-only path (no RQ push) — sole remaining caller is the operator
    smoke script ``packages/quantum/scripts/rq_smoke_morning_brief.py``.
    A5-2 origin provenance: stamped at insert time into ``payload.origin``;
    ``origin=None`` coerces to ``unknown_legacy``.
    """
    from packages.quantum.jobs.origin import coerce_origin

    if payload is None:
        payload = {}

    data = {
        "job_name": job_name,
        "idempotency_key": idempotency_key,
        "payload": {**payload, "origin": coerce_origin(origin)},
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
