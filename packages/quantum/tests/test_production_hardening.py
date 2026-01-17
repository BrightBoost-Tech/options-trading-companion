"""
Tests for Security v4: Production Hardening

Tests that:
- ENABLE_DEV_AUTH_BYPASS in production causes startup failure
- Debug routes are not registered in production
- Debug routes can be explicitly enabled via ENABLE_DEBUG_ROUTES=1
"""

import pytest
from unittest.mock import patch
import base64

# Valid Fernet key for testing (32 bytes base64 encoded)
VALID_FERNET_KEY = base64.urlsafe_b64encode(b"0" * 32).decode()


# =============================================================================
# Security Config Tests
# =============================================================================

class TestValidateSecurityConfig:
    """Test security configuration validation."""

    def test_dev_bypass_in_production_raises_error(self):
        """ENABLE_DEV_AUTH_BYPASS=1 in production should raise SecurityConfigError."""
        with patch.dict("os.environ", {
            "APP_ENV": "production",
            "ENABLE_DEV_AUTH_BYPASS": "1",
            # Required vars to pass first check
            "SUPABASE_JWT_SECRET": "test",
            "NEXT_PUBLIC_SUPABASE_URL": "https://test.supabase.co",
            "SUPABASE_ANON_KEY": "test-anon",
            "SUPABASE_SERVICE_ROLE_KEY": "test-service",
            "ENCRYPTION_KEY": VALID_FERNET_KEY,
        }):
            from packages.quantum.security import config
            import importlib
            importlib.reload(config)

            with pytest.raises(config.SecurityConfigError) as exc_info:
                config.validate_security_config()

            assert "ENABLE_DEV_AUTH_BYPASS" in str(exc_info.value)
            assert "production" in str(exc_info.value).lower()

    def test_dev_bypass_in_development_allowed(self):
        """ENABLE_DEV_AUTH_BYPASS=1 in development should be allowed."""
        with patch.dict("os.environ", {
            "APP_ENV": "development",
            "ENABLE_DEV_AUTH_BYPASS": "1",
            "SUPABASE_JWT_SECRET": "test",
            "NEXT_PUBLIC_SUPABASE_URL": "https://test.supabase.co",
            "SUPABASE_ANON_KEY": "test-anon",
            "SUPABASE_SERVICE_ROLE_KEY": "test-service",
            "ENCRYPTION_KEY": VALID_FERNET_KEY,
        }):
            from packages.quantum.security import config
            import importlib
            importlib.reload(config)

            # Should not raise
            config.validate_security_config()

    def test_missing_required_vars_raises_error(self):
        """Missing required env vars should raise SecurityConfigError."""
        with patch.dict("os.environ", {
            "APP_ENV": "development",
            # Missing required vars
        }, clear=True):
            from packages.quantum.security import config
            import importlib
            importlib.reload(config)

            with pytest.raises(config.SecurityConfigError) as exc_info:
                config.validate_security_config()

            assert "Missing required" in str(exc_info.value)


# =============================================================================
# Environment Detection Tests
# =============================================================================

class TestEnvironmentDetection:
    """Test environment detection functions."""

    def test_is_production_env_true(self):
        """is_production_env should return True when APP_ENV=production."""
        with patch.dict("os.environ", {"APP_ENV": "production"}):
            from packages.quantum.security import config
            import importlib
            importlib.reload(config)

            assert config.is_production_env() is True

    def test_is_production_env_false(self):
        """is_production_env should return False for non-production."""
        with patch.dict("os.environ", {"APP_ENV": "development"}):
            from packages.quantum.security import config
            import importlib
            importlib.reload(config)

            assert config.is_production_env() is False

    def test_is_dev_bypass_enabled_true(self):
        """is_dev_bypass_enabled should return True when ENABLE_DEV_AUTH_BYPASS=1."""
        with patch.dict("os.environ", {"ENABLE_DEV_AUTH_BYPASS": "1"}):
            from packages.quantum.security import config
            import importlib
            importlib.reload(config)

            assert config.is_dev_bypass_enabled() is True

    def test_is_dev_bypass_enabled_false(self):
        """is_dev_bypass_enabled should return False when not set or 0."""
        with patch.dict("os.environ", {"ENABLE_DEV_AUTH_BYPASS": "0"}):
            from packages.quantum.security import config
            import importlib
            importlib.reload(config)

            assert config.is_dev_bypass_enabled() is False


# =============================================================================
# Debug Routes Configuration Tests
# =============================================================================

class TestDebugRoutesConfiguration:
    """Test debug routes enablement logic."""

    def test_debug_routes_enabled_in_development_by_default(self):
        """Debug routes should be enabled by default in development."""
        with patch.dict("os.environ", {"APP_ENV": "development"}, clear=True):
            # Remove explicit setting
            import os
            os.environ.pop("ENABLE_DEBUG_ROUTES", None)

            from packages.quantum.security import config
            import importlib
            importlib.reload(config)

            assert config.is_debug_routes_enabled() is True

    def test_debug_routes_disabled_in_production_by_default(self):
        """Debug routes should be disabled by default in production."""
        with patch.dict("os.environ", {"APP_ENV": "production"}, clear=True):
            import os
            os.environ.pop("ENABLE_DEBUG_ROUTES", None)

            from packages.quantum.security import config
            import importlib
            importlib.reload(config)

            assert config.is_debug_routes_enabled() is False

    def test_debug_routes_explicit_enable_in_production(self):
        """Debug routes can be explicitly enabled in production."""
        with patch.dict("os.environ", {
            "APP_ENV": "production",
            "ENABLE_DEBUG_ROUTES": "1"
        }):
            from packages.quantum.security import config
            import importlib
            importlib.reload(config)

            assert config.is_debug_routes_enabled() is True

    def test_debug_routes_explicit_disable_in_development(self):
        """Debug routes can be explicitly disabled in development."""
        with patch.dict("os.environ", {
            "APP_ENV": "development",
            "ENABLE_DEBUG_ROUTES": "0"
        }):
            from packages.quantum.security import config
            import importlib
            importlib.reload(config)

            assert config.is_debug_routes_enabled() is False


# =============================================================================
# API Route Registration Tests
# =============================================================================

class TestAPIRouteRegistration:
    """Test that routes are registered correctly based on environment."""

    def test_debug_routes_not_in_openapi_when_disabled(self):
        """Debug routes should not appear in OpenAPI schema when disabled."""
        # This test verifies the conditional registration works
        # Note: Full integration testing would require spinning up the app

        with patch.dict("os.environ", {
            "APP_ENV": "production",
            "ENABLE_DEBUG_ROUTES": "0"
        }):
            from packages.quantum.security import config
            import importlib
            importlib.reload(config)

            # Verify the function returns False
            assert config.is_debug_routes_enabled() is False

            # The actual route registration happens at import time,
            # so this test verifies the guard condition

    def test_config_module_exports_correct_functions(self):
        """Verify all security functions are exported."""
        from packages.quantum.security.config import (
            validate_security_config,
            is_production_env,
            is_dev_bypass_enabled,
            is_debug_routes_enabled,
            SecurityConfigError,
            REQUIRED_ENV_VARS,
        )

        # Verify functions exist and are callable
        assert callable(validate_security_config)
        assert callable(is_production_env)
        assert callable(is_dev_bypass_enabled)
        assert callable(is_debug_routes_enabled)

        # Verify exception is a class
        assert issubclass(SecurityConfigError, Exception)

        # Verify required vars list is populated
        assert len(REQUIRED_ENV_VARS) > 0


# =============================================================================
# Integration Tests
# =============================================================================

class TestSecurityIntegration:
    """Integration tests for security hardening."""

    def test_full_validation_passes_in_valid_dev_env(self):
        """Full validation should pass in valid development environment."""
        with patch.dict("os.environ", {
            "APP_ENV": "development",
            "ENABLE_DEV_AUTH_BYPASS": "1",
            "SUPABASE_JWT_SECRET": "test-jwt-secret",
            "NEXT_PUBLIC_SUPABASE_URL": "https://test.supabase.co",
            "SUPABASE_ANON_KEY": "test-anon-key",
            "SUPABASE_SERVICE_ROLE_KEY": "test-service-key",
            "ENCRYPTION_KEY": VALID_FERNET_KEY,
            "TASK_SIGNING_SECRET": "test-task-secret",
        }):
            from packages.quantum.security import config
            import importlib
            importlib.reload(config)

            # Should not raise any exception
            config.validate_security_config()

    def test_full_validation_passes_in_valid_prod_env(self):
        """Full validation should pass in valid production environment."""
        with patch.dict("os.environ", {
            "APP_ENV": "production",
            # ENABLE_DEV_AUTH_BYPASS is NOT set (or is "0")
            "ENABLE_DEV_AUTH_BYPASS": "0",
            "SUPABASE_JWT_SECRET": "test-jwt-secret",
            "NEXT_PUBLIC_SUPABASE_URL": "https://test.supabase.co",
            "SUPABASE_ANON_KEY": "test-anon-key",
            "SUPABASE_SERVICE_ROLE_KEY": "test-service-key",
            "ENCRYPTION_KEY": VALID_FERNET_KEY,
            "TASK_SIGNING_SECRET": "test-task-secret",
        }):
            from packages.quantum.security import config
            import importlib
            importlib.reload(config)

            # Should not raise any exception
            config.validate_security_config()
