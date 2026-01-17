"""
Job Runs Admin Endpoints (/jobs/*)

Security v4: These endpoints require admin access.
CRON_SECRET fallback has been removed to prevent privilege escalation.

Admin access is granted if:
1. JWT contains role=admin claim
2. User ID is in ADMIN_USER_IDS environment variable
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Header
from uuid import UUID
from typing import List, Optional, Union, Dict, Any
from packages.quantum.security.secrets_provider import SecretsProvider
from packages.quantum.security.admin_auth import (
    verify_admin_access,
    AdminAuthResult,
    log_admin_mutation,
)
from supabase import create_client, Client
from packages.quantum.jobs.http_models import JobRunResponse
from packages.quantum.jobs.rq_enqueue import enqueue_idempotent
from datetime import datetime

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

@router.get("/runs", response_model=List[JobRunResponse])
async def list_job_runs(
    request: Request,
    status: Optional[str] = Query(None),
    job_name: Optional[str] = Query(None),
    limit: int = Query(50, le=100),
    client: Client = Depends(get_admin_client),
    admin: AdminAuthResult = Depends(verify_admin_access)
):
    """
    List job runs. Requires admin access.

    Auth: Requires JWT with admin role or user ID in ADMIN_USER_IDS.
    """
    query = client.table("job_runs").select("*").order("created_at", desc=True).limit(limit)

    if status:
        query = query.eq("status", status)
    if job_name:
        query = query.eq("job_name", job_name)

    res = query.execute()
    return res.data

@router.get("/runs/{job_run_id}", response_model=JobRunResponse)
async def get_job_run(
    request: Request,
    job_run_id: UUID,
    client: Client = Depends(get_admin_client),
    admin: AdminAuthResult = Depends(verify_admin_access)
):
    """
    Get a specific job run by ID. Requires admin access.

    Auth: Requires JWT with admin role or user ID in ADMIN_USER_IDS.
    """
    res = client.table("job_runs").select("*").eq("id", str(job_run_id)).single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Job run not found")
    return res.data

@router.post("/runs/{job_run_id}/retry")
async def retry_job_run(
    request: Request,
    job_run_id: UUID,
    client: Client = Depends(get_admin_client),
    admin: AdminAuthResult = Depends(verify_admin_access)
):
    """
    Retry a job run. Requires admin access.

    Auth: Requires JWT with admin role or user ID in ADMIN_USER_IDS.

    Only jobs in dead_lettered, failed_retryable, cancelled, or succeeded status can be retried.
    """
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
            "attempt": 0  # Reset attempts for manual retry
        }
        client.table("job_runs").update(update_data).eq("id", str(job_run_id)).execute()

        # Enqueue in RQ again
        payload = {"job_run_id": str(job_run_id)}
        result = enqueue_idempotent(
            job_name=job["job_name"],
            idempotency_key=job["idempotency_key"],  # Reuse same key
            payload=payload,
            handler_path="packages.quantum.jobs.runner.run_job_run"
        )

        # Audit log the mutation
        log_admin_mutation(
            request=request,
            user_id=admin.user_id,
            action="retry",
            resource_type="job_run",
            resource_id=str(job_run_id),
            details={
                "job_name": job["job_name"],
                "previous_status": current_status,
                "rq_job_id": result.get("job_id")
            }
        )

        return {"status": "ok", "message": "Job retried", "rq_job_id": result.get("job_id")}

    return {"status": "ignored", "message": f"Job status is {current_status}, not retriable"}
