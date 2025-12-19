from typing import Optional, Dict, Any
from datetime import datetime
from packages.quantum.jobs.db import create_supabase_admin_client, complete_job_run, requeue_job_run, dead_letter_job_run

class JobRunStore:
    def __init__(self):
        self.client = create_supabase_admin_client()

    def create_or_get(self, job_name: str, idempotency_key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Creates a new job run if it doesn't exist (based on job_name + idempotency_key).
        Returns the job run record.
        """
        # Try to find existing first
        existing = self.client.table("job_runs")\
            .select("*")\
            .eq("job_name", job_name)\
            .eq("idempotency_key", idempotency_key)\
            .maybe_single()\
            .execute()

        if existing.data:
            return existing.data

        # Attempt to insert
        try:
            data = {
                "job_name": job_name,
                "idempotency_key": idempotency_key,
                "payload": payload,
                "status": "queued"
            }
            # upsert with ignore_duplicates=True will do nothing if conflict
            res = self.client.table("job_runs").upsert(
                data, on_conflict="job_name,idempotency_key", ignore_duplicates=True
            ).select().execute()

            if res.data:
                return res.data[0]

            # If we are here, it means duplicate existed and was ignored. Fetch again.
            existing_retry = self.client.table("job_runs")\
                .select("*")\
                .eq("job_name", job_name)\
                .eq("idempotency_key", idempotency_key)\
                .maybe_single()\
                .execute()
            return existing_retry.data

        except Exception as e:
            # Fallback for errors
            print(f"Error in create_or_get: {e}")
            raise e

    def get_job(self, job_run_id: str) -> Optional[Dict[str, Any]]:
        res = self.client.table("job_runs").select("*").eq("id", job_run_id).maybe_single().execute()
        return res.data

    def mark_running(self, job_run_id: str, worker_id: str) -> None:
        """
        Marks a specific job run as running, incrementing attempt count.
        """
        # Fetch current attempt to increment
        job = self.get_job(job_run_id)
        if not job:
            return

        new_attempt = (job.get("attempt") or 0) + 1

        self.client.table("job_runs").update({
            "status": "running",
            "locked_by": worker_id,
            "locked_at": "now()",
            "started_at": "now()",
            "attempt": new_attempt
        }).eq("id", job_run_id).execute()

    def mark_succeeded(self, job_run_id: str, result: Dict[str, Any]) -> None:
        complete_job_run(self.client, job_run_id, result)

    def mark_retryable(self, job_run_id: str, error: Dict[str, Any], run_after: datetime) -> None:
        requeue_job_run(self.client, job_run_id, run_after.isoformat(), error)

    def mark_dead_letter(self, job_run_id: str, error: Dict[str, Any]) -> None:
        dead_letter_job_run(self.client, job_run_id, error)
