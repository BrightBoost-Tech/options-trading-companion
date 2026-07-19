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
from packages.quantum.security.masking import sanitize_exception, sanitize_message


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
TASK_NONCE_PROTECTION = os.getenv("TASK_NONCE_PROTECTION", "1") == "1"


class NonceStoreUnavailableError(Exception):
    """The nonce store could not be read/written and the request must fail
    CLOSED.

    Distinct from a REPLAY (``check_and_store_nonce`` returns ``False``): a
    store outage is not the caller's fault, so the verifier maps this to a
    503, never a 401. Raising a typed error — instead of fabricating a fresh
    verdict — is the whole point of fail-closed replay protection (H9: a value
    you cannot verify must reject, never fabricate).
    """


def _is_production_mode() -> bool:
    """Canonical production detector.

    Delegates to ``packages.quantum.security.config.is_production()`` — the H13
    single source of truth (production is ``APP_ENV=production`` OR the Railway
    platform signal ``RAILWAY_ENVIRONMENT_NAME`` / ``RAILWAY_ENVIRONMENT``).

    There is deliberately NO second detector here. The pre-fix heuristic keyed
    production off ``ENV=production`` OR ``ENABLE_DEV_AUTH_BYPASS=0``, which
    DIVERGED from ``is_production()`` and mis-classified the production worker
    (which sets ``APP_ENV`` / ``RAILWAY_ENVIRONMENT`` but not ``ENV``) as
    non-production — fail-opening the nonce replay guard within the TTL while
    ``audit_production_security()`` reported healthy (F-A9-1).
    """
    from packages.quantum.security.config import is_production
    return is_production()


def _nonce_outage_fails_closed() -> bool:
    """Whether a nonce-store read/write OUTAGE must REJECT the request.

    Fail-closed is MANDATORY and NON-OVERRIDABLE under canonical production
    (``is_production()``): no environment toggle can make a production worker
    fail open on a nonce-store outage, so replay protection can never silently
    degrade (F-A9-1 / F-A9-2).

    The ONLY fail-open path is a narrow, explicit, dev-only escape hatch that
    is impossible to reach under canonical production BY CONSTRUCTION. ALL of:
      1. ``is_production()`` is False, AND
      2. ``ENABLE_DEV_AUTH_BYPASS=1`` — the explicit dev marker, which
         ``config.validate_security_config()`` HARD-ABORTS at startup in
         production (so it can never co-occur with canonical production), AND
      3. ``TASK_NONCE_FAIL_CLOSED_IN_PROD=0`` — the explicit opt-out.
    must hold. Any weaker combination (production, no dev marker, or the
    opt-out unset) fails CLOSED. This lets a local box run without a Supabase
    nonce store, and nothing else.
    """
    if _is_production_mode():
        return True

    from packages.quantum.security.config import is_dev_bypass_enabled

    dev_escape = (
        is_dev_bypass_enabled()
        and os.getenv("TASK_NONCE_FAIL_CLOSED_IN_PROD", "1") == "0"
    )
    return not dev_escape


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
        True  if nonce is fresh (not seen before), or protection is disabled,
              or the store is down in the narrow dev fail-open mode.
        False if nonce is a REPLAY (already used).

    Raises:
        NonceStoreUnavailableError if the store is unavailable/errored AND the
        context fails CLOSED (``_nonce_outage_fails_closed()`` — always in
        canonical production). The caller maps this to a 503; it NEVER
        fabricates a fresh verdict.

    Behavior:
        - If TASK_NONCE_PROTECTION=0: always returns True (disabled).
        - Store unavailable / non-duplicate error:
            - fail-closed (production, or any non-dev context): raises
              NonceStoreUnavailableError, logs, writes an audit event.
            - dev fail-open (narrow, explicit — see _nonce_outage_fails_closed):
              returns True with a warning.
        - Duplicate/unique/conflict error: returns False (replay).
    """
    if not TASK_NONCE_PROTECTION:
        return True  # Nonce protection disabled

    fail_closed = _nonce_outage_fails_closed()

    client = _get_nonce_client()
    if not client:
        if fail_closed:
            print("🚨 FAIL-CLOSED: Nonce store unavailable - rejecting request")
            _emit_nonce_audit_event(
                nonce=nonce,
                scope=scope,
                event_type="nonce_store_unavailable",
                outcome="rejected",
                reason="Supabase nonce client unavailable in fail-closed mode"
            )
            raise NonceStoreUnavailableError("Nonce store unavailable")
        else:
            print("⚠️ Nonce protection enabled but Supabase unavailable - allowing request (dev fail-open)")
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
            print(f"🚨 FAIL-CLOSED: Nonce store error - rejecting request: {sanitize_exception(e)}")
            _emit_nonce_audit_event(
                nonce=nonce,
                scope=scope,
                event_type="nonce_store_error",
                outcome="rejected",
                reason=str(e)[:200]
            )
            raise NonceStoreUnavailableError("Nonce store error") from e
        else:
            print(f"⚠️ Nonce check error (allowing in dev fail-open): {sanitize_exception(e)}")
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
        print(f"⚠️ Failed to emit nonce audit event: {sanitize_exception(e)}")


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
    try:
        nonce_is_fresh = check_and_store_nonce(x_task_nonce, x_task_scope, timestamp)
    except NonceStoreUnavailableError:
        # Fail-closed: the replay-protection subsystem is down. Reject the
        # request rather than fabricate a pass. An outage is not the caller's
        # fault, so this is a 503 (subsystem unavailable), distinct from a 401
        # replay. The detail carries NO secret and NO store internals.
        print("🚨 FAIL-CLOSED: replay protection unavailable - rejecting request")
        raise HTTPException(status_code=503, detail="Replay protection unavailable")
    if not nonce_is_fresh:
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
