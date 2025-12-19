from fastapi import Header, HTTPException
from typing import Optional
import os
import secrets

async def verify_cron_secret(x_cron_secret: Optional[str] = Header(None)):
    """
    Verifies that the X-Cron-Secret header matches the CRON_SECRET env var.
    Uses constant-time comparison to prevent timing attacks.
    """
    expected_secret = os.getenv("CRON_SECRET")

    if not expected_secret:
        # Configuration error: CRON_SECRET not set on server
        print("Error: CRON_SECRET environment variable not set.")
        raise HTTPException(status_code=500, detail="Server misconfiguration: CRON_SECRET missing")

    if x_cron_secret is None or not secrets.compare_digest(x_cron_secret, expected_secret):
        # Auth failure
        raise HTTPException(status_code=401, detail="Invalid Cron Secret")

    return True
