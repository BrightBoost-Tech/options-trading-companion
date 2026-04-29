"""Tests for micro-tier spread threshold (#92, 2026-04-29).

Tier-aware loosening of the spread_too_wide rejection gate at
options_scanner.py:~2286. Default 0.30 (30%) for micro tier;
standard/small tiers continue to use the regime-keyed defaults
(0.10-0.20). Configured via MICRO_TIER_SPREAD_THRESHOLD env var.

Architecturally parallels MICRO_TIER_MAX_UNDERLYING (universe price
filter) and tier-aware sizing (#828).

Tests instantiate the helper directly. Dispatch wiring + max()
preservation verified at source level (matching H4a/b/c precedent
since options_scanner.py has the same heavy dependency tree as
workflow_orchestrator).
"""

import ast
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from packages.quantum.options_scanner import (
    _get_micro_tier_spread_threshold,
)


class TestEnvOverride(unittest.TestCase):
    """Verify MICRO_TIER_SPREAD_THRESHOLD env var override behavior."""

    def test_default_when_env_unset(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MICRO_TIER_SPREAD_THRESHOLD", None)
            self.assertEqual(_get_micro_tier_spread_threshold(), 0.30)

    def test_env_override_to_higher(self):
        with patch.dict(os.environ, {"MICRO_TIER_SPREAD_THRESHOLD": "0.50"}):
            self.assertEqual(_get_micro_tier_spread_threshold(), 0.50)

    def test_env_override_to_lower(self):
        # Lower than default is permitted — the dispatch uses max(regime,
        # micro_override) so a lower micro override would not REDUCE the
        # threshold below the regime default. Helper returns the literal
        # env value.
        with patch.dict(os.environ, {"MICRO_TIER_SPREAD_THRESHOLD": "0.05"}):
            self.assertEqual(_get_micro_tier_spread_threshold(), 0.05)

    def test_invalid_env_falls_back_to_default(self):
        with patch.dict(
            os.environ, {"MICRO_TIER_SPREAD_THRESHOLD": "not-a-number"},
        ):
            self.assertEqual(_get_micro_tier_spread_threshold(), 0.30)

    def test_empty_string_env_falls_back_to_default(self):
        with patch.dict(os.environ, {"MICRO_TIER_SPREAD_THRESHOLD": ""}):
            self.assertEqual(_get_micro_tier_spread_threshold(), 0.30)


class TestDispatchWiring(unittest.TestCase):
    """Source-level structural assertions on options_scanner.py.

    Avoids re-importing the scanner under test conditions (heavy
    transitive deps). Same convention as
    test_workflow_orchestrator_alerts.py for #72-H4 sites.
    """

    @classmethod
    def setUpClass(cls):
        path = Path(__file__).parent.parent / "options_scanner.py"
        with open(path, "r", encoding="utf-8") as f:
            cls.src = f.read()

    def test_helper_defined(self):
        self.assertIn(
            "def _get_micro_tier_spread_threshold(", self.src,
            "Helper _get_micro_tier_spread_threshold must be defined "
            "in options_scanner.py.",
        )

    def test_helper_reads_correct_env_var(self):
        self.assertIn(
            'os.getenv("MICRO_TIER_SPREAD_THRESHOLD"', self.src,
            "Helper must read MICRO_TIER_SPREAD_THRESHOLD env var.",
        )

    def test_dispatch_gated_on_micro_tier(self):
        self.assertIn(
            'if account_tier == "micro":', self.src,
            "Threshold dispatch must be gated by "
            "`if account_tier == \"micro\":` so other tiers are unaffected.",
        )

    def test_dispatch_uses_max_not_replace(self):
        self.assertIn(
            "max(threshold, _get_micro_tier_spread_threshold())", self.src,
            "Dispatch must use max(regime_default, micro_override) "
            "to preserve regime loosening — when SUPPRESSED gives 0.20 "
            "and micro override is 0.30, micro stays at 0.30; if a future "
            "config sets micro to 0.05 (lower), regime default still wins.",
        )

    def test_helper_called_in_micro_branch(self):
        # The helper invocation must live inside the micro-tier dispatch
        # block (within ~200 chars of the `if account_tier == "micro":`
        # line) — not be referenced from some unrelated path.
        anchor = self.src.find('if account_tier == "micro":')
        self.assertGreater(
            anchor, 0, "Could not locate micro-tier dispatch.",
        )
        block = self.src[anchor:anchor + 300]
        self.assertIn(
            "_get_micro_tier_spread_threshold()", block,
            "Helper invocation must live inside the micro-tier block.",
        )


class TestModuleSyntaxValid(unittest.TestCase):
    """Cheap guard: the PR's edits must not introduce a SyntaxError."""

    def test_module_parses(self):
        path = Path(__file__).parent.parent / "options_scanner.py"
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        try:
            ast.parse(src)
        except SyntaxError as e:
            self.fail(f"options_scanner.py has a syntax error: {e}")


if __name__ == "__main__":
    unittest.main()
