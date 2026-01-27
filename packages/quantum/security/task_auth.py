import hmac
import hashlib
import os
import time
import ipaddress
from fastapi import Request, HTTPException, Header
from typing import Optional
from packages.quantum.security.masking import sanitize_message

# Configuration
TASK_SIGNING_SECRET = os.getenv("TASK_SIGNING_SECRET")
TASK_TTL_SECONDS = int(os.getenv("TASK_TTL_SECONDS", "300"))
TASK_ALLOWLIST_CIDRS = os.getenv("TASK_ALLOWLIST_CIDRS", "") # Comma separated

# Pre-parse allowlist to avoid overhead per request
ALLOWED_NETWORKS = []
if TASK_ALLOWLIST_CIDRS:
    try:
        # Use strict=False to allow host bits in CIDR (e.g. 192.168.1.10/24 -> 192.168.1.0/24)
        ALLOWED_NETWORKS = [ipaddress.ip_network(c.strip(), strict=False) for c in TASK_ALLOWLIST_CIDRS.split(",") if c.strip()]
    except ValueError as e:
        # CRITICAL: Do not fail open. If config is invalid, we must prevent startup.
        raise ValueError(f"CRITICAL: Invalid TASK_ALLOWLIST_CIDRS configuration: {e}")

async def verify_internal_task_request(
    request: Request,
    x_task_signature: str = Header(..., alias="X-Task-Signature"),
    x_task_timestamp: str = Header(..., alias="X-Task-Timestamp"),
    x_task_key_id: Optional[str] = Header(None, alias="X-Task-Key-Id")
):
    """
    Verifies that the request is a valid internal task request.
    1. Checks Timestamp validity (TTL).
    2. Recomputes HMAC-SHA256 signature and compares constant-time.
    3. (Optional) Checks IP Allowlist.
    """

    if not TASK_SIGNING_SECRET:
        # Fail safe: if secret not configured, reject all internal tasks
        print("🚨 Internal Task Rejected: TASK_SIGNING_SECRET not configured.")
        raise HTTPException(status_code=503, detail="Task system not configured")

    # 1. Timestamp Check
    try:
        timestamp = int(x_task_timestamp)
        now = int(time.time())
        if abs(now - timestamp) > TASK_TTL_SECONDS:
            raise HTTPException(status_code=401, detail="Request expired")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid timestamp format")

    # 2. Signature Verification
    # Format: v1:{timestamp}:{method}:{path}:{body_hash}
    body_bytes = await request.body()
    body_hash = hashlib.sha256(body_bytes).hexdigest()
    path = request.url.path
    method = request.method

    payload = f"v1:{timestamp}:{method}:{path}:{body_hash}"

    expected_signature = hmac.new(
        TASK_SIGNING_SECRET.encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, x_task_signature):
        # SECURITY: Do not log the expected signature, as it allows signature forgery if logs are compromised.
        sanitized_payload = sanitize_message(payload)
        print(f"🚨 Invalid Task Signature. Got: {x_task_signature}, Payload: {sanitized_payload}")
        raise HTTPException(status_code=401, detail="Invalid signature")

    # 3. IP Allowlist (Optional)
    # Check if configured (even if empty list was result of empty string logic above, though empty string skips block)
    if TASK_ALLOWLIST_CIDRS:
        if not ALLOWED_NETWORKS:
             # Should be caught by startup check, but double safety
             print("🚨 Allowlist configured but empty/invalid runtime state. Denying access.")
             raise HTTPException(status_code=503, detail="Security Configuration Error")

        client_ip = request.client.host
        try:
            ip = ipaddress.ip_address(client_ip)
            if not any(ip in net for net in ALLOWED_NETWORKS):
                print(f"🚨 IP {client_ip} blocked by Allowlist.")
                raise HTTPException(status_code=403, detail="IP not allowed")
        except ValueError:
            print(f"🚨 Invalid Client IP: {client_ip}")
            raise HTTPException(status_code=400, detail="Invalid IP format")

    return True
