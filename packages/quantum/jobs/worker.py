import os
import sys
import socket
import time
import json
import traceback
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Callable

# Add package root to path to ensure imports work when run as script
# Assuming this script is at packages/quantum/jobs/worker.py
# We need to add the root of the repo (3 levels up)
current_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from packages.quantum.jobs.db import (
    create_supabase_admin_client,
    claim_job_run,
    complete_job_run,
    requeue_job_run,
    dead_letter_job_run
)
from packages.quantum.jobs.backoff import backoff_seconds
from packages.quantum.jobs.registry import discover_handlers

class RetryableJobError(Exception):
    """Exception raised when a job fails but should be retried."""
    pass

class PermanentJobError(Exception):
    """Exception raised when a job fails and should not be retried."""
    pass

def test_job_handler(payload: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """A simple test handler."""
    print(f"Executing test_job with payload: {payload}")
    return {"status": "success", "processed_payload": payload}

def format_error_payload(exception: Exception, job_name: str, attempt: int) -> Dict[str, Any]:
    """Formats an exception into the required error payload structure."""
    return {
        "type": type(exception).__name__,
        "message": str(exception),
        "stack": "".join(traceback.format_tb(exception.__traceback__)),
        "ts": datetime.now(timezone.utc).isoformat(),
        "job_name": job_name,
        "attempt": attempt
    }

def main():
    print("Starting Quantum Worker...")

    # Initialize Supabase client
    try:
        client = create_supabase_admin_client()
        print("Supabase client initialized.")
    except Exception as e:
        print(f"Failed to initialize Supabase client: {e}")
        sys.exit(1)

    worker_id = f"{socket.gethostname()}-{os.getpid()}"
    print(f"Worker ID: {worker_id}")

    # Load handlers from registry and add local test handler
    handlers = discover_handlers()
    handlers["test_job"] = test_job_handler
    print(f"Registered handlers: {list(handlers.keys())}")

    print("Worker loop started. Polling for jobs...")
    while True:
        try:
            job = claim_job_run(client, worker_id)

            if not job:
                time.sleep(2)
                continue

            # Assuming job is a dict with keys matching table columns
            # We need: id, job_name, payload, attempt (maybe)
            # Adjust keys based on actual DB schema.
            # Assuming: 'id', 'job_name', 'payload', 'attempt'

            job_id = job.get('id')
            job_name = job.get('job_name')
            payload = job.get('payload', {})
            # If attempt is not in job row, default to 1?
            # The RPC/DB usually tracks attempt count.
            # If claim_job_run increments it, we should get the current attempt.
            attempt = job.get('attempt', 1)

            print(f"Claimed job {job_id}: {job_name} (Attempt {attempt})")

            if job_name not in handlers:
                # Permanent failure: Missing handler
                error = PermanentJobError(f"No handler found for job: {job_name}")
                error_json = format_error_payload(error, job_name, attempt)
                print(f"Dead lettering job {job_id}: Missing handler")
                dead_letter_job_run(client, job_id, error_json)
                continue

            handler = handlers[job_name]

            # Context can include worker info, client, etc.
            context = {
                "worker_id": worker_id,
                "job_id": job_id,
                "attempt": attempt
            }

            try:
                result = handler(payload, context)
                print(f"Job {job_id} completed successfully.")
                complete_job_run(client, job_id, result or {})

            except RetryableJobError as e:
                print(f"Job {job_id} failed (Retryable): {e}")
                backoff = backoff_seconds(attempt)
                run_after = (datetime.now(timezone.utc) + timedelta(seconds=backoff)).isoformat()
                error_json = format_error_payload(e, job_name, attempt)
                requeue_job_run(client, job_id, run_after, error_json)

            except Exception as e:
                # Treat generic exceptions as dead letter or retryable?
                # The prompt says: "on any other exception => dead_letter_job_run with stack trace"
                print(f"Job {job_id} failed (Permanent/Unknown): {e}")
                error_json = format_error_payload(e, job_name, attempt)
                dead_letter_job_run(client, job_id, error_json)

        except KeyboardInterrupt:
            print("Worker stopping...")
            break
        except Exception as outer_e:
            print(f"Unexpected error in worker loop: {outer_e}")
            traceback.print_exc()
            time.sleep(5) # Sleep before retrying loop to avoid tight loop on persistent errors

if __name__ == "__main__":
    main()
