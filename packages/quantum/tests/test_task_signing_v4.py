"""
Tests for Security v4: HMAC Request Signing for /tasks/* endpoints

Tests the signing and verification logic including:
- Valid signature verification
- Timestamp expiry
- Scope enforcement
- Key rotation
- Legacy CRON_SECRET fallback
- Nonce replay protection (mocked)
"""

import pytest
import time
import hmac
import hashlib
import secrets
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi import HTTPException
from fastapi.testclient import TestClient

from packages.quantum.security.task_signing_v4 import (
    compute_signature,
    sign_task_request,
    verify_task_signature,
    parse_signing_keys,
    get_signing_secret,
    check_and_store_nonce,
    TaskSignatureResult,
    TASK_V4_TTL_SECONDS,
)


# =============================================================================
# Signature Computation Tests
# =============================================================================

class TestComputeSignature:
    """Test the HMAC signature computation."""

    def test_compute_signature_deterministic(self):
        """Same inputs should produce same signature."""
        secret = "test-secret-123"
        ts = 1704067200
        nonce = "abc123"
        method = "POST"
        path = "/tasks/suggestions/open"
        body_hash = hashlib.sha256(b'{"foo":"bar"}').hexdigest()
        scope = "tasks:suggestions_open"

        sig1 = compute_signature(secret, ts, nonce, method, path, body_hash, scope)
        sig2 = compute_signature(secret, ts, nonce, method, path, body_hash, scope)

        assert sig1 == sig2
        assert len(sig1) == 64  # SHA256 hex digest

    def test_compute_signature_varies_with_secret(self):
        """Different secrets should produce different signatures."""
        ts = 1704067200
        nonce = "abc123"
        method = "POST"
        path = "/tasks/test"
        body_hash = hashlib.sha256(b"").hexdigest()
        scope = "tasks:test"

        sig1 = compute_signature("secret-1", ts, nonce, method, path, body_hash, scope)
        sig2 = compute_signature("secret-2", ts, nonce, method, path, body_hash, scope)

        assert sig1 != sig2

    def test_compute_signature_varies_with_timestamp(self):
        """Different timestamps should produce different signatures."""
        secret = "test-secret"
        nonce = "abc123"
        method = "POST"
        path = "/tasks/test"
        body_hash = hashlib.sha256(b"").hexdigest()
        scope = "tasks:test"

        sig1 = compute_signature(secret, 1704067200, nonce, method, path, body_hash, scope)
        sig2 = compute_signature(secret, 1704067201, nonce, method, path, body_hash, scope)

        assert sig1 != sig2

    def test_compute_signature_varies_with_scope(self):
        """Different scopes should produce different signatures."""
        secret = "test-secret"
        ts = 1704067200
        nonce = "abc123"
        method = "POST"
        path = "/tasks/test"
        body_hash = hashlib.sha256(b"").hexdigest()

        sig1 = compute_signature(secret, ts, nonce, method, path, body_hash, "tasks:a")
        sig2 = compute_signature(secret, ts, nonce, method, path, body_hash, "tasks:b")

        assert sig1 != sig2


# =============================================================================
# Client-side Signing Helper Tests
# =============================================================================

class TestSignTaskRequest:
    """Test the client-side signing helper."""

    @patch.dict("os.environ", {"TASK_SIGNING_SECRET": "test-secret-456"})
    def test_sign_task_request_produces_headers(self):
        """sign_task_request should return all required headers."""
        # Need to reload the module to pick up env var
        from packages.quantum.security import task_signing_v4
        import importlib
        importlib.reload(task_signing_v4)

        headers = task_signing_v4.sign_task_request(
            method="POST",
            path="/tasks/suggestions/open",
            body=b'{"strategy_name": "test"}',
            scope="tasks:suggestions_open"
        )

        assert "X-Task-Ts" in headers
        assert "X-Task-Nonce" in headers
        assert "X-Task-Scope" in headers
        assert "X-Task-Signature" in headers
        assert headers["X-Task-Scope"] == "tasks:suggestions_open"
        assert len(headers["X-Task-Nonce"]) == 32  # 16 bytes hex

    @patch.dict("os.environ", {"TASK_SIGNING_SECRET": "test-secret-456"})
    def test_sign_task_request_timestamp_is_recent(self):
        """Timestamp should be within a few seconds of now."""
        from packages.quantum.security import task_signing_v4
        import importlib
        importlib.reload(task_signing_v4)

        before = int(time.time())
        headers = task_signing_v4.sign_task_request(
            method="POST",
            path="/tasks/test",
            body=b"",
            scope="tasks:test"
        )
        after = int(time.time())

        ts = int(headers["X-Task-Ts"])
        assert before <= ts <= after


# =============================================================================
# Key Management Tests
# =============================================================================

class TestKeyManagement:
    """Test key parsing and rotation support."""

    def test_parse_signing_keys_single(self):
        """Parse a single key."""
        with patch.dict("os.environ", {"TASK_SIGNING_KEYS": "kid1:secret1"}):
            from packages.quantum.security import task_signing_v4
            import importlib
            importlib.reload(task_signing_v4)

            keys = task_signing_v4.parse_signing_keys()
            assert keys == {"kid1": "secret1"}

    def test_parse_signing_keys_multiple(self):
        """Parse multiple keys."""
        with patch.dict("os.environ", {"TASK_SIGNING_KEYS": "kid1:secret1,kid2:secret2,kid3:secret3"}):
            from packages.quantum.security import task_signing_v4
            import importlib
            importlib.reload(task_signing_v4)

            keys = task_signing_v4.parse_signing_keys()
            assert keys == {
                "kid1": "secret1",
                "kid2": "secret2",
                "kid3": "secret3"
            }

    def test_parse_signing_keys_with_whitespace(self):
        """Whitespace should be trimmed."""
        with patch.dict("os.environ", {"TASK_SIGNING_KEYS": " kid1 : secret1 , kid2:secret2 "}):
            from packages.quantum.security import task_signing_v4
            import importlib
            importlib.reload(task_signing_v4)

            keys = task_signing_v4.parse_signing_keys()
            assert keys == {"kid1": "secret1", "kid2": "secret2"}

    def test_parse_signing_keys_empty(self):
        """Empty string returns empty dict."""
        with patch.dict("os.environ", {"TASK_SIGNING_KEYS": ""}):
            from packages.quantum.security import task_signing_v4
            import importlib
            importlib.reload(task_signing_v4)

            keys = task_signing_v4.parse_signing_keys()
            assert keys == {}

    def test_get_signing_secret_with_key_id(self):
        """get_signing_secret should return correct key by ID."""
        with patch.dict("os.environ", {"TASK_SIGNING_KEYS": "kid1:secret1,kid2:secret2"}):
            from packages.quantum.security import task_signing_v4
            import importlib
            importlib.reload(task_signing_v4)

            # Force re-parse
            task_signing_v4.SIGNING_KEYS = task_signing_v4.parse_signing_keys()

            assert task_signing_v4.get_signing_secret("kid1") == "secret1"
            assert task_signing_v4.get_signing_secret("kid2") == "secret2"
            assert task_signing_v4.get_signing_secret("unknown") is None


# =============================================================================
# Verification Dependency Tests
# =============================================================================

class TestVerifyTaskSignature:
    """Test the FastAPI dependency for signature verification."""

    @pytest.fixture
    def mock_request(self):
        """Create a mock FastAPI request."""
        request = MagicMock()
        request.url.path = "/tasks/suggestions/open"
        request.method = "POST"
        return request

    @pytest.mark.asyncio
    async def test_verify_valid_signature(self, mock_request):
        """Valid v4 signature should pass verification."""
        secret = "test-secret-789"
        scope = "tasks:suggestions_open"
        body = b'{"strategy_name": "test"}'
        body_hash = hashlib.sha256(body).hexdigest()
        timestamp = int(time.time())
        nonce = secrets.token_hex(16)

        signature = compute_signature(
            secret, timestamp, nonce, "POST",
            "/tasks/suggestions/open", body_hash, scope
        )

        mock_request.body = AsyncMock(return_value=body)

        with patch.dict("os.environ", {
            "TASK_SIGNING_SECRET": secret,
            "TASK_SIGNING_KEYS": "",
            "TASK_NONCE_PROTECTION": "0"
        }):
            from packages.quantum.security import task_signing_v4
            import importlib
            importlib.reload(task_signing_v4)

            # Re-init module globals
            task_signing_v4.SIGNING_KEYS = {}
            task_signing_v4.TASK_SIGNING_SECRET = secret
            task_signing_v4.TASK_NONCE_PROTECTION = False

            dependency = task_signing_v4.verify_task_signature(scope)

            result = await dependency(
                request=mock_request,
                x_task_key_id=None,
                x_task_ts=str(timestamp),
                x_task_nonce=nonce,
                x_task_scope=scope,
                x_task_signature=signature,
                x_cron_secret=None
            )

            assert result.valid is True
            assert result.scope == scope
            assert result.actor == f"v4:{scope}"
            assert result.legacy_fallback is False

    @pytest.mark.asyncio
    async def test_reject_expired_timestamp(self, mock_request):
        """Expired timestamp should be rejected."""
        secret = "test-secret"
        scope = "tasks:test"
        body = b""

        # Timestamp from 10 minutes ago (beyond TTL)
        old_timestamp = int(time.time()) - 600
        nonce = secrets.token_hex(16)
        body_hash = hashlib.sha256(body).hexdigest()

        signature = compute_signature(
            secret, old_timestamp, nonce, "POST",
            "/tasks/test", body_hash, scope
        )

        mock_request.body = AsyncMock(return_value=body)
        mock_request.url.path = "/tasks/test"

        with patch.dict("os.environ", {
            "TASK_SIGNING_SECRET": secret,
            "TASK_SIGNING_KEYS": "",
            "TASK_NONCE_PROTECTION": "0"
        }):
            from packages.quantum.security import task_signing_v4
            import importlib
            importlib.reload(task_signing_v4)

            task_signing_v4.SIGNING_KEYS = {}
            task_signing_v4.TASK_SIGNING_SECRET = secret

            dependency = task_signing_v4.verify_task_signature(scope)

            with pytest.raises(HTTPException) as exc_info:
                await dependency(
                    request=mock_request,
                    x_task_key_id=None,
                    x_task_ts=str(old_timestamp),
                    x_task_nonce=nonce,
                    x_task_scope=scope,
                    x_task_signature=signature,
                    x_cron_secret=None
                )

            assert exc_info.value.status_code == 401
            assert "expired" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_reject_scope_mismatch(self, mock_request):
        """Mismatched scope should be rejected."""
        secret = "test-secret"
        required_scope = "tasks:suggestions_open"
        provided_scope = "tasks:suggestions_close"  # Wrong scope
        body = b""
        timestamp = int(time.time())
        nonce = secrets.token_hex(16)
        body_hash = hashlib.sha256(body).hexdigest()

        signature = compute_signature(
            secret, timestamp, nonce, "POST",
            "/tasks/suggestions/open", body_hash, provided_scope
        )

        mock_request.body = AsyncMock(return_value=body)

        with patch.dict("os.environ", {
            "TASK_SIGNING_SECRET": secret,
            "TASK_SIGNING_KEYS": "",
        }):
            from packages.quantum.security import task_signing_v4
            import importlib
            importlib.reload(task_signing_v4)

            task_signing_v4.SIGNING_KEYS = {}
            task_signing_v4.TASK_SIGNING_SECRET = secret

            dependency = task_signing_v4.verify_task_signature(required_scope)

            with pytest.raises(HTTPException) as exc_info:
                await dependency(
                    request=mock_request,
                    x_task_key_id=None,
                    x_task_ts=str(timestamp),
                    x_task_nonce=nonce,
                    x_task_scope=provided_scope,
                    x_task_signature=signature,
                    x_cron_secret=None
                )

            assert exc_info.value.status_code == 403
            assert "scope" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_reject_invalid_signature(self, mock_request):
        """Invalid signature should be rejected."""
        secret = "test-secret"
        scope = "tasks:test"
        body = b""
        timestamp = int(time.time())
        nonce = secrets.token_hex(16)

        mock_request.body = AsyncMock(return_value=body)
        mock_request.url.path = "/tasks/test"

        with patch.dict("os.environ", {
            "TASK_SIGNING_SECRET": secret,
            "TASK_SIGNING_KEYS": "",
        }):
            from packages.quantum.security import task_signing_v4
            import importlib
            importlib.reload(task_signing_v4)

            task_signing_v4.SIGNING_KEYS = {}
            task_signing_v4.TASK_SIGNING_SECRET = secret

            dependency = task_signing_v4.verify_task_signature(scope)

            with pytest.raises(HTTPException) as exc_info:
                await dependency(
                    request=mock_request,
                    x_task_key_id=None,
                    x_task_ts=str(timestamp),
                    x_task_nonce=nonce,
                    x_task_scope=scope,
                    x_task_signature="invalid-signature-here",
                    x_cron_secret=None
                )

            assert exc_info.value.status_code == 401
            assert "signature" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_reject_missing_headers(self, mock_request):
        """Missing required headers should be rejected."""
        with patch.dict("os.environ", {"TASK_SIGNING_SECRET": "test"}):
            from packages.quantum.security import task_signing_v4
            import importlib
            importlib.reload(task_signing_v4)

            dependency = task_signing_v4.verify_task_signature("tasks:test")

            with pytest.raises(HTTPException) as exc_info:
                await dependency(
                    request=mock_request,
                    x_task_key_id=None,
                    x_task_ts=None,  # Missing
                    x_task_nonce=None,  # Missing
                    x_task_scope=None,  # Missing
                    x_task_signature=None,  # Missing
                    x_cron_secret=None
                )

            assert exc_info.value.status_code == 401
            assert "missing" in exc_info.value.detail.lower()


# =============================================================================
# Legacy CRON_SECRET Fallback Tests
# =============================================================================

class TestLegacyCronSecretFallback:
    """Test the legacy CRON_SECRET fallback behavior."""

    @pytest.fixture
    def mock_request(self):
        request = MagicMock()
        request.url.path = "/tasks/test"
        request.method = "POST"
        return request

    @pytest.mark.asyncio
    async def test_legacy_cron_secret_when_allowed(self, mock_request):
        """Legacy CRON_SECRET should work when ALLOW_LEGACY_CRON_SECRET=1."""
        cron_secret = "my-cron-secret"

        with patch.dict("os.environ", {
            "ALLOW_LEGACY_CRON_SECRET": "1",
            "CRON_SECRET": cron_secret,
            "TASK_SIGNING_SECRET": "",
        }):
            from packages.quantum.security import task_signing_v4
            import importlib
            importlib.reload(task_signing_v4)

            task_signing_v4.ALLOW_LEGACY_CRON_SECRET = True
            task_signing_v4.CRON_SECRET = cron_secret

            dependency = task_signing_v4.verify_task_signature("tasks:test")

            result = await dependency(
                request=mock_request,
                x_task_key_id=None,
                x_task_ts=None,
                x_task_nonce=None,
                x_task_scope=None,
                x_task_signature=None,
                x_cron_secret=cron_secret
            )

            assert result.valid is True
            assert result.actor == "legacy:cron"
            assert result.scope == "*"
            assert result.legacy_fallback is True

    @pytest.mark.asyncio
    async def test_legacy_cron_secret_rejected_when_disabled(self, mock_request):
        """Legacy CRON_SECRET should fail when ALLOW_LEGACY_CRON_SECRET=0."""
        cron_secret = "my-cron-secret"

        with patch.dict("os.environ", {
            "ALLOW_LEGACY_CRON_SECRET": "0",
            "CRON_SECRET": cron_secret,
        }):
            from packages.quantum.security import task_signing_v4
            import importlib
            importlib.reload(task_signing_v4)

            task_signing_v4.ALLOW_LEGACY_CRON_SECRET = False
            task_signing_v4.CRON_SECRET = cron_secret

            dependency = task_signing_v4.verify_task_signature("tasks:test")

            with pytest.raises(HTTPException) as exc_info:
                await dependency(
                    request=mock_request,
                    x_task_key_id=None,
                    x_task_ts=None,
                    x_task_nonce=None,
                    x_task_scope=None,
                    x_task_signature=None,
                    x_cron_secret=cron_secret
                )

            assert exc_info.value.status_code == 401
            assert "disabled" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_legacy_wrong_cron_secret(self, mock_request):
        """Wrong CRON_SECRET should fail."""
        with patch.dict("os.environ", {
            "ALLOW_LEGACY_CRON_SECRET": "1",
            "CRON_SECRET": "correct-secret",
        }):
            from packages.quantum.security import task_signing_v4
            import importlib
            importlib.reload(task_signing_v4)

            task_signing_v4.ALLOW_LEGACY_CRON_SECRET = True
            task_signing_v4.CRON_SECRET = "correct-secret"

            dependency = task_signing_v4.verify_task_signature("tasks:test")

            with pytest.raises(HTTPException) as exc_info:
                await dependency(
                    request=mock_request,
                    x_task_key_id=None,
                    x_task_ts=None,
                    x_task_nonce=None,
                    x_task_scope=None,
                    x_task_signature=None,
                    x_cron_secret="wrong-secret"
                )

            assert exc_info.value.status_code == 401


# =============================================================================
# Nonce Replay Protection Tests
# =============================================================================

class TestNonceReplayProtection:
    """Test nonce replay protection (mocked Supabase)."""

    def test_nonce_protection_disabled_allows_all(self):
        """When disabled, all nonces should be allowed."""
        with patch.dict("os.environ", {"TASK_NONCE_PROTECTION": "0"}):
            from packages.quantum.security import task_signing_v4
            import importlib
            importlib.reload(task_signing_v4)

            task_signing_v4.TASK_NONCE_PROTECTION = False

            # Should always return True when disabled
            assert task_signing_v4.check_and_store_nonce("any-nonce", "tasks:test", 12345) is True
            assert task_signing_v4.check_and_store_nonce("any-nonce", "tasks:test", 12345) is True

    def test_nonce_replay_detected(self):
        """Replay should be detected when nonce insert fails due to conflict."""
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table

        # Second call fails with duplicate error
        mock_table.insert.return_value.execute.side_effect = [
            MagicMock(),  # First succeeds
            Exception("duplicate key violates unique constraint")  # Second fails
        ]

        with patch.dict("os.environ", {"TASK_NONCE_PROTECTION": "1"}):
            from packages.quantum.security import task_signing_v4
            import importlib
            importlib.reload(task_signing_v4)

            task_signing_v4.TASK_NONCE_PROTECTION = True

            # Mock _get_nonce_client after reload
            with patch.object(task_signing_v4, "_get_nonce_client", return_value=mock_client):
                # First use should succeed
                result1 = task_signing_v4.check_and_store_nonce("nonce-1", "tasks:test", 12345)
                assert result1 is True

                # Second use (replay) should fail
                result2 = task_signing_v4.check_and_store_nonce("nonce-1", "tasks:test", 12345)
                assert result2 is False


class TestNonceFailClosedBehavior:
    """Test fail-closed vs fail-open behavior for nonce protection."""

    def test_fail_closed_rejects_when_store_unavailable_in_prod(self):
        """In production with fail-closed, unavailable nonce store should reject."""
        with patch.dict("os.environ", {
            "TASK_NONCE_PROTECTION": "1",
            "TASK_NONCE_FAIL_CLOSED_IN_PROD": "1",
            "ENV": "production",
        }):
            from packages.quantum.security import task_signing_v4
            import importlib
            importlib.reload(task_signing_v4)

            task_signing_v4.TASK_NONCE_PROTECTION = True
            task_signing_v4.TASK_NONCE_FAIL_CLOSED_IN_PROD = True

            # Mock store as unavailable
            with patch.object(task_signing_v4, "_get_nonce_client", return_value=None):
                with patch.object(task_signing_v4, "_is_production_mode", return_value=True):
                    with patch.object(task_signing_v4, "_emit_nonce_audit_event"):
                        result = task_signing_v4.check_and_store_nonce("test-nonce", "tasks:test", 12345)
                        assert result is False  # Rejected in fail-closed mode

    def test_fail_open_allows_when_store_unavailable_in_dev(self):
        """In dev mode, unavailable nonce store should allow request."""
        with patch.dict("os.environ", {
            "TASK_NONCE_PROTECTION": "1",
            "TASK_NONCE_FAIL_CLOSED_IN_PROD": "1",
            "ENV": "development",
            "ENABLE_DEV_AUTH_BYPASS": "1",
        }):
            from packages.quantum.security import task_signing_v4
            import importlib
            importlib.reload(task_signing_v4)

            task_signing_v4.TASK_NONCE_PROTECTION = True
            task_signing_v4.TASK_NONCE_FAIL_CLOSED_IN_PROD = True

            # Mock store as unavailable
            with patch.object(task_signing_v4, "_get_nonce_client", return_value=None):
                with patch.object(task_signing_v4, "_is_production_mode", return_value=False):
                    result = task_signing_v4.check_and_store_nonce("test-nonce", "tasks:test", 12345)
                    assert result is True  # Allowed in dev mode (fail-open)

    def test_fail_closed_rejects_on_store_error_in_prod(self):
        """In production, non-duplicate store errors should reject."""
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table
        mock_table.insert.return_value.execute.side_effect = Exception("Connection timeout")

        with patch.dict("os.environ", {
            "TASK_NONCE_PROTECTION": "1",
            "TASK_NONCE_FAIL_CLOSED_IN_PROD": "1",
            "ENV": "production",
        }):
            from packages.quantum.security import task_signing_v4
            import importlib
            importlib.reload(task_signing_v4)

            task_signing_v4.TASK_NONCE_PROTECTION = True
            task_signing_v4.TASK_NONCE_FAIL_CLOSED_IN_PROD = True

            with patch.object(task_signing_v4, "_get_nonce_client", return_value=mock_client):
                with patch.object(task_signing_v4, "_is_production_mode", return_value=True):
                    with patch.object(task_signing_v4, "_emit_nonce_audit_event"):
                        result = task_signing_v4.check_and_store_nonce("test-nonce", "tasks:test", 12345)
                        assert result is False  # Rejected on error in fail-closed mode

    def test_fail_open_allows_on_store_error_in_dev(self):
        """In dev mode, non-duplicate store errors should allow request."""
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table
        mock_table.insert.return_value.execute.side_effect = Exception("Connection timeout")

        with patch.dict("os.environ", {
            "TASK_NONCE_PROTECTION": "1",
            "ENV": "development",
            "ENABLE_DEV_AUTH_BYPASS": "1",
        }):
            from packages.quantum.security import task_signing_v4
            import importlib
            importlib.reload(task_signing_v4)

            task_signing_v4.TASK_NONCE_PROTECTION = True

            with patch.object(task_signing_v4, "_get_nonce_client", return_value=mock_client):
                with patch.object(task_signing_v4, "_is_production_mode", return_value=False):
                    result = task_signing_v4.check_and_store_nonce("test-nonce", "tasks:test", 12345)
                    assert result is True  # Allowed in dev mode

    def test_is_production_mode_env_production(self):
        """ENV=production should return True."""
        from packages.quantum.security import task_signing_v4
        import importlib

        with patch.dict("os.environ", {"ENV": "production"}):
            importlib.reload(task_signing_v4)
            assert task_signing_v4._is_production_mode() is True

    def test_is_production_mode_dev_bypass_disabled(self):
        """ENABLE_DEV_AUTH_BYPASS=0 should return True (treated as prod)."""
        from packages.quantum.security import task_signing_v4
        import importlib

        with patch.dict("os.environ", {"ENV": "staging", "ENABLE_DEV_AUTH_BYPASS": "0"}):
            importlib.reload(task_signing_v4)
            assert task_signing_v4._is_production_mode() is True

    def test_is_production_mode_dev_bypass_enabled(self):
        """ENABLE_DEV_AUTH_BYPASS=1 should return False (dev mode)."""
        from packages.quantum.security import task_signing_v4
        import importlib

        with patch.dict("os.environ", {"ENV": "development", "ENABLE_DEV_AUTH_BYPASS": "1"}):
            importlib.reload(task_signing_v4)
            assert task_signing_v4._is_production_mode() is False


# =============================================================================
# Pydantic Model Tests
# =============================================================================

class TestPublicTasksModels:
    """Test the Pydantic models for task payloads."""

    def test_suggestions_open_payload_defaults(self):
        """SuggestionsOpenPayload should have sensible defaults."""
        from packages.quantum.public_tasks_models import SuggestionsOpenPayload

        payload = SuggestionsOpenPayload()
        assert payload.strategy_name == "spy_opt_autolearn_v6"
        assert payload.user_id is None
        assert payload.skip_sync is False

    def test_suggestions_open_payload_custom(self):
        """SuggestionsOpenPayload should accept custom values."""
        from packages.quantum.public_tasks_models import SuggestionsOpenPayload

        payload = SuggestionsOpenPayload(
            strategy_name="custom_strategy",
            user_id="12345678-1234-1234-1234-123456789012",
            skip_sync=True
        )
        assert payload.strategy_name == "custom_strategy"
        assert payload.user_id == "12345678-1234-1234-1234-123456789012"
        assert payload.skip_sync is True

    def test_validation_eval_payload_mode_validation(self):
        """ValidationEvalPayload should validate mode."""
        from packages.quantum.public_tasks_models import ValidationEvalPayload
        from pydantic import ValidationError

        # Valid modes
        payload1 = ValidationEvalPayload(mode="paper")
        assert payload1.mode == "paper"

        payload2 = ValidationEvalPayload(mode="historical")
        assert payload2.mode == "historical"

        # Invalid mode
        with pytest.raises(ValidationError):
            ValidationEvalPayload(mode="invalid")

    def test_learning_ingest_payload_lookback_bounds(self):
        """LearningIngestPayload should enforce lookback_days bounds."""
        from packages.quantum.public_tasks_models import LearningIngestPayload
        from pydantic import ValidationError

        # Valid range
        payload = LearningIngestPayload(lookback_days=30)
        assert payload.lookback_days == 30

        # Too low
        with pytest.raises(ValidationError):
            LearningIngestPayload(lookback_days=0)

        # Too high
        with pytest.raises(ValidationError):
            LearningIngestPayload(lookback_days=100)

    def test_payload_rejects_unknown_fields(self):
        """Payloads should reject unknown fields (extra='forbid')."""
        from packages.quantum.public_tasks_models import SuggestionsOpenPayload
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SuggestionsOpenPayload(unknown_field="value")

    def test_task_scopes_mapping(self):
        """TASK_SCOPES should have all endpoints mapped."""
        from packages.quantum.public_tasks_models import TASK_SCOPES

        expected_paths = [
            "/tasks/universe/sync",
            "/tasks/morning-brief",
            "/tasks/midday-scan",
            "/tasks/weekly-report",
            "/tasks/validation/eval",
            "/tasks/suggestions/close",
            "/tasks/suggestions/open",
            "/tasks/learning/ingest",
            "/tasks/strategy/autotune",
        ]

        for path in expected_paths:
            assert path in TASK_SCOPES, f"Missing scope for {path}"
            assert TASK_SCOPES[path].startswith("tasks:"), f"Scope for {path} should start with 'tasks:'"
