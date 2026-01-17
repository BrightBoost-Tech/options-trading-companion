"""
Security v4: Admin-Only Access Control for /jobs/* endpoints

This module provides strict admin-only access control with:
- JWT role claim verification (role=admin)
- Explicit admin user ID allowlist (ADMIN_USER_IDS env var)
- Audit logging for all admin actions
- No fallback to CRON_SECRET (removed privilege escalation risk)

Admin access is granted if ANY of:
1. JWT contains `role: "admin"` or `app_metadata.role: "admin"`
2. User ID is in ADMIN_USER_IDS allowlist

This replaces the insecure get_authorized_actor that allowed CRON_SECRET.
"""

import os
import json
from typing import Optional, List, Set
from datetime import datetime, timezone
from functools import lru_cache

from fastapi import Request, HTTPException, Depends, Header
from pydantic import BaseModel

from packages.quantum.security import get_current_user


# =============================================================================
# Configuration
# =============================================================================

def _parse_admin_user_ids() -> Set[str]:
    """
    Parse ADMIN_USER_IDS from environment.
    Format: Comma-separated list of user IDs (UUIDs).
    Example: "uuid1,uuid2,uuid3"
    """
    raw = os.getenv("ADMIN_USER_IDS", "")
    if not raw:
        return set()
    return {uid.strip() for uid in raw.split(",") if uid.strip()}


# Cache the admin user IDs at startup
ADMIN_USER_IDS: Set[str] = _parse_admin_user_ids()


# =============================================================================
# Admin Verification
# =============================================================================

class AdminAuthResult(BaseModel):
    """Result of admin authentication."""
    user_id: str
    is_admin: bool
    admin_reason: str  # "role_claim", "allowlist", or "denied"


async def verify_admin_access(
    request: Request,
    user_id: Optional[str] = Depends(get_current_user),
    authorization: Optional[str] = Header(None)
) -> AdminAuthResult:
    """
    Verify the current user has admin access.

    Admin access is granted if:
    1. JWT contains role=admin (in `role` claim or `app_metadata.role`)
    2. User ID is in ADMIN_USER_IDS environment variable

    Raises:
        HTTPException 401 if not authenticated
        HTTPException 403 if authenticated but not admin

    Returns:
        AdminAuthResult with user_id and admin status
    """
    # Must be authenticated first
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Provide a valid JWT."
        )

    # Check admin allowlist first (fast path)
    if user_id in ADMIN_USER_IDS:
        _log_admin_action(request, user_id, "allowlist", "access_granted")
        return AdminAuthResult(
            user_id=user_id,
            is_admin=True,
            admin_reason="allowlist"
        )

    # Check JWT role claim
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        if _has_admin_role_claim(token):
            _log_admin_action(request, user_id, "role_claim", "access_granted")
            return AdminAuthResult(
                user_id=user_id,
                is_admin=True,
                admin_reason="role_claim"
            )

    # Not an admin - deny access
    _log_admin_action(request, user_id, "denied", "access_denied")
    raise HTTPException(
        status_code=403,
        detail="Admin access required. Your account does not have admin privileges."
    )


def _has_admin_role_claim(token: str) -> bool:
    """
    Check if JWT has admin role claim.

    Checks:
    - `role` claim == "admin"
    - `app_metadata.role` == "admin"
    - `user_metadata.role` == "admin"
    """
    try:
        import base64

        # JWT has 3 parts: header.payload.signature
        parts = token.split(".")
        if len(parts) != 3:
            return False

        # Decode payload (second part)
        # Add padding if needed
        payload_b64 = parts[1]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding

        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        payload = json.loads(payload_bytes)

        # Check role claim
        if payload.get("role") == "admin":
            return True

        # Check app_metadata.role
        app_metadata = payload.get("app_metadata", {})
        if isinstance(app_metadata, dict) and app_metadata.get("role") == "admin":
            return True

        # Check user_metadata.role
        user_metadata = payload.get("user_metadata", {})
        if isinstance(user_metadata, dict) and user_metadata.get("role") == "admin":
            return True

        return False

    except Exception:
        # If we can't decode the token, assume not admin
        return False


# =============================================================================
# Audit Logging
# =============================================================================

def _log_admin_action(request: Request, user_id: str, reason: str, action: str):
    """
    Log admin access attempt for audit trail.

    In production, this would write to:
    - Structured logging (JSON to stdout for aggregation)
    - Audit table in database
    - Security monitoring system

    For now, we print structured JSON to stdout.
    """
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": "admin_access",
        "user_id": user_id,
        "action": action,
        "reason": reason,
        "path": str(request.url.path),
        "method": request.method,
        "client_ip": request.client.host if request.client else "unknown",
    }
    print(f"[AUDIT] {json.dumps(log_entry)}")


def log_admin_mutation(
    request: Request,
    user_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
    details: Optional[dict] = None
):
    """
    Log an admin mutation (create, update, delete) for audit trail.

    Args:
        request: FastAPI request
        user_id: User performing the action
        action: Action type (create, update, delete, retry)
        resource_type: Type of resource (job_run, etc.)
        resource_id: ID of the resource being modified
        details: Optional additional details
    """
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": "admin_mutation",
        "user_id": user_id,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "path": str(request.url.path),
        "method": request.method,
        "client_ip": request.client.host if request.client else "unknown",
        "details": details,
    }
    print(f"[AUDIT] {json.dumps(log_entry)}")


# =============================================================================
# Utility Functions
# =============================================================================

def is_admin_user(user_id: str) -> bool:
    """Check if a user ID is in the admin allowlist."""
    return user_id in ADMIN_USER_IDS


def reload_admin_user_ids():
    """Reload admin user IDs from environment. Useful for testing."""
    global ADMIN_USER_IDS
    ADMIN_USER_IDS = _parse_admin_user_ids()
