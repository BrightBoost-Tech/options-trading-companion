"""Tests for `get_alpaca_options_buying_power` helper at equity_state.py.

Part of #93 fix (2026-05-01): read Alpaca-authoritative
options_buying_power instead of stale Plaid + accumulated DB
reservations. Mirrors the existing `get_alpaca_equity` test pattern.
"""

import unittest
from unittest.mock import MagicMock, patch


class TestSourceLevelHelperPresent(unittest.TestCase):
    def test_helper_function_exists(self):
        from packages.quantum.services.equity_state import (
            get_alpaca_options_buying_power,
        )
        self.assertTrue(callable(get_alpaca_options_buying_power))

    def test_internal_fetcher_exists(self):
        from packages.quantum.services.equity_state import (
            _fetch_alpaca_options_buying_power,
        )
        self.assertTrue(callable(_fetch_alpaca_options_buying_power))


class TestBehavioralHelper(unittest.TestCase):
    def setUp(self):
        from packages.quantum.services.equity_state import (
            _reset_caches_for_testing,
        )
        _reset_caches_for_testing()

    def test_returns_obp_on_success(self):
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client"
        ) as mock_factory:
            mock_client = MagicMock()
            mock_client.get_account.return_value = {
                "options_buying_power": "500.00",
            }
            mock_factory.return_value = mock_client

            from packages.quantum.services.equity_state import (
                get_alpaca_options_buying_power,
            )
            result = get_alpaca_options_buying_power(
                "test-user-1", supabase=MagicMock(),
            )
            self.assertEqual(result, 500.0)

    def test_returns_none_on_alpaca_failure(self):
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            side_effect=Exception("Alpaca down"),
        ):
            from packages.quantum.services.equity_state import (
                get_alpaca_options_buying_power,
            )
            result = get_alpaca_options_buying_power(
                "test-user-2", supabase=MagicMock(),
            )
            self.assertIsNone(result)

    def test_returns_none_on_missing_field(self):
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client"
        ) as mock_factory:
            mock_client = MagicMock()
            mock_client.get_account.return_value = {}
            mock_factory.return_value = mock_client

            from packages.quantum.services.equity_state import (
                get_alpaca_options_buying_power,
            )
            result = get_alpaca_options_buying_power(
                "test-user-3", supabase=MagicMock(),
            )
            self.assertIsNone(result)

    def test_returns_none_when_client_unavailable(self):
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            return_value=None,
        ):
            from packages.quantum.services.equity_state import (
                get_alpaca_options_buying_power,
            )
            result = get_alpaca_options_buying_power(
                "test-user-4", supabase=MagicMock(),
            )
            self.assertIsNone(result)

    def test_negative_obp_clamped_to_zero(self):
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client"
        ) as mock_factory:
            mock_client = MagicMock()
            mock_client.get_account.return_value = {
                "options_buying_power": "-100.00",
            }
            mock_factory.return_value = mock_client

            from packages.quantum.services.equity_state import (
                get_alpaca_options_buying_power,
            )
            result = get_alpaca_options_buying_power(
                "test-user-5", supabase=MagicMock(),
            )
            self.assertEqual(result, 0.0)

    def test_cache_hit_avoids_second_alpaca_call(self):
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client"
        ) as mock_factory:
            mock_client = MagicMock()
            mock_client.get_account.return_value = {
                "options_buying_power": "500.00",
            }
            mock_factory.return_value = mock_client

            from packages.quantum.services.equity_state import (
                get_alpaca_options_buying_power,
            )
            get_alpaca_options_buying_power("test-user-cache", supabase=MagicMock())
            get_alpaca_options_buying_power("test-user-cache", supabase=MagicMock())
            # Cache should prevent the second factory invocation
            self.assertEqual(mock_factory.call_count, 1)


class TestAlertOnFailure(unittest.TestCase):
    """Critical alert with operator_action_required must fire on failure."""

    def setUp(self):
        from packages.quantum.services.equity_state import (
            _reset_caches_for_testing,
        )
        _reset_caches_for_testing()

    def test_critical_alert_emitted_on_failure(self):
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            side_effect=Exception("Alpaca timeout"),
        ), patch(
            "packages.quantum.services.equity_state.alert"
        ) as mock_alert:
            from packages.quantum.services.equity_state import (
                get_alpaca_options_buying_power,
            )
            get_alpaca_options_buying_power(
                "test-user-alert", supabase=MagicMock(),
            )

            self.assertEqual(mock_alert.call_count, 1)
            kwargs = mock_alert.call_args.kwargs
            self.assertEqual(
                kwargs.get("alert_type"),
                "alpaca_options_buying_power_query_failed",
            )
            self.assertEqual(kwargs.get("severity"), "critical")
            metadata = kwargs.get("metadata", {})
            self.assertIn("operator_action_required", metadata)
            self.assertIn("consequence", metadata)

    def test_alert_failure_does_not_break_fallback(self):
        """If alert path itself fails, the helper still returns None
        cleanly (no exception bubbles out)."""
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            side_effect=Exception("Alpaca down"),
        ), patch(
            "packages.quantum.services.equity_state.alert",
            side_effect=Exception("alert system down"),
        ):
            from packages.quantum.services.equity_state import (
                get_alpaca_options_buying_power,
            )
            # Must not raise
            result = get_alpaca_options_buying_power(
                "test-user-alert-fail", supabase=MagicMock(),
            )
            self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
