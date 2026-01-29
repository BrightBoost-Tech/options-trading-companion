"""
Supabase environment variable sanitization.

Provides a single helper to read, sanitize, and validate Supabase URL/key
from environment variables. Used by all _get_supabase_client() helpers
to prevent DNS failures from whitespace/newline in env vars.
"""
import logging
import os
from typing import Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def get_sanitized_supabase_env() -> Tuple[Optional[str], Optional[str]]:
    """
    Read and sanitize Supabase URL and service role key from environment.

    Precedence for URL: SUPABASE_URL > NEXT_PUBLIC_SUPABASE_URL
    Both values are stripped of whitespace/newlines.
    URL is validated for scheme and hostname.

    Returns:
        Tuple of (url, key) or (None, None) if missing or invalid.
    """
    # Read with precedence: SUPABASE_URL preferred over NEXT_PUBLIC_SUPABASE_URL
    raw_url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL") or ""
    raw_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or ""

    # Strip whitespace/newlines
    url = raw_url.strip()
    key = raw_key.strip()

    if not url or not key:
        return None, None

    # Validate URL scheme
    if not url.startswith(("http://", "https://")):
        logger.warning("[SUPABASE] Invalid URL: missing http(s):// scheme")
        return None, None

    # Parse and validate hostname
    parsed = urlparse(url)
    if not parsed.hostname:
        logger.warning("[SUPABASE] Invalid URL: no hostname found")
        return None, None

    # Log safe, non-secret connection info for DNS troubleshooting
    logger.info("[SUPABASE] url_host=%s scheme=%s", parsed.hostname, parsed.scheme)

    return url, key
