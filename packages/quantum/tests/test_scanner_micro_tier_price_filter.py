"""Tests for micro-tier universe price filter (#85, 2026-04-27).

Filter inserted at options_scanner._apply_tier_price_filter, called
immediately after the batch quotes_map fetch in scan_for_opportunities.
For micro tier accounts, drops symbols whose underlying price exceeds
MICRO_TIER_MAX_UNDERLYING (default $50). Aligns with existing
spread-width split at line ~1084 (2.5-wide for sub-$50 underlyings,
5-wide above) so sub-threshold names produce contracts that fit the
micro-tier $450 budget.

Tests instantiate the helper directly with a mock quotes_map. No
Polygon, Supabase, or scanner-flow mocking — pure unit tests.
"""

import os
import unittest
from unittest.mock import patch

from packages.quantum.options_scanner import (
    _apply_tier_price_filter,
    _get_micro_tier_max_underlying,
)


class _FakeRejectionStats:
    """Minimal stand-in for RejectionStats — counts record() calls."""

    def __init__(self):
        self.counts = {}

    def record(self, reason: str):
        self.counts[reason] = self.counts.get(reason, 0) + 1


def _quote(price=None, bid=None, ask=None, mid=None, last=None):
    """Build a snapshot_many-shaped quote dict."""
    q = {}
    if last is not None:
        q["last"] = last
    if mid is not None:
        q["mid"] = mid
    if bid is not None:
        q["bid"] = bid
    if ask is not None:
        q["ask"] = ask
    if price is not None and "last" not in q:
        q["last"] = price
    return {"quote": q}


class TestMicroTierFilter(unittest.TestCase):

    def setUp(self):
        self.stats = _FakeRejectionStats()
        self.quotes = {
            "F": _quote(last=20.0),
            "BAC": _quote(last=48.0),
            "AAPL": _quote(last=200.0),
            "AMZN": _quote(last=1247.0),
        }
        self.symbols = ["F", "BAC", "AAPL", "AMZN"]

    def test_micro_filters_above_threshold(self):
        kept = _apply_tier_price_filter(
            self.symbols, self.quotes, "micro", self.stats,
        )
        self.assertEqual(set(kept), {"F", "BAC"})
        self.assertNotIn("AAPL", kept)
        self.assertNotIn("AMZN", kept)

    def test_small_tier_no_filter(self):
        kept = _apply_tier_price_filter(
            self.symbols, self.quotes, "small", self.stats,
        )
        self.assertEqual(set(kept), set(self.symbols))
        self.assertEqual(self.stats.counts, {})

    def test_standard_tier_no_filter(self):
        kept = _apply_tier_price_filter(
            self.symbols, self.quotes, "standard", self.stats,
        )
        self.assertEqual(set(kept), set(self.symbols))

    def test_no_account_tier_param(self):
        kept = _apply_tier_price_filter(
            self.symbols, self.quotes, None, self.stats,
        )
        self.assertEqual(set(kept), set(self.symbols))


class TestThresholdBoundary(unittest.TestCase):

    def setUp(self):
        self.stats = _FakeRejectionStats()

    def test_threshold_boundary_kept(self):
        # Exactly $50.00 — kept (≤ threshold, not <).
        quotes = {"X": _quote(last=50.0)}
        kept = _apply_tier_price_filter(
            ["X"], quotes, "micro", self.stats,
        )
        self.assertEqual(kept, ["X"])

    def test_threshold_just_above(self):
        quotes = {"Y": _quote(last=50.01)}
        kept = _apply_tier_price_filter(
            ["Y"], quotes, "micro", self.stats,
        )
        self.assertEqual(kept, [])
        self.assertEqual(self.stats.counts.get("micro_tier_underlying_too_high"), 1)


class TestQuoteShape(unittest.TestCase):

    def setUp(self):
        self.stats = _FakeRejectionStats()

    def test_missing_quotes_pass_through(self):
        # Symbol has no entry in quotes_map — pass through to downstream
        # missing_quotes rejection (don't drop on data errors).
        quotes = {"F": _quote(last=20.0)}  # no entry for "X"
        kept = _apply_tier_price_filter(
            ["F", "X"], quotes, "micro", self.stats,
        )
        self.assertIn("X", kept)
        self.assertNotIn(
            "micro_tier_underlying_too_high",
            self.stats.counts,
            "Missing quote should not increment the tier-filter counter "
            "(downstream missing_quotes path owns this case).",
        )

    def test_uses_mid_when_no_last(self):
        # Quote provides only bid/ask, no last/mid — filter computes mid.
        quotes = {"Z": {"quote": {"bid": 19.0, "ask": 21.0}}}  # mid=20
        kept = _apply_tier_price_filter(
            ["Z"], quotes, "micro", self.stats,
        )
        self.assertEqual(kept, ["Z"])

    def test_uses_explicit_mid_field(self):
        quotes = {"Z": {"quote": {"mid": 30.0}}}
        kept = _apply_tier_price_filter(
            ["Z"], quotes, "micro", self.stats,
        )
        self.assertEqual(kept, ["Z"])

    def test_unparseable_quote_passes_through(self):
        # last/mid/bid/ask all missing → price=None → kept.
        quotes = {"W": {"quote": {}}}
        kept = _apply_tier_price_filter(
            ["W"], quotes, "micro", self.stats,
        )
        self.assertEqual(kept, ["W"])


class TestEnvOverride(unittest.TestCase):

    def test_env_override_lowers_threshold(self):
        # Default threshold $50 keeps BAC@$48; lowering to $40 filters it.
        with patch.dict(os.environ, {"MICRO_TIER_MAX_UNDERLYING": "40.0"}):
            stats = _FakeRejectionStats()
            quotes = {"BAC": _quote(last=48.0)}
            kept = _apply_tier_price_filter(
                ["BAC"], quotes, "micro", stats,
            )
            self.assertEqual(kept, [])
            self.assertEqual(
                stats.counts.get("micro_tier_underlying_too_high"), 1,
            )

    def test_env_override_raises_threshold(self):
        # Threshold $200 keeps AAPL@$200 (boundary kept).
        with patch.dict(os.environ, {"MICRO_TIER_MAX_UNDERLYING": "200.0"}):
            stats = _FakeRejectionStats()
            quotes = {"AAPL": _quote(last=200.0)}
            kept = _apply_tier_price_filter(
                ["AAPL"], quotes, "micro", stats,
            )
            self.assertEqual(kept, ["AAPL"])

    def test_invalid_env_falls_back_to_default(self):
        with patch.dict(os.environ, {"MICRO_TIER_MAX_UNDERLYING": "not_a_number"}):
            self.assertEqual(_get_micro_tier_max_underlying(), 50.0)


class TestRejectionStats(unittest.TestCase):

    def test_rejection_stats_increment(self):
        stats = _FakeRejectionStats()
        quotes = {
            "AAPL": _quote(last=200.0),
            "AMZN": _quote(last=1200.0),
            "MSFT": _quote(last=400.0),
        }
        kept = _apply_tier_price_filter(
            ["AAPL", "AMZN", "MSFT"], quotes, "micro", stats,
        )
        self.assertEqual(kept, [])
        self.assertEqual(
            stats.counts.get("micro_tier_underlying_too_high"), 3,
        )


class TestModuleSyntaxValid(unittest.TestCase):
    """Source-level syntax check on options_scanner.py post-edits.

    Matches the H4 doctrine convention from
    test_workflow_orchestrator_alerts.py. Cheap guard against this
    PR's edits introducing a SyntaxError that the unit tests wouldn't
    otherwise catch (since they import the helper directly, the rest
    of the module would parse on first import).
    """

    def test_module_parses(self):
        import ast

        path = os.path.join(
            os.path.dirname(__file__), "..", "options_scanner.py",
        )
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        try:
            ast.parse(src)
        except SyntaxError as e:
            self.fail(f"options_scanner.py has a syntax error: {e}")


if __name__ == "__main__":
    unittest.main()
