from fastapi import APIRouter, Depends, HTTPException, Query, Request
from uuid import UUID
from typing import List, Optional, Union
from packages.quantum.security import get_current_user
from packages.quantum.security.secrets_provider import SecretsProvider
from supabase import create_client, Client
from packages.quantum.jobs.http_models import JobRunResponse

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
    status: Optional[str] = Query(None),
    job_name: Optional[str] = Query(None),
    limit: int = Query(50, le=100),
    client: Client = Depends(get_admin_client),
    user_id: str = Depends(get_current_user)
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
    user_id: str = Depends(get_current_user)
):
    res = client.table("job_runs").select("*").eq("id", str(job_run_id)).single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Job run not found")
    return res.data

@router.post("/runs/{job_run_id}/retry")
async def retry_job_run(
    job_run_id: UUID,
    client: Client = Depends(get_admin_client),
    user_id: str = Depends(get_current_user)
):
    # Fetch current status
    res = client.table("job_runs").select("status").eq("id", str(job_run_id)).single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Job run not found")

    current_status = res.data["status"]

    # sets status back to queued IF currently dead_lettered or failed_retryable
    if current_status in ["dead_lettered", "failed_retryable"]:
        update_data = {
            "status": "queued",
            "locked_at": None,
            "locked_by": None,
            "run_after": None,
            "error": None,
            "attempt": 0 # Reset attempts for manual retry
        }
        client.table("job_runs").update(update_data).eq("id", str(job_run_id)).execute()
        return {"status": "ok", "message": "Job retried"}

    return {"status": "ignored", "message": f"Job status is {current_status}, not retriable"}
