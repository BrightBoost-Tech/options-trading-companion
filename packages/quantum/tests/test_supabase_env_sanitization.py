"""
Unit tests for Supabase environment variable sanitization.

Ensures get_sanitized_supabase_env() strips whitespace, validates URLs,
and respects SUPABASE_URL precedence over NEXT_PUBLIC_SUPABASE_URL.
"""
import unittest
from unittest.mock import patch, MagicMock
import sys

# Bypass version check
with patch.dict(sys.modules, {"packages.quantum.check_version": MagicMock()}):
    from packages.quantum.supabase_env import get_sanitized_supabase_env


class TestGetSanitizedSupabaseEnv(unittest.TestCase):

    @patch.dict("os.environ", {
        "NEXT_PUBLIC_SUPABASE_URL": "https://xyz.supabase.co\n",
        "SUPABASE_SERVICE_ROLE_KEY": "  test-key-123  ",
    }, clear=True)
    def test_strips_whitespace_and_newlines(self):
        """Trailing whitespace/newlines are stripped from URL and key."""
        url, key = get_sanitized_supabase_env()
        self.assertEqual(url, "https://xyz.supabase.co")
        self.assertEqual(key, "test-key-123")

    @patch.dict("os.environ", {
        "NEXT_PUBLIC_SUPABASE_URL": "  https://abc.supabase.co  \r\n",
        "SUPABASE_SERVICE_ROLE_KEY": "key\n",
    }, clear=True)
    def test_strips_carriage_return(self):
        """Carriage return and newline are stripped."""
        url, key = get_sanitized_supabase_env()
        self.assertEqual(url, "https://abc.supabase.co")
        self.assertEqual(key, "key")

    @patch.dict("os.environ", {
        "SUPABASE_URL": "https://preferred.supabase.co",
        "NEXT_PUBLIC_SUPABASE_URL": "https://fallback.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "key",
    }, clear=True)
    def test_supabase_url_takes_precedence(self):
        """SUPABASE_URL is preferred over NEXT_PUBLIC_SUPABASE_URL."""
        url, key = get_sanitized_supabase_env()
        self.assertEqual(url, "https://preferred.supabase.co")

    @patch.dict("os.environ", {
        "NEXT_PUBLIC_SUPABASE_URL": "https://fallback.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "key",
    }, clear=True)
    def test_falls_back_to_next_public(self):
        """Falls back to NEXT_PUBLIC_SUPABASE_URL when SUPABASE_URL is not set."""
        url, key = get_sanitized_supabase_env()
        self.assertEqual(url, "https://fallback.supabase.co")

    @patch.dict("os.environ", {
        "NEXT_PUBLIC_SUPABASE_URL": "xyz.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "key",
    }, clear=True)
    def test_invalid_url_no_scheme(self):
        """URL without http(s):// scheme returns None."""
        url, key = get_sanitized_supabase_env()
        self.assertIsNone(url)
        self.assertIsNone(key)

    @patch.dict("os.environ", {
        "NEXT_PUBLIC_SUPABASE_URL": "https://",
        "SUPABASE_SERVICE_ROLE_KEY": "key",
    }, clear=True)
    def test_invalid_url_no_hostname(self):
        """URL with scheme but no hostname returns None."""
        url, key = get_sanitized_supabase_env()
        self.assertIsNone(url)
        self.assertIsNone(key)

    @patch.dict("os.environ", {}, clear=True)
    def test_missing_env_vars(self):
        """Missing env vars return None without error."""
        url, key = get_sanitized_supabase_env()
        self.assertIsNone(url)
        self.assertIsNone(key)

    @patch.dict("os.environ", {
        "NEXT_PUBLIC_SUPABASE_URL": "https://xyz.supabase.co",
    }, clear=True)
    def test_missing_key(self):
        """URL present but key missing returns None."""
        url, key = get_sanitized_supabase_env()
        self.assertIsNone(url)
        self.assertIsNone(key)

    @patch.dict("os.environ", {
        "NEXT_PUBLIC_SUPABASE_URL": "http://localhost:54321",
        "SUPABASE_SERVICE_ROLE_KEY": "local-key",
    }, clear=True)
    def test_http_localhost_is_valid(self):
        """http:// scheme with localhost is valid (local dev)."""
        url, key = get_sanitized_supabase_env()
        self.assertEqual(url, "http://localhost:54321")
        self.assertEqual(key, "local-key")


if __name__ == "__main__":
    unittest.main()
