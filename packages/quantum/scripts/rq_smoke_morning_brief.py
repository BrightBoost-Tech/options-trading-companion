import sys
import os
import asyncio
from datetime import datetime

# Setup path to import from packages.quantum
current_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

# Import the Postgres/Supabase-based enqueue function which is what the system actively uses
from packages.quantum.jobs.db import create_supabase_admin_client
from packages.quantum.jobs.enqueue import enqueue_idempotent

def smoke_test():
    print("Running Smoke Test for Morning Brief (Postgres/Supabase Queue)...")
    try:
        client = create_supabase_admin_client()
    except Exception as e:
        print(f"Failed to create Supabase client: {e}")
        return

    job_name = "morning-brief"
    # Create a unique key to ensure it gets enqueued
    key = f"smoke-test-{datetime.now().timestamp()}"

    # Using a known test user ID from memory/context
    test_user_id = "75ee12ad-b119-4f32-aeea-19b4ef55d587"

    print(f"Enqueueing job: {job_name}")
    print(f"Idempotency Key: {key}")
    print(f"Payload: {{'user_id': '{test_user_id}'}}")

    try:
        job_id = enqueue_idempotent(
            client=client,
            job_name=job_name,
            idempotency_key=key,
            payload={"user_id": test_user_id}
        )
        print(f"Success! Job ID: {job_id}")
        print("The worker (if running) should pick this up and execute 'packages.quantum.jobs.handlers.morning_brief.run'.")
        print("Check 'job_runs' table for status 'completed' and 'trade_suggestions' for new records.")
    except Exception as e:
        print(f"Failed to enqueue: {e}")

if __name__ == "__main__":
    smoke_test()
