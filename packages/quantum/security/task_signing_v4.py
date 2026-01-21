"""
Security v4: HMAC Request Signing for /tasks/* endpoints

This module provides scoped HMAC-signed request verification with:
- Timestamp + nonce replay protection
- Key rotation support via TASK_SIGNING_KEYS
- Scope enforcement per endpoint
- Legacy CRON_SECRET fallback (gated by ALLOW_LEGACY_CRON_SECRET=1)

Signature payload format (v4):
  v4:{ts}:{nonce}:{method}:{path}:{body_hash}:{scope}

Headers:
  X-Task-Key-Id (optional): Key ID for rotation support
  X-Task-Ts (required): Unix timestamp in seconds
  X-Task-Nonce (required): Unique nonce for replay protection
  X-Task-Scope (required): Scope string (e.g., "tasks:suggestions_open")
  X-Task-Signature (required): HMAC-SHA256 signature
"""

import hmac
import hashlib
import os
import time
import secrets
from typing import Optional, Dict, Callable
from functools import wraps

from fastapi import Request, HTTPException, Header, Depends
from pydantic import BaseModel


# =============================================================================
# Configuration
# =============================================================================

# TTL for request timestamps (reuse existing or new)
TASK_V4_TTL_SECONDS = int(os.getenv("TASK_V4_TTL_SECONDS", os.getenv("TASK_TTL_SECONDS", "300")))

# Key rotation support: "kid1:secret1,kid2:secret2"
TASK_SIGNING_KEYS_RAW = os.getenv("TASK_SIGNING_KEYS", "")

# Fallback to single secret
TASK_SIGNING_SECRET = os.getenv("TASK_SIGNING_SECRET")

# Legacy CRON_SECRET support (transition period)
ALLOW_LEGACY_CRON_SECRET = os.getenv("ALLOW_LEGACY_CRON_SECRET", "0") == "1"
CRON_SECRET = os.getenv("CRON_SECRET")

# Nonce replay protection (requires Supabase)
TASK_NONCE_PROTECTION = os.getenv("TASK_NONCE_PROTECTION", "0") == "1"

# Fail-closed mode for production: reject requests if nonce store unavailable
# Default "1" in production for safety
TASK_NONCE_FAIL_CLOSED_IN_PROD = os.getenv("TASK_NONCE_FAIL_CLOSED_IN_PROD", "1") == "1"


def _is_production_mode() -> bool:
    """
    Check if running in production mode.

    Production if:
    - ENV=production OR
    - ENABLE_DEV_AUTH_BYPASS=0 (explicitly disabled)

    Dev mode if:
    - ENABLE_DEV_AUTH_BYPASS=1 (default in dev)
    """
    env = os.getenv("ENV", "").lower()
    if env == "production":
        return True

    # If dev auth bypass is explicitly disabled, treat as production
    dev_bypass = os.getenv("ENABLE_DEV_AUTH_BYPASS", "1")
    if dev_bypass == "0":
        return True

    return False


# =============================================================================
# Key Management
# =============================================================================

def parse_signing_keys() -> Dict[str, str]:
    """
    Parse TASK_SIGNING_KEYS into a dict of {kid: secret}.
    Format: "kid1:secret1,kid2:secret2"
    """
    keys = {}
    if TASK_SIGNING_KEYS_RAW:
        for entry in TASK_SIGNING_KEYS_RAW.split(","):
            entry = entry.strip()
            if ":" in entry:
                kid, secret = entry.split(":", 1)
                keys[kid.strip()] = secret.strip()
    return keys


SIGNING_KEYS = parse_signing_keys()


def get_signing_secret(key_id: Optional[str] = None) -> Optional[str]:
    """
    Get signing secret by key ID, or fallback to default.

    Priority:
    1. If key_id provided and exists in SIGNING_KEYS -> return that
    2. If SIGNING_KEYS has entries but key_id not found -> return None (fail)
    3. If no SIGNING_KEYS -> fallback to TASK_SIGNING_SECRET
    """
    if key_id and SIGNING_KEYS:
        return SIGNING_KEYS.get(key_id)

    if SIGNING_KEYS:
        # Keys configured but no key_id provided - use first key as default
        return next(iter(SIGNING_KEYS.values()), None)

    # Fallback to single secret
    return TASK_SIGNING_SECRET


# =============================================================================
# Nonce Store (Supabase-backed)
# =============================================================================

_nonce_client = None


def _get_nonce_client():
    """Lazy-load Supabase admin client for nonce storage."""
    global _nonce_client
    if _nonce_client is None:
        try:
            from packages.quantum.security.secrets_provider import SecretsProvider
            from supabase import create_client

            provider = SecretsProvider()
            secrets = provider.get_supabase_secrets()
            if secrets.url and secrets.service_role_key:
                _nonce_client = create_client(secrets.url, secrets.service_role_key)
        except Exception as e:
            print(f"⚠️ Failed to initialize nonce store: {e}")
    return _nonce_client


def check_and_store_nonce(nonce: str, scope: str, timestamp: int) -> bool:
    """
    Check if nonce has been used; if not, store it.

    Returns:
        True if nonce is fresh (not seen before)
        False if nonce is a replay (already used) OR store unavailable in fail-closed mode

    Behavior:
        - If TASK_NONCE_PROTECTION=0: Always returns True (disabled)
        - If store unavailable:
            - Production (fail-closed): Returns False, logs error, writes audit event
            - Dev mode (fail-open): Returns True with warning
        - If store error (non-duplicate):
            - Production (fail-closed): Returns False
            - Dev mode (fail-open): Returns True with warning
    """
    if not TASK_NONCE_PROTECTION:
        return True  # Nonce protection disabled

    is_prod = _is_production_mode()
    fail_closed = TASK_NONCE_FAIL_CLOSED_IN_PROD and is_prod

    client = _get_nonce_client()
    if not client:
        if fail_closed:
            print("🚨 FAIL-CLOSED: Nonce store unavailable in production - rejecting request")
            _emit_nonce_audit_event(
                nonce=nonce,
                scope=scope,
                event_type="nonce_store_unavailable",
                outcome="rejected",
                reason="Supabase client unavailable in fail-closed production mode"
            )
            return False
        else:
            print("⚠️ Nonce protection enabled but Supabase unavailable - allowing request (dev mode)")
            return True

    try:
        # Calculate expiry (TTL from now)
        from datetime import datetime, timezone, timedelta
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=TASK_V4_TTL_SECONDS * 2)

        # Insert nonce - conflict means replay
        client.table("task_nonces").insert({
            "nonce": nonce,
            "scope": scope,
            "ts": timestamp,
            "expires_at": expires_at.isoformat()
        }).execute()

        return True  # Insert succeeded - nonce is fresh

    except Exception as e:
        error_str = str(e).lower()
        if "duplicate" in error_str or "unique" in error_str or "conflict" in error_str:
            return False  # Replay detected

        # Other errors - behavior depends on mode
        if fail_closed:
            print(f"🚨 FAIL-CLOSED: Nonce store error in production - rejecting request: {e}")
            _emit_nonce_audit_event(
                nonce=nonce,
                scope=scope,
                event_type="nonce_store_error",
                outcome="rejected",
                reason=str(e)[:200]
            )
            return False
        else:
            print(f"⚠️ Nonce check error (allowing in dev mode): {e}")
            return True


def _emit_nonce_audit_event(
    nonce: str,
    scope: str,
    event_type: str,
    outcome: str,
    reason: str
) -> None:
    """
    Emit audit event for nonce protection failures.

    Best-effort: failures to emit don't block the main flow.
    """
    try:
        client = _get_nonce_client()
        if not client:
            return

        from datetime import datetime, timezone

        client.table("decision_audit_events").insert({
            "event_name": f"nonce.{event_type}",
            "payload": {
                "nonce": nonce[:32] + "..." if len(nonce) > 32 else nonce,
                "scope": scope,
                "outcome": outcome,
                "reason": reason,
                "fail_closed_mode": True,
            },
            "created_at": datetime.now(timezone.utc).isoformat()
        }).execute()
    except Exception as e:
        # Best effort - don't block on audit failures
        print(f"⚠️ Failed to emit nonce audit event: {e}")


# =============================================================================
# Signature Verification
# =============================================================================

class TaskSignatureResult(BaseModel):
    """Result of signature verification."""
    valid: bool
    actor: str  # "v4:{scope}" or "legacy:cron" or "denied"
    scope: str
    key_id: Optional[str] = None
    legacy_fallback: bool = False


def compute_signature(
    secret: str,
    timestamp: int,
    nonce: str,
    method: str,
    path: str,
    body_hash: str,
    scope: str
) -> str:
    """Compute v4 HMAC-SHA256 signature."""
    payload = f"v4:{timestamp}:{nonce}:{method}:{path}:{body_hash}:{scope}"
    return hmac.new(
        secret.encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()


async def _verify_v4_signature(
    request: Request,
    required_scope: str,
    x_task_key_id: Optional[str],
    x_task_ts: str,
    x_task_nonce: str,
    x_task_scope: str,
    x_task_signature: str
) -> TaskSignatureResult:
    """Internal v4 signature verification logic."""

    # 1. Get signing secret
    secret = get_signing_secret(x_task_key_id)
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="Task signing not configured" if not SIGNING_KEYS else "Unknown key ID"
        )

    # 2. Validate timestamp
    try:
        timestamp = int(x_task_ts)
        now = int(time.time())
        if abs(now - timestamp) > TASK_V4_TTL_SECONDS:
            raise HTTPException(status_code=401, detail="Request expired")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid timestamp format")

    # 3. Validate scope
    if x_task_scope != required_scope:
        raise HTTPException(
            status_code=403,
            detail=f"Scope mismatch: got '{x_task_scope}', required '{required_scope}'"
        )

    # 4. Check for :all_users suffix if user_id not in payload
    # This is enforced at payload validation level, not here

    # 5. Compute expected signature
    body_bytes = await request.body()
    body_hash = hashlib.sha256(body_bytes).hexdigest()
    path = request.url.path
    method = request.method

    expected_sig = compute_signature(
        secret, timestamp, x_task_nonce, method, path, body_hash, x_task_scope
    )

    # 6. Constant-time compare
    if not hmac.compare_digest(expected_sig, x_task_signature):
        print(f"🚨 Invalid v4 signature for scope {x_task_scope}")
        raise HTTPException(status_code=401, detail="Invalid signature")

    # 7. Nonce replay check
    if not check_and_store_nonce(x_task_nonce, x_task_scope, timestamp):
        print(f"🚨 Nonce replay detected: {x_task_nonce}")
        raise HTTPException(status_code=401, detail="Request replay detected")

    return TaskSignatureResult(
        valid=True,
        actor=f"v4:{x_task_scope}",
        scope=x_task_scope,
        key_id=x_task_key_id,
        legacy_fallback=False
    )


async def _verify_legacy_cron_secret(x_cron_secret: str) -> TaskSignatureResult:
    """Verify legacy CRON_SECRET (transition period only)."""
    if not ALLOW_LEGACY_CRON_SECRET:
        raise HTTPException(
            status_code=401,
            detail="Legacy CRON_SECRET authentication disabled. Use v4 signing."
        )

    if not CRON_SECRET:
        raise HTTPException(status_code=500, detail="CRON_SECRET not configured")

    if not secrets.compare_digest(x_cron_secret, CRON_SECRET):
        raise HTTPException(status_code=401, detail="Invalid Cron Secret")

    print("⚠️ DEPRECATED: Legacy CRON_SECRET used. Migrate to v4 signed requests.")

    return TaskSignatureResult(
        valid=True,
        actor="legacy:cron",
        scope="*",  # Legacy has wildcard scope
        legacy_fallback=True
    )


# =============================================================================
# FastAPI Dependency Factory
# =============================================================================

def verify_task_signature(required_scope: str):
    """
    Create a FastAPI dependency that verifies task request signatures.

    Usage:
        @router.post("/tasks/suggestions/open")
        async def task_suggestions_open(
            auth: TaskSignatureResult = Depends(verify_task_signature("tasks:suggestions_open"))
        ):
            ...
    """
    async def _dependency(
        request: Request,
        x_task_key_id: Optional[str] = Header(None, alias="X-Task-Key-Id"),
        x_task_ts: Optional[str] = Header(None, alias="X-Task-Ts"),
        x_task_nonce: Optional[str] = Header(None, alias="X-Task-Nonce"),
        x_task_scope: Optional[str] = Header(None, alias="X-Task-Scope"),
        x_task_signature: Optional[str] = Header(None, alias="X-Task-Signature"),
        x_cron_secret: Optional[str] = Header(None, alias="X-Cron-Secret")
    ) -> TaskSignatureResult:

        # Check for v4 headers
        has_v4_headers = all([x_task_ts, x_task_nonce, x_task_scope, x_task_signature])

        if has_v4_headers:
            return await _verify_v4_signature(
                request, required_scope,
                x_task_key_id, x_task_ts, x_task_nonce, x_task_scope, x_task_signature
            )

        # Fallback to legacy CRON_SECRET
        if x_cron_secret:
            return await _verify_legacy_cron_secret(x_cron_secret)

        # No valid auth
        raise HTTPException(
            status_code=401,
            detail="Missing authentication headers. Provide X-Task-* headers or X-Cron-Secret."
        )

    return _dependency


# =============================================================================
# Client-side Signing Helper
# =============================================================================

def sign_task_request(
    method: str,
    path: str,
    body: bytes,
    scope: str,
    secret: Optional[str] = None,
    key_id: Optional[str] = None
) -> Dict[str, str]:
    """
    Generate signed headers for a task request.

    Args:
        method: HTTP method (GET, POST, etc.)
        path: Request path (e.g., "/tasks/suggestions/open")
        body: Request body bytes
        scope: Required scope (e.g., "tasks:suggestions_open")
        secret: Signing secret (defaults to TASK_SIGNING_SECRET)
        key_id: Key ID for rotation (optional)

    Returns:
        Dict of headers to add to the request
    """
    if secret is None:
        secret = get_signing_secret(key_id)

    if not secret:
        raise ValueError("No signing secret available")

    timestamp = int(time.time())
    nonce = secrets.token_hex(16)
    body_hash = hashlib.sha256(body).hexdigest()

    signature = compute_signature(secret, timestamp, nonce, method, path, body_hash, scope)

    headers = {
        "X-Task-Ts": str(timestamp),
        "X-Task-Nonce": nonce,
        "X-Task-Scope": scope,
        "X-Task-Signature": signature
    }

    if key_id:
        headers["X-Task-Key-Id"] = key_id

    return headers
