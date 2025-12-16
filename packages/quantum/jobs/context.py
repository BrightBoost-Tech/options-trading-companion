from dataclasses import dataclass
from typing import Optional
from datetime import datetime

@dataclass
class JobContext:
    job_run_id: str
    job_name: str
    idempotency_key: str
    attempt: int
    max_attempts: int
    worker_id: str
    started_at: Optional[datetime] = None
