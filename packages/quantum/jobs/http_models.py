from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime
from uuid import UUID

class EnqueueResponse(BaseModel):
    job_run_id: UUID
    job_name: str
    idempotency_key: str
    status: str

class JobRunResponse(BaseModel):
    id: UUID
    job_name: str
    idempotency_key: str
    status: str
    payload: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime
    run_after: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    retry_count: int = 0
