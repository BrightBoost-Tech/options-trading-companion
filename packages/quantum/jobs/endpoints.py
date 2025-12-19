from fastapi import APIRouter, Depends, HTTPException, Query, Request, Header
from uuid import UUID
from typing import List, Optional, Union, Dict, Any
from packages.quantum.security import get_current_user
from packages.quantum.security.secrets_provider import SecretsProvider
from packages.quantum.security.cron_auth import verify_cron_secret
from supabase import create_client, Client
from packages.quantum.jobs.http_models import JobRunResponse
from packages.quantum.jobs.rq_enqueue import enqueue_idempotent
from datetime import datetime
import os
import secrets

router = APIRouter(
    prefix="/jobs",
    tags=["jobs"],
)

# Admin Client Init
secrets_provider = SecretsProvider()
supa_secrets = secrets_provider.get_supabase_secrets()
url = supa_secrets.url
key = supa_secrets.service_role_key
supabase_admin: Client = create_client(url, key) if url and key else None

def get_admin_client():
    if not supabase_admin:
        raise HTTPException(status_code=503, detail="Database not available")
    return supabase_admin

async def get_authorized_actor(
    user_id: Optional[str] = Depends(get_current_user),
    x_cron_secret: Optional[str] = Header(None, alias="X-Cron-Secret")
):
    """
    Allows access if EITHER:
    1. A valid user is logged in (via get_current_user)
    2. The request has a valid X-Cron-Secret header
    """
    if user_id:
        return f"user:{user_id}"

    # Check Cron Secret
    if x_cron_secret:
        expected_secret = os.getenv("CRON_SECRET")
        if expected_secret and secrets.compare_digest(x_cron_secret, expected_secret):
            return "system:cron"

    raise HTTPException(status_code=401, detail="Unauthorized: User or Cron Secret required")

@router.get("/runs", response_model=List[JobRunResponse])
async def list_job_runs(
    status: Optional[str] = Query(None),
    job_name: Optional[str] = Query(None),
    limit: int = Query(50, le=100),
    client: Client = Depends(get_admin_client),
    actor: str = Depends(get_authorized_actor)
):
    query = client.table("job_runs").select("*").order("created_at", desc=True).limit(limit)

    if status:
        query = query.eq("status", status)
    if job_name:
        query = query.eq("job_name", job_name)

    res = query.execute()
    return res.data

@router.get("/runs/{job_run_id}", response_model=JobRunResponse)
async def get_job_run(
    job_run_id: UUID,
    client: Client = Depends(get_admin_client),
    actor: str = Depends(get_authorized_actor)
):
    res = client.table("job_runs").select("*").eq("id", str(job_run_id)).single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Job run not found")
    return res.data

@router.post("/runs/{job_run_id}/retry")
async def retry_job_run(
    job_run_id: UUID,
    client: Client = Depends(get_admin_client),
    actor: str = Depends(get_authorized_actor)
):
    # Fetch current status
    res = client.table("job_runs").select("*").eq("id", str(job_run_id)).single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Job run not found")

    job = res.data
    current_status = job["status"]

    # sets status back to queued IF currently dead_lettered or failed_retryable
    if current_status in ["dead_lettered", "failed_retryable", "cancelled", "succeeded"]:
        update_data = {
            "status": "queued",
            "locked_at": None,
            "locked_by": None,
            "run_after": datetime.now().isoformat(),
            "error": None,
            "attempt": 0 # Reset attempts for manual retry
        }
        client.table("job_runs").update(update_data).eq("id", str(job_run_id)).execute()

        # Enqueue in RQ again
        payload = {"job_run_id": str(job_run_id)}
        result = enqueue_idempotent(
            job_name=job["job_name"],
            idempotency_key=job["idempotency_key"], # Reuse same key
            payload=payload,
            handler_path="packages.quantum.jobs.runner.run_job_run"
        )

        return {"status": "ok", "message": "Job retried", "rq_job_id": result.get("job_id")}

    return {"status": "ignored", "message": f"Job status is {current_status}, not retriable"}
