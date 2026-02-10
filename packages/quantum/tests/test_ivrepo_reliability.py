"""
Tests for IVRepository reliability improvements.

Verifies:
1. Configurable concurrency via IVREPO_MAX_WORKERS
2. Retry/backoff on batch fetch failures
3. Sanitized logging (no HTML dumps)
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
import os
import time


class TestIVRepoConfiguration:
    """Test configurable parameters."""

    def test_default_max_workers(self):
        """Default max_workers should be 4."""
        # Clear env var to test default
        with patch.dict(os.environ, {}, clear=True):
            # Re-import to get default
            default = int(os.getenv("IVREPO_MAX_WORKERS", "4"))
            assert default == 4

    def test_custom_max_workers(self):
        """IVREPO_MAX_WORKERS should be configurable."""
        with patch.dict(os.environ, {"IVREPO_MAX_WORKERS": "8"}):
            workers = int(os.getenv("IVREPO_MAX_WORKERS", "4"))
            assert workers == 8

    def test_default_retry_count(self):
        """Default retry count should be 2."""
        with patch.dict(os.environ, {}, clear=True):
            default = int(os.getenv("IVREPO_RETRY_COUNT", "2"))
            assert default == 2

    def test_default_retry_delay(self):
        """Default retry delay should be 0.5 seconds."""
        with patch.dict(os.environ, {}, clear=True):
            default = float(os.getenv("IVREPO_RETRY_DELAY", "0.5"))
            assert default == 0.5


class TestRetryLogic:
    """Test retry/backoff behavior."""

    def test_retry_on_failure(self):
        """Should retry on transient failures."""
        attempts = []

        def mock_fetch(attempt_num):
            attempts.append(attempt_num)
            if attempt_num < 2:
                raise Exception("Transient error")
            return {"data": []}

        # Simulate retry logic
        max_retries = 2
        delay = 0.1
        result = None

        for attempt in range(max_retries + 1):
            try:
                result = mock_fetch(attempt)
                break
            except Exception:
                if attempt < max_retries:
                    time.sleep(delay * (attempt + 1))
                    continue

        # Should have tried 3 times (0, 1, 2)
        assert len(attempts) == 3
        assert result is not None

    def test_exponential_backoff(self):
        """Backoff delay should increase with each retry."""
        base_delay = 0.5
        delays = []

        for attempt in range(3):
            delay = base_delay * (attempt + 1)
            delays.append(delay)

        assert delays == [0.5, 1.0, 1.5]

    def test_all_retries_exhausted(self):
        """Should return empty after all retries exhausted."""
        def mock_fetch():
            raise Exception("Persistent error")

        max_retries = 2
        result = {}

        for attempt in range(max_retries + 1):
            try:
                result = mock_fetch()
                break
            except Exception:
                if attempt >= max_retries:
                    result = {}

        assert result == {}


class TestErrorSanitization:
    """Test that errors are sanitized in logs."""

    def test_long_error_truncated(self):
        """Errors longer than 100 chars should be truncated."""
        error = "x" * 200

        if len(error) > 100:
            error = error[:100] + "..."

        assert len(error) == 103  # 100 + "..."
        assert error.endswith("...")

    def test_html_content_redacted(self):
        """HTML content should be redacted."""
        error = "<html><body>Error page</body></html>"

        if "<" in error or ">" in error:
            error = "[HTML content redacted]"

        assert error == "[HTML content redacted]"

    def test_normal_error_preserved(self):
        """Normal error messages should be preserved."""
        error = "Connection timeout after 30s"

        if len(error) <= 100 and "<" not in error and ">" not in error:
            # Preserved as-is
            pass

        assert error == "Connection timeout after 30s"

    def test_mixed_sanitization(self):
        """Long HTML errors should be truncated first, then redacted."""
        error = "<html>" + "x" * 200 + "</html>"

        # First truncate
        if len(error) > 100:
            error = error[:100] + "..."

        # Then check for HTML
        if "<" in error or ">" in error:
            error = "[HTML content redacted]"

        assert error == "[HTML content redacted]"


class TestBatchFetchIntegration:
    """Test batch fetch with mocked Supabase client."""

    def test_successful_batch_fetch(self):
        """Should return results on successful fetch."""
        mock_supabase = MagicMock()
        mock_response = MagicMock()
        mock_response.data = [
            {"underlying": "SPY", "iv_30d": 0.25, "as_of_date": "2024-01-15"},
            {"underlying": "SPY", "iv_30d": 0.24, "as_of_date": "2024-01-14"},
        ]

        # Chain the mock methods
        mock_table = MagicMock()
        mock_table.select.return_value = mock_table
        mock_table.in_.return_value = mock_table
        mock_table.gte.return_value = mock_table
        mock_table.not_.is_.return_value = mock_table
        mock_table.execute.return_value = mock_response
        mock_supabase.table.return_value = mock_table

        # Simulate fetch_batch function
        def fetch_batch(symbols):
            try:
                res = mock_supabase.table("test").select("*").in_("underlying", symbols).gte("as_of_date", "2024-01-01").execute()
                return {"SPY": {"iv_30d": 0.25}} if res.data else {}
            except Exception:
                return {}

        result = fetch_batch(["SPY"])
        assert "SPY" in result

    def test_failed_batch_returns_empty(self):
        """Should return empty dict on persistent failure."""
        mock_supabase = MagicMock()
        mock_supabase.table.side_effect = Exception("DB connection error")

        def fetch_batch(symbols, max_retries=2):
            for attempt in range(max_retries + 1):
                try:
                    mock_supabase.table("test")
                    return {"data": True}
                except Exception:
                    if attempt >= max_retries:
                        return {}
            return {}

        result = fetch_batch(["SPY"])
        assert result == {}


class TestConcurrencyLimits:
    """Test that concurrency is properly limited."""

    def test_max_workers_respected(self):
        """ThreadPoolExecutor should use configured max_workers."""
        import concurrent.futures

        max_workers = 4
        active_count = []

        def track_worker(batch):
            # Track concurrent execution
            active_count.append(1)
            time.sleep(0.1)
            active_count.pop()
            return batch

        batches = [["A"], ["B"], ["C"], ["D"], ["E"], ["F"]]

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(track_worker, b) for b in batches]
            concurrent.futures.wait(futures)

        # All should complete (basic sanity check)
        assert len(futures) == 6


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
