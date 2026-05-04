"""Regression tests for AlpacaClient.get_account wrapper field shape.

The wrapper at packages/quantum/brokers/alpaca_client.py:get_account
returns a hand-built dict with a fixed whitelist of fields. Pre-2026-05-04
the whitelist dropped `options_buying_power`, which broke
equity_state.get_alpaca_options_buying_power (PR #849 for #93) silently —
it called `acct.get("options_buying_power")` on the wrapper's output, got
None, and fell back to paper_baseline_capital. Three days of stale
deployable_capital readings before the diagnostic surfaced it.

These tests guard against re-deletion of the field from the whitelist.
"""

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


WRAPPER_PATH = (
    Path(__file__).parent.parent / "brokers" / "alpaca_client.py"
)


class TestSourceLevelGuard(unittest.TestCase):
    """Cheap insurance against future whitelist trims."""

    def test_get_account_dict_includes_options_buying_power(self):
        src = WRAPPER_PATH.read_text(encoding="utf-8")
        self.assertIn(
            '"options_buying_power"', src,
            "AlpacaClient.get_account wrapper dict must expose "
            "options_buying_power. Read by "
            "equity_state.get_alpaca_options_buying_power (PR #849 / #93). "
            "Removing this field silently regresses to paper_baseline_capital "
            "fallback — see 2026-05-04 OBP-divergence diagnostic.",
        )


class TestBehavioralWrapperShape(unittest.TestCase):
    """Verify the wrapper actually reads and exposes options_buying_power
    from the underlying alpaca-py Account object."""

    def _build_alpaca_client(self, mock_account):
        """Construct an AlpacaClient with the underlying alpaca-py
        client patched to return mock_account from get_account()."""
        from packages.quantum.brokers.alpaca_client import AlpacaClient
        # Bypass __init__'s credential bootstrap by constructing without
        # going through the normal init path — patch the inner client
        # directly and stub _call_with_retry to invoke the callable.
        client = AlpacaClient.__new__(AlpacaClient)
        client._client = MagicMock()
        client._client.get_account.return_value = mock_account
        client.paper = False
        client._call_with_retry = lambda fn, *a, **kw: fn(*a, **kw)
        return client

    def _make_mock_account(self, **overrides):
        """Mock alpaca-py Account with the fields get_account reads."""
        mock = MagicMock()
        mock.id = "test-account-id"
        mock.status = "ACTIVE"
        mock.equity = "617.75"
        mock.cash = "617.75"
        mock.buying_power = "617.75"
        mock.options_buying_power = "417.75"
        mock.portfolio_value = "617.75"
        mock.pattern_day_trader = False
        mock.daytrade_count = 0
        mock.daytrading_buying_power = "0"
        for k, v in overrides.items():
            setattr(mock, k, v)
        return mock

    def test_get_account_exposes_options_buying_power(self):
        """Wrapper output dict has options_buying_power as a top-level key
        with the float-coerced value from the underlying Account object."""
        mock_acct = self._make_mock_account()
        client = self._build_alpaca_client(mock_acct)

        result = client.get_account()
        self.assertIn("options_buying_power", result)
        self.assertEqual(result["options_buying_power"], 417.75)

    def test_get_account_preserves_none_when_field_absent(self):
        """If alpaca-py returns None for options_buying_power (e.g.,
        account without options approval), the wrapper preserves None
        rather than coercing to 0.0. equity_state helper relies on this
        distinction."""
        mock_acct = self._make_mock_account(options_buying_power=None)
        client = self._build_alpaca_client(mock_acct)

        result = client.get_account()
        self.assertIn("options_buying_power", result)
        self.assertIsNone(result["options_buying_power"])

    def test_get_account_preserves_existing_fields(self):
        """The new field doesn't clobber any existing wrapper output."""
        mock_acct = self._make_mock_account()
        client = self._build_alpaca_client(mock_acct)

        result = client.get_account()
        # All pre-existing keys must still be present and correct.
        self.assertEqual(result["account_id"], "test-account-id")
        self.assertEqual(result["status"], "ACTIVE")
        self.assertEqual(result["equity"], 617.75)
        self.assertEqual(result["cash"], 617.75)
        self.assertEqual(result["buying_power"], 617.75)
        self.assertEqual(result["portfolio_value"], 617.75)
        self.assertFalse(result["pattern_day_trader"])
        self.assertEqual(result["daytrade_count"], 0)
        self.assertEqual(result["daytrading_buying_power"], 0.0)
        self.assertFalse(result["paper"])


if __name__ == "__main__":
    unittest.main()
