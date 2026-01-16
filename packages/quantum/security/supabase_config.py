"""
Unified Supabase Configuration

This module provides a single source of truth for Supabase client configuration
across the backend and worker. It ensures:
- Consistent environment variable resolution
- Clear distinction between admin and anon clients
- Actionable warnings for misconfigurations
- Safe defaults for development vs production
"""

import os
from pathlib import Path
from typing import Optional, List, Tuple
from dataclasses import dataclass
from enum import Enum

from supabase import create_client, Client


class KeyType(Enum):
    SERVICE_ROLE = "service_role"
    ANON = "anon"
    NONE = "none"


@dataclass
class SupabaseConfig:
    """Validated Supabase configuration."""
    url: Optional[str]
    service_role_key: Optional[str]
    anon_key: Optional[str]
    jwt_secret: Optional[str]

    # Diagnostics
    url_source: str = "not_found"
    service_key_source: str = "not_found"
    anon_key_source: str = "not_found"
    warnings: List[str] = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


def _find_repo_root() -> Path:
    """Find repository root by looking for marker files."""
    current = Path(__file__).resolve().parent
    for _ in range(10):
        if (current / "pnpm-workspace.yaml").exists() or (current / ".git").exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    # Fallback: packages/quantum/security/supabase_config.py -> 4 levels up
    return Path(__file__).resolve().parent.parent.parent.parent


def _load_env_files() -> List[str]:
    """
    Load environment files in priority order.
    Returns list of files that were loaded.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return []

    repo_root = _find_repo_root()
    loaded = []

    # Priority order (first match wins per variable)
    env_files = [
        repo_root / ".env.local",
        repo_root / ".env",
        repo_root / "packages" / "quantum" / ".env.local",
        repo_root / "packages" / "quantum" / ".env",
    ]

    for env_file in env_files:
        if env_file.exists():
            load_dotenv(env_file, override=False)
            loaded.append(str(env_file))

    return loaded


# Load env files on module import
_ENV_FILES_LOADED = _load_env_files()


def _get_env_with_source(primary: str, *fallbacks: str) -> Tuple[Optional[str], str]:
    """
    Get environment variable with fallbacks, returning (value, source_name).
    """
    value = os.getenv(primary)
    if value:
        return value, primary

    for fallback in fallbacks:
        value = os.getenv(fallback)
        if value:
            return value, f"{fallback} (fallback)"

    return None, "not_found"


def _mask_url(url: Optional[str]) -> str:
    """Mask URL for safe logging (show host only)."""
    if not url:
        return "N/A"
    try:
        # Extract host from URL
        if "://" in url:
            host = url.split("://")[1].split("/")[0]
            return f"...{host}"
        return url[:20] + "..." if len(url) > 20 else url
    except Exception:
        return "***"


def _mask_key(key: Optional[str]) -> str:
    """Mask key for safe logging."""
    if not key:
        return "N/A"
    if len(key) < 12:
        return "***"
    return f"{key[:6]}...{key[-4:]}"


def _is_production_url(url: Optional[str]) -> bool:
    """Check if URL points to production Supabase (not localhost)."""
    if not url:
        return False
    return "localhost" not in url and "127.0.0.1" not in url


def load_supabase_config() -> SupabaseConfig:
    """
    Load and validate Supabase configuration from environment.

    Environment variable precedence:
    - URL: SUPABASE_URL > NEXT_PUBLIC_SUPABASE_URL
    - Service Key: SUPABASE_SERVICE_ROLE_KEY > SUPABASE_SERVICE_KEY
    - Anon Key: SUPABASE_ANON_KEY > NEXT_PUBLIC_SUPABASE_ANON_KEY
    - JWT Secret: SUPABASE_JWT_SECRET

    Returns SupabaseConfig with warnings for any issues detected.
    """
    warnings = []

    # URL resolution
    url, url_source = _get_env_with_source(
        "SUPABASE_URL",
        "NEXT_PUBLIC_SUPABASE_URL"
    )

    # Service role key (for admin operations)
    service_key, service_key_source = _get_env_with_source(
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_SERVICE_KEY"
    )

    # Anon key (for user-scoped operations)
    anon_key, anon_key_source = _get_env_with_source(
        "SUPABASE_ANON_KEY",
        "NEXT_PUBLIC_SUPABASE_ANON_KEY"
    )

    # JWT secret (for token verification)
    jwt_secret = os.getenv("SUPABASE_JWT_SECRET")

    # --- Consistency Checks ---

    # Check for NEXT_PUBLIC_* usage in backend (warning only)
    if "NEXT_PUBLIC" in url_source:
        warnings.append(
            f"Using frontend env var {url_source} for URL. "
            "Set SUPABASE_URL in backend .env for clarity."
        )

    if "NEXT_PUBLIC" in anon_key_source:
        warnings.append(
            f"Using frontend env var {anon_key_source} for anon key. "
            "Set SUPABASE_ANON_KEY in backend .env for clarity."
        )

    # Check for production URL with missing service key
    if _is_production_url(url) and not service_key:
        warnings.append(
            "Production Supabase URL detected but SUPABASE_SERVICE_ROLE_KEY is missing. "
            "Admin operations will fail."
        )

    # Check for local URL (informational)
    if url and ("localhost" in url or "127.0.0.1" in url):
        # Local Supabase - this is fine for dev
        pass

    return SupabaseConfig(
        url=url,
        service_role_key=service_key,
        anon_key=anon_key,
        jwt_secret=jwt_secret,
        url_source=url_source,
        service_key_source=service_key_source,
        anon_key_source=anon_key_source,
        warnings=warnings,
    )


def create_admin_client(config: Optional[SupabaseConfig] = None) -> Tuple[Optional[Client], KeyType, List[str]]:
    """
    Create a Supabase admin client using the service role key.

    Returns:
        (client, key_type, warnings)
        - client: Supabase client or None if creation failed
        - key_type: Which key was used (SERVICE_ROLE, ANON, or NONE)
        - warnings: List of warning messages
    """
    if config is None:
        config = load_supabase_config()

    warnings = list(config.warnings)

    if not config.url:
        warnings.append("Supabase URL not configured. Set SUPABASE_URL in .env")
        return None, KeyType.NONE, warnings

    # Prefer service role key
    if config.service_role_key:
        try:
            client = create_client(config.url, config.service_role_key)
            return client, KeyType.SERVICE_ROLE, warnings
        except Exception as e:
            warnings.append(f"Failed to create admin client: {e}")
            return None, KeyType.NONE, warnings

    # Fallback to anon key with warning
    if config.anon_key:
        warnings.append(
            "SUPABASE_SERVICE_ROLE_KEY not set. Using anon key for admin client. "
            "Some operations (RPC calls, bypassing RLS) will fail."
        )
        try:
            client = create_client(config.url, config.anon_key)
            return client, KeyType.ANON, warnings
        except Exception as e:
            warnings.append(f"Failed to create client with anon key: {e}")
            return None, KeyType.NONE, warnings

    warnings.append(
        "No Supabase keys configured. Set SUPABASE_SERVICE_ROLE_KEY and SUPABASE_ANON_KEY in .env"
    )
    return None, KeyType.NONE, warnings


def create_anon_client(config: Optional[SupabaseConfig] = None) -> Tuple[Optional[Client], List[str]]:
    """
    Create a Supabase client using the anon key (for user-scoped operations).

    Returns:
        (client, warnings)
    """
    if config is None:
        config = load_supabase_config()

    warnings = list(config.warnings)

    if not config.url:
        warnings.append("Supabase URL not configured.")
        return None, warnings

    if not config.anon_key:
        warnings.append("SUPABASE_ANON_KEY not configured.")
        return None, warnings

    try:
        client = create_client(config.url, config.anon_key)
        return client, warnings
    except Exception as e:
        warnings.append(f"Failed to create anon client: {e}")
        return None, warnings


def validate_admin_connection(client: Client, table: str = "scanner_universe") -> Tuple[bool, Optional[str]]:
    """
    Validate admin client can connect by fetching from a table.

    Returns:
        (success, error_message)
    """
    if not client:
        return False, "No client provided"

    try:
        client.table(table).select("*").limit(1).execute()
        return True, None
    except Exception as e:
        error_str = str(e)

        # Provide actionable error messages
        if "401" in error_str or "Invalid API key" in error_str:
            return False, (
                "401 Invalid API key. This usually means:\n"
                "  1. SUPABASE_SERVICE_ROLE_KEY is wrong or expired\n"
                "  2. Using anon key instead of service role key\n"
                "  3. Key doesn't match the Supabase URL (dev key with prod URL)\n"
                "Check packages/quantum/.env and ensure SUPABASE_SERVICE_ROLE_KEY is correct."
            )
        elif "PGRST" in error_str:
            return False, f"PostgREST error: {error_str}"
        else:
            return False, f"Connection failed: {error_str}"


def print_config_summary(config: SupabaseConfig, key_type: KeyType, validated: bool):
    """Print a clean summary of Supabase configuration."""
    print("\n" + "=" * 60)
    print("SUPABASE CONFIGURATION")
    print("=" * 60)
    print(f"  URL:         {_mask_url(config.url)}")
    print(f"  URL Source:  {config.url_source}")
    print(f"  Key Type:    {key_type.value}")
    print(f"  Key Source:  {config.service_key_source if key_type == KeyType.SERVICE_ROLE else config.anon_key_source}")
    print(f"  Validated:   {'✅ Yes' if validated else '❌ No'}")

    if config.warnings:
        print("\n⚠️  WARNINGS:")
        for w in config.warnings:
            print(f"    - {w}")

    if _ENV_FILES_LOADED:
        print(f"\n  Env files loaded: {', '.join(_ENV_FILES_LOADED)}")
    else:
        print("\n  Env files loaded: (none)")

    print("=" * 60 + "\n")
