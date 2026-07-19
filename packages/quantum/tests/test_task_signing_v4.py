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

import importlib
import sys
import types
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


def _pin_real_module(monkeypatch, name):
    """Return the GENUINE module for ``name`` and pin it into ``sys.modules``
    for the test's duration (self-contained mirror of
    test_job_origin_provenance._pin_real_module).

    Sibling suites can replace ``packages.quantum.security`` (or a submodule)
    with a MagicMock in ``sys.modules`` at collection time; a later
    ``importlib.reload`` on the leaked mock raises, and a ``from ... import``
    then binds mock children. Pinning the real module makes every import form
    resolve to the same object, so the route's ``verify_task_signature``
    closure reads the real globals this test sets.
    """
    def _is_real(mod):
        return isinstance(mod, types.ModuleType) and getattr(
            mod, "__spec__", None
        ) is not None

    mod = sys.modules.get(name)
    if not _is_real(mod):
        parent_name, _, attr = name.rpartition(".")
        parent = sys.modules.get(parent_name)
        cand = getattr(parent, attr, None) if parent is not None else None
        if _is_real(cand):
            mod = cand
        else:
            monkeypatch.delitem(sys.modules, name, raising=False)
            mod = importlib.import_module(name)
    monkeypatch.setitem(sys.modules, name, mod)
    return mod


# Canonical production-marker env keys read by security.config.is_production()
# (H13). ENV is deliberately EXCLUDED — the F-A9-1 fix drops the divergent
# ENV/ENABLE_DEV_AUTH_BYPASS heuristic; a stray ENV=production must NOT
# classify as production.
_ENV_KEYS = (
    "APP_ENV",
    "RAILWAY_ENVIRONMENT",
    "RAILWAY_ENVIRONMENT_NAME",
    "ENV",
    "ENABLE_DEV_AUTH_BYPASS",
    "TASK_NONCE_FAIL_CLOSED_IN_PROD",
)


def _clear_env(monkeypatch):
    for k in _ENV_KEYS:
        monkeypatch.delenv(k, raising=False)


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


class TestProductionModeDetection:
    """`_is_production_mode` must be the CANONICAL detector — a thin delegate to
    security.config.is_production() (H13), NOT a second heuristic (F-A9-1)."""

    @pytest.fixture
    def signing(self, monkeypatch):
        _clear_env(monkeypatch)
        return _pin_real_module(
            monkeypatch, "packages.quantum.security.task_signing_v4"
        )

    def test_app_env_production_is_production(self, signing, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        assert signing._is_production_mode() is True

    def test_railway_environment_name_is_production(self, signing, monkeypatch):
        monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
        assert signing._is_production_mode() is True

    def test_railway_environment_is_production(self, signing, monkeypatch):
        monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
        assert signing._is_production_mode() is True

    def test_env_production_alone_is_NOT_production(self, signing, monkeypatch):
        """F-A9-1 regression: the pre-fix detector keyed off ENV=production.
        The canonical detector ignores ENV — a stray ENV must never classify
        as production (nor de-classify a real one)."""
        monkeypatch.setenv("ENV", "production")
        assert signing._is_production_mode() is False

    def test_dev_bypass_zero_alone_is_NOT_production(self, signing, monkeypatch):
        """F-A9-1 regression: the pre-fix detector treated
        ENABLE_DEV_AUTH_BYPASS=0 as production. The canonical detector does
        not — production is APP_ENV / the Railway platform signal only."""
        monkeypatch.setenv("ENABLE_DEV_AUTH_BYPASS", "0")
        assert signing._is_production_mode() is False

    def test_all_unset_is_not_production(self, signing):
        assert signing._is_production_mode() is False

    def test_dev_bypass_enabled_is_not_production(self, signing, monkeypatch):
        monkeypatch.setenv("APP_ENV", "development")
        monkeypatch.setenv("ENABLE_DEV_AUTH_BYPASS", "1")
        assert signing._is_production_mode() is False

    def test_delegates_to_config_is_production(self, signing, monkeypatch):
        """No second detector: the result IS security.config.is_production()."""
        from packages.quantum.security import config as sec_config

        for env in ({}, {"APP_ENV": "production"},
                    {"RAILWAY_ENVIRONMENT": "production"},
                    {"ENV": "production"},
                    {"ENABLE_DEV_AUTH_BYPASS": "0"}):
            _clear_env(monkeypatch)
            for k, v in env.items():
                monkeypatch.setenv(k, v)
            assert signing._is_production_mode() == sec_config.is_production()


# Every production-marker combination the fail-closed contract must cover.
# (label, env-dict, is_production_expected)
_PRODUCTION_MARKERS = [
    ("app_env_production", {"APP_ENV": "production"}, True),
    ("railway_environment", {"RAILWAY_ENVIRONMENT": "production"}, True),
    ("railway_environment_name", {"RAILWAY_ENVIRONMENT_NAME": "production"}, True),
    ("env_production_alone", {"ENV": "production"}, False),
    ("all_unset", {}, False),
    ("dev_app_env", {"APP_ENV": "development"}, False),
]


class TestNonceFailClosedBehavior:
    """Fail-closed vs the narrow, explicit dev fail-open — driven at the
    deepest callee (`check_and_store_nonce`) with the store injected DOWN.

    Reload-free: `_is_production_mode` / `_nonce_outage_fails_closed` read env
    at call time via the canonical config; only the module-level
    TASK_NONCE_PROTECTION constant is set via setattr. No production marker can
    reach the fail-open branch."""

    @pytest.fixture
    def signing(self, monkeypatch):
        _clear_env(monkeypatch)
        mod = _pin_real_module(
            monkeypatch, "packages.quantum.security.task_signing_v4"
        )
        monkeypatch.setattr(mod, "TASK_NONCE_PROTECTION", True)
        monkeypatch.setattr(mod, "_emit_nonce_audit_event",
                            lambda *a, **k: None)
        return mod

    @pytest.mark.parametrize("label,env,is_prod", _PRODUCTION_MARKERS)
    def test_store_unavailable_fails_closed(
            self, signing, monkeypatch, label, env, is_prod):
        """Store DOWN → fail CLOSED (typed error) under EVERY production marker
        AND under every non-production state lacking the explicit dev escape.

        `env_production_alone` / `all_unset` are non-production yet still fail
        closed: fail-open needs the explicit dev markers, never mere
        non-production."""
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        assert signing._is_production_mode() is is_prod
        monkeypatch.setattr(signing, "_get_nonce_client", lambda: None)
        with pytest.raises(signing.NonceStoreUnavailableError):
            signing.check_and_store_nonce("nonce-x", "tasks:test", 12345)

    @pytest.mark.parametrize("label,env,is_prod", _PRODUCTION_MARKERS)
    def test_store_error_fails_closed(
            self, signing, monkeypatch, label, env, is_prod):
        """A non-duplicate store ERROR → fail CLOSED (typed error), same
        matrix. A value that cannot be verified rejects, never fabricates."""
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        client = MagicMock()
        client.table.return_value.insert.return_value.execute.side_effect = (
            Exception("Connection timeout to nonce store")
        )
        monkeypatch.setattr(signing, "_get_nonce_client", lambda: client)
        with pytest.raises(signing.NonceStoreUnavailableError):
            signing.check_and_store_nonce("nonce-y", "tasks:test", 12345)

    def test_production_cannot_be_forced_open(self, signing, monkeypatch):
        """The hardening: even the explicit dev opt-out CANNOT open production.
        APP_ENV=production + ENABLE_DEV_AUTH_BYPASS=1 + FAIL_CLOSED_IN_PROD=0
        (a config-illegal combo that startup would hard-abort) STILL fails
        closed — production is non-overridable."""
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("ENABLE_DEV_AUTH_BYPASS", "1")
        monkeypatch.setenv("TASK_NONCE_FAIL_CLOSED_IN_PROD", "0")
        assert signing._nonce_outage_fails_closed() is True
        monkeypatch.setattr(signing, "_get_nonce_client", lambda: None)
        with pytest.raises(signing.NonceStoreUnavailableError):
            signing.check_and_store_nonce("nonce-z", "tasks:test", 12345)

    def test_dev_escape_fails_open_only_with_both_markers(
            self, signing, monkeypatch):
        """The ONLY fail-open path: non-production AND ENABLE_DEV_AUTH_BYPASS=1
        AND TASK_NONCE_FAIL_CLOSED_IN_PROD=0. Store DOWN → allowed (True)."""
        monkeypatch.setenv("APP_ENV", "development")
        monkeypatch.setenv("ENABLE_DEV_AUTH_BYPASS", "1")
        monkeypatch.setenv("TASK_NONCE_FAIL_CLOSED_IN_PROD", "0")
        assert signing._nonce_outage_fails_closed() is False
        monkeypatch.setattr(signing, "_get_nonce_client", lambda: None)
        assert signing.check_and_store_nonce("nonce-d", "tasks:test", 12345) is True

    def test_dev_bypass_without_optout_fails_closed(self, signing, monkeypatch):
        """Dev bypass alone is NOT enough — without the explicit opt-out the
        request still fails closed (the escape hatch is narrow)."""
        monkeypatch.setenv("APP_ENV", "development")
        monkeypatch.setenv("ENABLE_DEV_AUTH_BYPASS", "1")
        # TASK_NONCE_FAIL_CLOSED_IN_PROD unset → default fail-closed
        assert signing._nonce_outage_fails_closed() is True
        monkeypatch.setattr(signing, "_get_nonce_client", lambda: None)
        with pytest.raises(signing.NonceStoreUnavailableError):
            signing.check_and_store_nonce("nonce-e", "tasks:test", 12345)

    def test_optout_without_dev_bypass_fails_closed(self, signing, monkeypatch):
        """The opt-out alone is NOT enough — without dev bypass it fails
        closed."""
        monkeypatch.setenv("APP_ENV", "development")
        monkeypatch.setenv("TASK_NONCE_FAIL_CLOSED_IN_PROD", "0")
        assert signing._nonce_outage_fails_closed() is True
        monkeypatch.setattr(signing, "_get_nonce_client", lambda: None)
        with pytest.raises(signing.NonceStoreUnavailableError):
            signing.check_and_store_nonce("nonce-f", "tasks:test", 12345)

    def test_protection_disabled_short_circuits(self, signing, monkeypatch):
        """TASK_NONCE_PROTECTION=0 → always allowed, store never consulted."""
        monkeypatch.setattr(signing, "TASK_NONCE_PROTECTION", False)

        def _boom():
            raise AssertionError("store must not be consulted when disabled")

        monkeypatch.setattr(signing, "_get_nonce_client", _boom)
        assert signing.check_and_store_nonce("n", "tasks:test", 1) is True


# =============================================================================
# Route-driven verification — the REAL verifier on a REAL FastAPI route, with
# failures injected at the DEEPEST callee (the nonce store) and truth asserted
# at the TOP (the HTTP status). Pattern: test_shadow_fleet_activation_route.
# =============================================================================

ROUTE = "/tasks/test/verify"
SCOPE = "tasks:test_verify"
ROUTE_SECRET = "route-drive-signing-secret-abc123"


class _FakeNonceStore:
    """Minimal supabase-shaped nonce store: first insert of a nonce succeeds,
    a repeat raises a unique-violation (the real replay signal)."""

    def __init__(self):
        self._seen = set()
        self._pending = None

    def table(self, _name):
        return self

    def insert(self, row):
        self._pending = row
        return self

    def execute(self):
        nonce = self._pending["nonce"]
        if nonce in self._seen:
            raise Exception("duplicate key value violates unique constraint")
        self._seen.add(nonce)
        return MagicMock()


@pytest.fixture
def signed_route(monkeypatch):
    """A fresh FastAPI app whose single route is guarded by the REAL
    verify_task_signature closure reading the pinned module's globals."""
    from fastapi import FastAPI, Depends

    _clear_env(monkeypatch)
    signing = _pin_real_module(
        monkeypatch, "packages.quantum.security.task_signing_v4"
    )
    monkeypatch.setattr(signing, "SIGNING_KEYS", {})
    monkeypatch.setattr(signing, "TASK_SIGNING_SECRET", ROUTE_SECRET)
    monkeypatch.setattr(signing, "ALLOW_LEGACY_CRON_SECRET", False)
    monkeypatch.setattr(signing, "TASK_NONCE_PROTECTION", True)
    monkeypatch.setattr(signing, "_emit_nonce_audit_event", lambda *a, **k: None)

    app = FastAPI()

    @app.post(ROUTE)
    async def _endpoint(
        auth: TaskSignatureResult = Depends(signing.verify_task_signature(SCOPE))
    ):
        return {"ok": True, "actor": auth.actor, "scope": auth.scope}

    client = TestClient(app, raise_server_exceptions=False)
    return signing, client


def _sign(signing, body, *, method="POST", path=ROUTE, scope=SCOPE,
          secret=ROUTE_SECRET):
    headers = signing.sign_task_request(
        method=method, path=path, body=body, scope=scope, secret=secret
    )
    headers["Content-Type"] = "application/json"
    return headers


class TestSignedRouteHappyAndReplay:
    def test_valid_request_200(self, signed_route):
        signing, client = signed_route
        store = _FakeNonceStore()
        with patch.object(signing, "_get_nonce_client", return_value=store):
            body = b'{"hello":"world"}'
            resp = client.post(ROUTE, content=body, headers=_sign(signing, body))
        assert resp.status_code == 200
        assert resp.json()["scope"] == SCOPE
        assert resp.json()["actor"] == f"v4:{SCOPE}"

    def test_replayed_nonce_401(self, signed_route):
        signing, client = signed_route
        store = _FakeNonceStore()
        with patch.object(signing, "_get_nonce_client", return_value=store):
            body = b'{"hello":"world"}'
            headers = _sign(signing, body)  # SAME headers → SAME nonce
            first = client.post(ROUTE, content=body, headers=headers)
            replay = client.post(ROUTE, content=body, headers=headers)
        assert first.status_code == 200
        assert replay.status_code == 401
        assert "replay" in replay.json()["detail"].lower()

    def test_secret_never_appears_in_error_body(self, signed_route):
        """No secret in the wire error (bad signature → 401)."""
        signing, client = signed_route
        store = _FakeNonceStore()
        with patch.object(signing, "_get_nonce_client", return_value=store):
            body = b'{"a":1}'
            headers = _sign(signing, body)
            headers["X-Task-Signature"] = "deadbeef" * 8  # wrong
            resp = client.post(ROUTE, content=body, headers=headers)
        assert resp.status_code == 401
        assert ROUTE_SECRET not in resp.text


class TestSignedRouteRejections:
    def _store(self, signing):
        return patch.object(signing, "_get_nonce_client",
                            return_value=_FakeNonceStore())

    def test_expired_timestamp_401(self, signed_route):
        signing, client = signed_route
        body = b'{}'
        headers = signing.sign_task_request(
            method="POST", path=ROUTE, body=body, scope=SCOPE, secret=ROUTE_SECRET
        )
        headers["Content-Type"] = "application/json"
        old_ts = str(int(time.time()) - (TASK_V4_TTL_SECONDS + 120))
        headers["X-Task-Ts"] = old_ts  # stale ts (sig no longer matches, but
        # the expiry gate fires first — either way the request is rejected)
        with self._store(signing):
            resp = client.post(ROUTE, content=body, headers=headers)
        assert resp.status_code == 401
        assert "expired" in resp.json()["detail"].lower()

    def test_future_out_of_skew_timestamp_401(self, signed_route):
        signing, client = signed_route
        body = b'{}'
        future_ts = int(time.time()) + (TASK_V4_TTL_SECONDS + 120)
        nonce = secrets.token_hex(16)
        body_hash = hashlib.sha256(body).hexdigest()
        sig = compute_signature(
            ROUTE_SECRET, future_ts, nonce, "POST", ROUTE, body_hash, SCOPE
        )
        headers = {
            "X-Task-Ts": str(future_ts), "X-Task-Nonce": nonce,
            "X-Task-Scope": SCOPE, "X-Task-Signature": sig,
            "Content-Type": "application/json",
        }
        with self._store(signing):
            resp = client.post(ROUTE, content=body, headers=headers)
        assert resp.status_code == 401
        assert "expired" in resp.json()["detail"].lower()

    def test_wrong_scope_403(self, signed_route):
        signing, client = signed_route
        body = b'{}'
        headers = _sign(signing, body, scope="tasks:some_other_scope")
        with self._store(signing):
            resp = client.post(ROUTE, content=body, headers=headers)
        assert resp.status_code == 403
        assert "scope" in resp.json()["detail"].lower()

    def test_wrong_secret_401(self, signed_route):
        signing, client = signed_route
        body = b'{}'
        headers = _sign(signing, body, secret="a-different-secret")
        with self._store(signing):
            resp = client.post(ROUTE, content=body, headers=headers)
        assert resp.status_code == 401
        assert "signature" in resp.json()["detail"].lower()

    def test_wrong_body_401(self, signed_route):
        """Signature binds the body hash: signed for body A, sent body B."""
        signing, client = signed_route
        headers = _sign(signing, b'{"signed":"body"}')
        with self._store(signing):
            resp = client.post(ROUTE, content=b'{"tampered":"body"}',
                               headers=headers)
        assert resp.status_code == 401
        assert "signature" in resp.json()["detail"].lower()

    def test_wrong_method_401(self, signed_route):
        """Signature binds the method: signed GET, dispatched POST."""
        signing, client = signed_route
        body = b'{}'
        headers = _sign(signing, body, method="GET")
        with self._store(signing):
            resp = client.post(ROUTE, content=body, headers=headers)
        assert resp.status_code == 401
        assert "signature" in resp.json()["detail"].lower()

    def test_wrong_path_401(self, signed_route):
        """Signature binds the path: signed a different path."""
        signing, client = signed_route
        body = b'{}'
        headers = _sign(signing, body, path="/tasks/other/path")
        with self._store(signing):
            resp = client.post(ROUTE, content=body, headers=headers)
        assert resp.status_code == 401
        assert "signature" in resp.json()["detail"].lower()

    def test_missing_headers_401(self, signed_route):
        signing, client = signed_route
        with self._store(signing):
            resp = client.post(ROUTE, content=b'{}',
                               headers={"Content-Type": "application/json"})
        assert resp.status_code == 401
        assert "missing" in resp.json()["detail"].lower()


class TestSignedRouteNonceOutageFailClosed:
    """The headline: a VALID, correctly-signed request is REJECTED at the route
    when the nonce store is DOWN and the context fails closed — under every
    production marker — and ALLOWED only in the narrow explicit dev escape."""

    @pytest.mark.parametrize("label,env,is_prod", _PRODUCTION_MARKERS)
    def test_store_down_fails_closed_503(
            self, signed_route, monkeypatch, label, env, is_prod):
        signing, client = signed_route
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        assert signing._is_production_mode() is is_prod
        # store DOWN
        monkeypatch.setattr(signing, "_get_nonce_client", lambda: None)
        body = b'{"valid":"signed"}'
        resp = client.post(ROUTE, content=body, headers=_sign(signing, body))
        # A perfectly valid signature is still rejected: replay protection is
        # unavailable and must never fail open. Honest 503, not a fabricated
        # 200 nor a misleading 401 replay.
        assert resp.status_code == 503, (label, resp.status_code)
        assert "replay protection unavailable" in resp.json()["detail"].lower()
        assert ROUTE_SECRET not in resp.text

    def test_store_down_dev_escape_allows_200(self, signed_route, monkeypatch):
        signing, client = signed_route
        monkeypatch.setenv("APP_ENV", "development")
        monkeypatch.setenv("ENABLE_DEV_AUTH_BYPASS", "1")
        monkeypatch.setenv("TASK_NONCE_FAIL_CLOSED_IN_PROD", "0")
        monkeypatch.setattr(signing, "_get_nonce_client", lambda: None)
        body = b'{"valid":"signed"}'
        resp = client.post(ROUTE, content=body, headers=_sign(signing, body))
        assert resp.status_code == 200

    def test_store_error_fails_closed_503(self, signed_route, monkeypatch):
        """A non-duplicate store ERROR on a production marker → 503."""
        signing, client = signed_route
        monkeypatch.setenv("APP_ENV", "production")
        erroring = MagicMock()
        erroring.table.return_value.insert.return_value.execute.side_effect = (
            Exception("nonce store connection reset")
        )
        monkeypatch.setattr(signing, "_get_nonce_client", lambda: erroring)
        body = b'{"valid":"signed"}'
        resp = client.post(ROUTE, content=body, headers=_sign(signing, body))
        assert resp.status_code == 503

    def test_unsigned_request_still_401_not_503(self, signed_route, monkeypatch):
        """An UNSIGNED request in production is a 401 (missing auth), decided
        before the nonce path — the outage path never masks missing auth."""
        signing, client = signed_route
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setattr(signing, "_get_nonce_client", lambda: None)
        resp = client.post(ROUTE, content=b'{}',
                           headers={"Content-Type": "application/json"})
        assert resp.status_code == 401


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
