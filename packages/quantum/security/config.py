"""
Security Configuration Module (Security v4)

This module validates required environment variables and enforces security
constraints at startup. If constraints are violated, the server will not start.

Production Hardening (v4):
- ENABLE_DEV_AUTH_BYPASS is a hard failure in production (not just a warning)
- Debug routes can be explicitly enabled via ENABLE_DEBUG_ROUTES=1
"""

import os
from typing import List


# =============================================================================
# Required Environment Variables
# =============================================================================

REQUIRED_ENV_VARS = [
    "SUPABASE_JWT_SECRET",
    "NEXT_PUBLIC_SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "ENCRYPTION_KEY",
]

OPTIONAL_ENV_VARS = [
    "TASK_SIGNING_SECRET",  # Required if tasks are enabled/exposed
]

# =============================================================================
# Trading Environment Variables (v4-L1F Optimization)
# =============================================================================

TRADING_ENV_VARS = [
    "POLYGON_API_KEY",  # Required for market data fetching
]


# =============================================================================
# Environment Detection
# =============================================================================

def is_production_env() -> bool:
    """Check if we're running in production environment."""
    return os.getenv("APP_ENV") == "production"


def is_dev_bypass_enabled() -> bool:
    """Check if dev auth bypass is enabled."""
    return os.getenv("ENABLE_DEV_AUTH_BYPASS") == "1"


def is_debug_routes_enabled() -> bool:
    """Check if debug routes should be registered."""
    # In development, enable by default unless explicitly disabled
    # In production, require explicit enablement
    app_env = os.getenv("APP_ENV", "development")
    explicit_setting = os.getenv("ENABLE_DEBUG_ROUTES")

    if explicit_setting is not None:
        return explicit_setting == "1"

    # Default: enabled in dev/test, disabled in production
    return app_env in ("development", "test")


# =============================================================================
# Security Validation
# =============================================================================

class SecurityConfigError(Exception):
    """Raised when security configuration is invalid."""
    pass


def validate_security_config():
    """
    Validates that all required security-related environment variables are present.
    Raises SecurityConfigError if any critical constraints are violated.

    Security v4 Enforcement:
    - Missing required env vars -> abort startup
    - ENABLE_DEV_AUTH_BYPASS in production -> abort startup (not just warning)
    """
    missing = []
    for var in REQUIRED_ENV_VARS:
        if not os.getenv(var):
            missing.append(var)

    if missing:
        raise SecurityConfigError(
            f"CRITICAL SECURITY ERROR: Missing required environment variables: {', '.join(missing)}. "
            "Server startup aborted."
        )

    # Check TASK_SIGNING_SECRET if we are likely to run tasks (default assumption yes)
    if not os.getenv("TASK_SIGNING_SECRET"):
        print("⚠️ WARNING: TASK_SIGNING_SECRET is missing. Internal task endpoints will fail verification.")

    # =============================================================================
    # Security v4: Hard failure for dev bypass in production
    # =============================================================================
    if is_production_env() and is_dev_bypass_enabled():
        raise SecurityConfigError(
            "CRITICAL SECURITY ERROR: ENABLE_DEV_AUTH_BYPASS=1 is set in production environment!\n"
            "This is a severe security risk that allows unauthenticated access.\n"
            "Remove ENABLE_DEV_AUTH_BYPASS from production environment variables.\n"
            "Server startup aborted."
        )


class TradingConfigError(Exception):
    """Raised when trading configuration is invalid."""
    pass


def validate_trading_config():
    """
    v4-L1F Optimization: Validates trading-related environment variables at startup.

    In production: Missing POLYGON_API_KEY is a hard failure
    In development: Missing POLYGON_API_KEY is a warning (allows mock data testing)
    """
    missing = []
    for var in TRADING_ENV_VARS:
        if not os.getenv(var):
            missing.append(var)

    if missing:
        if is_production_env():
            raise TradingConfigError(
                f"CRITICAL TRADING CONFIG ERROR: Missing required environment variables: {', '.join(missing)}. "
                "Paper trading and live execution will fail without market data. "
                "Server startup aborted."
            )
        else:
            # In development, warn but allow startup (supports mock data testing)
            print(f"⚠️ WARNING: Missing trading environment variables: {', '.join(missing)}. "
                  "Market data fetches will fail or use mock data.")
