"""Tests for the loosened spread threshold: micro tier (#92, 2026-04-29)
re-keyed to PRICE CLASS (audit Area 6, 2026-06-09).

The 0.30 threshold's rationale was always price-class physics (per-leg
bid-ask fixed in dollars while premiums scale with underlying price), but
the dispatch was keyed to account_tier=='micro' alone — so when deployable
capital crossed the $1,000 micro→small cliff (2026-05-19→20) the gate
silently tightened 0.30→0.10 across the whole universe. The dispatch is now
`micro tier OR current_price < PRICE_CLASS_SPREAD_CUTOFF (default $60)`;
mega-caps keep the regime-keyed defaults (0.10-0.20).

Tests instantiate the helpers directly. Dispatch wiring + max()
preservation verified at source level (matching H4a/b/c precedent
since options_scanner.py has the same heavy dependency tree as
workflow_orchestrator).

DELIBERATE PIN CHANGES (test-deletion discipline): the prior
`test_dispatch_gated_on_micro_tier` pinned the tier-only dispatch string —
that pin is REPLACED (not deleted) by `test_dispatch_gated_on_micro_or_price_class`,
which pins the corrected key. No retained surface lost coverage.
"""

import ast
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from packages.quantum.options_scanner import (
    _get_micro_tier_spread_threshold,
    _get_price_class_spread_cutoff,
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

    def test_dispatch_gated_on_micro_or_price_class(self):
        # Replaces test_dispatch_gated_on_micro_tier: the dispatch key is
        # now micro tier OR price class. Pinning the OR shape prevents a
        # regression back to the tier-only key that silently tightened the
        # gate 3x at the 2026-05-20 capital cliff (audit Area 6).
        self.assertIn(
            'if account_tier == "micro" or (', self.src,
            "Threshold dispatch must be keyed micro-tier OR price-class.",
        )
        self.assertIn(
            "float(current_price) < _get_price_class_spread_cutoff()",
            self.src,
            "Price-class arm must compare current_price to the cutoff "
            "helper (None-guarded).",
        )
        self.assertIn(
            "current_price is not None", self.src,
            "Price-class arm must be None-guarded — a missing quote must "
            "not crash or accidentally loosen the gate.",
        )

    def test_dispatch_uses_max_not_replace(self):
        self.assertIn(
            "max(threshold, _get_micro_tier_spread_threshold())", self.src,
            "Dispatch must use max(regime_default, class_override) "
            "to preserve regime loosening — when SUPPRESSED gives 0.20 "
            "and the class override is 0.30, the override stays at 0.30; if "
            "a future config sets it lower, the regime default still wins.",
        )

    def test_helper_called_in_dispatch_branch(self):
        # The helper invocation must live inside the dispatch block (within
        # ~400 chars of the dispatch line, which now spans the OR condition)
        # — not be referenced from some unrelated path.
        anchor = self.src.find('if account_tier == "micro" or (')
        self.assertGreater(
            anchor, 0, "Could not locate spread-threshold dispatch.",
        )
        block = self.src[anchor:anchor + 400]
        self.assertIn(
            "_get_micro_tier_spread_threshold()", block,
            "Helper invocation must live inside the dispatch block.",
        )

    def test_cutoff_helper_defined_and_reads_env(self):
        self.assertIn(
            "def _get_price_class_spread_cutoff(", self.src,
            "Cutoff helper must be defined in options_scanner.py.",
        )
        self.assertIn(
            'os.getenv("PRICE_CLASS_SPREAD_CUTOFF"', self.src,
            "Cutoff helper must read PRICE_CLASS_SPREAD_CUTOFF env var.",
        )


class TestPriceClassCutoffEnv(unittest.TestCase):
    """PRICE_CLASS_SPREAD_CUTOFF env override behavior (mirrors
    TestEnvOverride for the threshold value helper)."""

    def test_default_when_env_unset(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PRICE_CLASS_SPREAD_CUTOFF", None)
            self.assertEqual(_get_price_class_spread_cutoff(), 60.0)

    def test_env_override(self):
        with patch.dict(os.environ, {"PRICE_CLASS_SPREAD_CUTOFF": "45"}):
            self.assertEqual(_get_price_class_spread_cutoff(), 45.0)

    def test_invalid_env_falls_back_to_default(self):
        with patch.dict(os.environ, {"PRICE_CLASS_SPREAD_CUTOFF": "cheap"}):
            self.assertEqual(_get_price_class_spread_cutoff(), 60.0)

    def test_zero_cutoff_disables_price_class_arm(self):
        # Operator escape hatch: cutoff=0 means no underlying is "cheap",
        # restoring tier-only behavior without a code change.
        with patch.dict(os.environ, {"PRICE_CLASS_SPREAD_CUTOFF": "0"}):
            self.assertEqual(_get_price_class_spread_cutoff(), 0.0)


class TestEffectiveThresholdComposition(unittest.TestCase):
    """Behavioral pin of the dispatch arithmetic (pure recomputation of the
    source expression — keeps the no-heavy-import convention)."""

    @staticmethod
    def _effective(regime_threshold, account_tier, current_price,
                   micro_thr=0.30, cutoff=60.0):
        threshold = regime_threshold
        if account_tier == "micro" or (
            current_price is not None and float(current_price) < cutoff
        ):
            threshold = max(threshold, micro_thr)
        return threshold

    def test_small_tier_cheap_underlying_gets_030(self):
        self.assertEqual(self._effective(0.10, "small", 25.0), 0.30)

    def test_small_tier_megacap_keeps_regime(self):
        self.assertEqual(self._effective(0.10, "small", 400.0), 0.10)

    def test_micro_tier_unchanged_any_price(self):
        self.assertEqual(self._effective(0.10, "micro", 400.0), 0.30)

    def test_none_price_keeps_regime_for_non_micro(self):
        self.assertEqual(self._effective(0.10, "small", None), 0.10)

    def test_suppressed_regime_wins_when_wider(self):
        # SUPPRESSED gives 0.20; class override 0.30 → 0.30 (max), and a
        # hypothetical 0.15 override would lose to 0.20.
        self.assertEqual(self._effective(0.20, "small", 25.0), 0.30)
        self.assertEqual(
            self._effective(0.20, "small", 25.0, micro_thr=0.15), 0.20,
        )

    def test_boundary_at_cutoff_is_exclusive(self):
        self.assertEqual(self._effective(0.10, "small", 60.0), 0.10)
        self.assertEqual(self._effective(0.10, "small", 59.99), 0.30)


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
