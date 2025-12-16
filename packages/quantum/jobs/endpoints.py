from fastapi import APIRouter, Depends, HTTPException, Query
from uuid import UUID
from typing import List, Optional
from packages.quantum.security.task_auth import verify_internal_task_request
from packages.quantum.security.secrets_provider import SecretsProvider
from supabase import create_client, Client
from packages.quantum.jobs.http_models import JobRunResponse

router = APIRouter(
    prefix="/jobs",
    tags=["jobs"],
    # Protect these endpoints similarly to tasks, or maybe just service/dev-only as requested.
    # User said: "Add monitoring endpoints (service/dev-only)"
    # I'll use verify_internal_task_request for now as a basic guard if X-Cron-Secret is used,
    # or rely on the caller having access. The prompt doesn't specify auth for monitoring,
    # but "service/dev-only" implies protection. I'll stick to verify_internal_task_request
    # or maybe just depend on nothing if it's internal network only?
    # Given the existing pattern, I'll assume they might be called by developers or dashboard.
    # Let's use verify_internal_task_request for write (retry), and maybe open/auth for read?
    # Prompt says "Keep X-Cron-Secret verification unchanged" for TASKS endpoints.
    # For JOB endpoints, it doesn't explicitly say.
    # I'll add `verify_internal_task_request` to be safe.
    dependencies=[Depends(verify_internal_task_request)]
)

# Admin Client Init (duplicated pattern, maybe centralize later)
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
    client: Client = Depends(get_admin_client)
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
    client: Client = Depends(get_admin_client)
):
    res = client.table("job_runs").select("*").eq("id", str(job_run_id)).single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Job run not found")
    return res.data

@router.post("/runs/{job_run_id}/retry")
async def retry_job_run(
    job_run_id: UUID,
    client: Client = Depends(get_admin_client)
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
            "error": None
            # Do we reset retry_count? Prompt didn't say. Usually yes or keep it.
            # "clears locked fields and run_after"
        }
        client.table("job_runs").update(update_data).eq("id", str(job_run_id)).execute()
        return {"status": "ok", "message": "Job retried"}

    return {"status": "ignored", "message": f"Job status is {current_status}, not retriable"}
