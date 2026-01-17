"""
Tests for Security v4: Admin-Only Access Control for /jobs/* endpoints

Tests the admin authentication logic including:
- JWT role claim verification
- Admin user ID allowlist
- Denial for non-admin users
- Audit logging
"""

import pytest
import json
import base64
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi import HTTPException

from packages.quantum.security.admin_auth import (
    verify_admin_access,
    _has_admin_role_claim,
    _parse_admin_user_ids,
    is_admin_user,
    reload_admin_user_ids,
    AdminAuthResult,
    ADMIN_USER_IDS,
)


# =============================================================================
# Test Fixtures
# =============================================================================

def make_jwt(payload: dict) -> str:
    """Create a test JWT with the given payload (no signature verification)."""
    header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).decode().rstrip("=")
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    signature = "test_signature"
    return f"{header}.{body}.{signature}"


@pytest.fixture
def mock_request():
    """Create a mock FastAPI request."""
    request = MagicMock()
    request.url.path = "/jobs/runs"
    request.method = "GET"
    request.client.host = "127.0.0.1"
    return request


# =============================================================================
# JWT Role Claim Tests
# =============================================================================

class TestHasAdminRoleClaim:
    """Test JWT role claim detection."""

    def test_admin_role_in_role_claim(self):
        """JWT with role=admin in root should return True."""
        token = make_jwt({"sub": "user123", "role": "admin"})
        assert _has_admin_role_claim(token) is True

    def test_admin_role_in_app_metadata(self):
        """JWT with role=admin in app_metadata should return True."""
        token = make_jwt({
            "sub": "user123",
            "app_metadata": {"role": "admin"}
        })
        assert _has_admin_role_claim(token) is True

    def test_admin_role_in_user_metadata(self):
        """JWT with role=admin in user_metadata should return True."""
        token = make_jwt({
            "sub": "user123",
            "user_metadata": {"role": "admin"}
        })
        assert _has_admin_role_claim(token) is True

    def test_non_admin_role(self):
        """JWT with role=user should return False."""
        token = make_jwt({"sub": "user123", "role": "user"})
        assert _has_admin_role_claim(token) is False

    def test_no_role_claim(self):
        """JWT without role claim should return False."""
        token = make_jwt({"sub": "user123", "email": "test@example.com"})
        assert _has_admin_role_claim(token) is False

    def test_invalid_token_format(self):
        """Invalid JWT format should return False."""
        assert _has_admin_role_claim("not.a.valid.token") is False
        assert _has_admin_role_claim("invalid") is False
        assert _has_admin_role_claim("") is False


# =============================================================================
# Admin User ID Allowlist Tests
# =============================================================================

class TestAdminUserIdAllowlist:
    """Test admin user ID parsing and checking."""

    def test_parse_single_user_id(self):
        """Parse a single user ID."""
        with patch.dict("os.environ", {"ADMIN_USER_IDS": "uuid-123"}):
            result = _parse_admin_user_ids()
            assert result == {"uuid-123"}

    def test_parse_multiple_user_ids(self):
        """Parse multiple user IDs."""
        with patch.dict("os.environ", {"ADMIN_USER_IDS": "uuid-1,uuid-2,uuid-3"}):
            result = _parse_admin_user_ids()
            assert result == {"uuid-1", "uuid-2", "uuid-3"}

    def test_parse_with_whitespace(self):
        """Whitespace should be trimmed."""
        with patch.dict("os.environ", {"ADMIN_USER_IDS": " uuid-1 , uuid-2 , uuid-3 "}):
            result = _parse_admin_user_ids()
            assert result == {"uuid-1", "uuid-2", "uuid-3"}

    def test_parse_empty(self):
        """Empty string should return empty set."""
        with patch.dict("os.environ", {"ADMIN_USER_IDS": ""}):
            result = _parse_admin_user_ids()
            assert result == set()

    def test_parse_missing_env_var(self):
        """Missing env var should return empty set."""
        with patch.dict("os.environ", {}, clear=True):
            # Remove ADMIN_USER_IDS if it exists
            import os
            os.environ.pop("ADMIN_USER_IDS", None)
            result = _parse_admin_user_ids()
            assert result == set()


# =============================================================================
# Verify Admin Access Tests
# =============================================================================

class TestVerifyAdminAccess:
    """Test the admin verification dependency."""

    @pytest.mark.asyncio
    async def test_admin_via_allowlist(self, mock_request):
        """User in ADMIN_USER_IDS should get admin access."""
        from packages.quantum.security import admin_auth
        import importlib

        with patch.dict("os.environ", {"ADMIN_USER_IDS": "admin-user-123,other-admin"}):
            # Reload to pick up env var
            importlib.reload(admin_auth)

            result = await admin_auth.verify_admin_access(
                request=mock_request,
                user_id="admin-user-123",
                authorization=None
            )

            assert result.is_admin is True
            assert result.user_id == "admin-user-123"
            assert result.admin_reason == "allowlist"

    @pytest.mark.asyncio
    async def test_admin_via_jwt_role_claim(self, mock_request):
        """User with admin role in JWT should get admin access."""
        from packages.quantum.security import admin_auth
        import importlib

        admin_token = make_jwt({"sub": "jwt-admin-user", "role": "admin"})

        with patch.dict("os.environ", {"ADMIN_USER_IDS": ""}):
            importlib.reload(admin_auth)

            result = await admin_auth.verify_admin_access(
                request=mock_request,
                user_id="jwt-admin-user",
                authorization=f"Bearer {admin_token}"
            )

            assert result.is_admin is True
            assert result.user_id == "jwt-admin-user"
            assert result.admin_reason == "role_claim"

    @pytest.mark.asyncio
    async def test_non_admin_user_denied(self, mock_request):
        """Non-admin user should be denied with 403."""
        from packages.quantum.security import admin_auth
        import importlib

        non_admin_token = make_jwt({"sub": "regular-user", "role": "user"})

        with patch.dict("os.environ", {"ADMIN_USER_IDS": "other-admin"}):
            importlib.reload(admin_auth)

            with pytest.raises(HTTPException) as exc_info:
                await admin_auth.verify_admin_access(
                    request=mock_request,
                    user_id="regular-user",
                    authorization=f"Bearer {non_admin_token}"
                )

            assert exc_info.value.status_code == 403
            assert "admin" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_unauthenticated_user_denied(self, mock_request):
        """Unauthenticated user should be denied with 401."""
        from packages.quantum.security import admin_auth

        with pytest.raises(HTTPException) as exc_info:
            await admin_auth.verify_admin_access(
                request=mock_request,
                user_id=None,
                authorization=None
            )

        assert exc_info.value.status_code == 401
        assert "authentication" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_allowlist_takes_precedence(self, mock_request):
        """User in allowlist should get access even without admin role in JWT."""
        from packages.quantum.security import admin_auth
        import importlib

        # Token without admin role
        non_admin_token = make_jwt({"sub": "allowlist-user", "role": "user"})

        with patch.dict("os.environ", {"ADMIN_USER_IDS": "allowlist-user"}):
            importlib.reload(admin_auth)

            result = await admin_auth.verify_admin_access(
                request=mock_request,
                user_id="allowlist-user",
                authorization=f"Bearer {non_admin_token}"
            )

            # Should succeed via allowlist, not JWT
            assert result.is_admin is True
            assert result.admin_reason == "allowlist"


# =============================================================================
# CRON_SECRET Removal Tests
# =============================================================================

class TestCronSecretRemoved:
    """Verify CRON_SECRET is not accepted for admin access."""

    @pytest.mark.asyncio
    async def test_cron_secret_header_not_accepted(self, mock_request):
        """X-Cron-Secret header should NOT grant admin access."""
        from packages.quantum.security import admin_auth
        import importlib

        with patch.dict("os.environ", {
            "ADMIN_USER_IDS": "",
            "CRON_SECRET": "test-cron-secret"
        }):
            importlib.reload(admin_auth)

            # Try with CRON_SECRET but no user_id
            with pytest.raises(HTTPException) as exc_info:
                await admin_auth.verify_admin_access(
                    request=mock_request,
                    user_id=None,  # No authenticated user
                    authorization=None
                )

            # Should fail because CRON_SECRET doesn't grant access
            assert exc_info.value.status_code == 401


# =============================================================================
# Audit Logging Tests
# =============================================================================

class TestAuditLogging:
    """Test audit logging functionality."""

    @pytest.mark.asyncio
    async def test_admin_access_logs_audit_entry(self, mock_request, capsys):
        """Admin access should log an audit entry."""
        from packages.quantum.security import admin_auth
        import importlib

        with patch.dict("os.environ", {"ADMIN_USER_IDS": "audited-admin"}):
            importlib.reload(admin_auth)

            await admin_auth.verify_admin_access(
                request=mock_request,
                user_id="audited-admin",
                authorization=None
            )

            captured = capsys.readouterr()
            assert "[AUDIT]" in captured.out
            assert "audited-admin" in captured.out
            assert "access_granted" in captured.out

    @pytest.mark.asyncio
    async def test_denied_access_logs_audit_entry(self, mock_request, capsys):
        """Denied access should also log an audit entry."""
        from packages.quantum.security import admin_auth
        import importlib

        with patch.dict("os.environ", {"ADMIN_USER_IDS": ""}):
            importlib.reload(admin_auth)

            with pytest.raises(HTTPException):
                await admin_auth.verify_admin_access(
                    request=mock_request,
                    user_id="denied-user",
                    authorization=None
                )

            captured = capsys.readouterr()
            assert "[AUDIT]" in captured.out
            assert "denied-user" in captured.out
            assert "access_denied" in captured.out

    def test_mutation_logging(self, mock_request, capsys):
        """log_admin_mutation should produce structured log."""
        from packages.quantum.security.admin_auth import log_admin_mutation

        log_admin_mutation(
            request=mock_request,
            user_id="mutation-admin",
            action="retry",
            resource_type="job_run",
            resource_id="job-123",
            details={"job_name": "test_job"}
        )

        captured = capsys.readouterr()
        assert "[AUDIT]" in captured.out
        assert "mutation-admin" in captured.out
        assert "retry" in captured.out
        assert "job_run" in captured.out
        assert "job-123" in captured.out


# =============================================================================
# Integration Tests
# =============================================================================

class TestJobsEndpointsSecurity:
    """Test that /jobs/* endpoints enforce admin access."""

    def test_endpoints_import_admin_auth(self):
        """Jobs endpoints should import admin_auth, not cron_auth."""
        # Read the endpoints file and verify imports
        import inspect
        from packages.quantum.jobs import endpoints

        source = inspect.getsource(endpoints)

        # Should use admin_auth
        assert "verify_admin_access" in source
        assert "AdminAuthResult" in source

        # Should NOT use the old cron auth
        assert "verify_cron_secret" not in source
        assert "get_authorized_actor" not in source
