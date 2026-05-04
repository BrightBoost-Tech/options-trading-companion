"""Tests for #105 + #106 — rejection-name discipline in options_scanner.

#105: strategy_hold was recorded at two distinct sites for distinct
conditions. Split into:
  - strategy_hold_no_candidates (selector returned empty list, line ~2408)
  - strategy_hold_explicit_verdict (HOLD/CASH verdict, line ~2447)

#106: spread_too_wide formula `combo_spread / entry_cost` produces
deceptively-large percentages when entry_cost is tiny (today's PFE:
combo=$0.12 / entry=$0.06 = 200%, but neither value indicates a real
liquidity issue). Split into:
  - spread_too_wide_real (combo > $0.20 — actual wide spread)
  - entry_cost_too_low (entry < $0.15 — uneconomic trade)
  - spread_too_wide (boundary — both absolute checks pass)

Both are observability improvements only; no scanner behavior changes.
Same trades accepted/rejected as before; rejection_counts now disambiguates.
"""

import re
import unittest
from pathlib import Path


SCANNER_PATH = (
    Path(__file__).parent.parent / "options_scanner.py"
)


def _read_scanner() -> str:
    return SCANNER_PATH.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────
# Layer 1 — Source-level structural assertions
# ─────────────────────────────────────────────────────────────────────


class TestStrategyHoldSplit(unittest.TestCase):
    """#105 — strategy_hold split into two reason codes."""

    @classmethod
    def setUpClass(cls):
        cls.src = _read_scanner()

    def test_no_candidates_reason_present(self):
        self.assertIn(
            'rej_stats.record("strategy_hold_no_candidates")', self.src,
            "Site 1 (selector returned []) must record "
            "strategy_hold_no_candidates",
        )

    def test_explicit_verdict_reason_present(self):
        self.assertIn(
            'rej_stats.record("strategy_hold_explicit_verdict")', self.src,
            "Site 2 (HOLD/CASH verdict) must record "
            "strategy_hold_explicit_verdict",
        )

    def test_bare_strategy_hold_record_removed(self):
        """No `rej_stats.record("strategy_hold")` (the legacy bare name)
        remains anywhere. Substring matches via the two new names are OK."""
        bare_calls = re.findall(
            r'rej_stats\.record\("strategy_hold"\)', self.src
        )
        self.assertEqual(
            bare_calls, [],
            "Legacy bare strategy_hold record must be removed; "
            f"found {len(bare_calls)} occurrences",
        )


class TestSpreadRejectionSplit(unittest.TestCase):
    """#106 — spread_too_wide split into three reason codes."""

    @classmethod
    def setUpClass(cls):
        cls.src = _read_scanner()

    def test_real_wide_reason_present(self):
        self.assertIn('"spread_too_wide_real"', self.src)

    def test_entry_cost_too_low_reason_present(self):
        self.assertIn('"entry_cost_too_low"', self.src)

    def test_boundary_spread_too_wide_retained(self):
        """The legacy 'spread_too_wide' name still appears for the
        boundary case (neither absolute threshold triggers)."""
        # Should appear at least in the reject_reason fallback branch
        # of the new classification block.
        self.assertIn('"spread_too_wide"', self.src)

    def test_module_constants_defined(self):
        """Tunable thresholds must be module constants (env-overridable),
        not magic numbers in the rejection logic."""
        self.assertIn("ABSOLUTE_SPREAD_THRESHOLD", self.src)
        self.assertIn("MIN_ECONOMIC_ENTRY", self.src)

    def test_thresholds_have_default_values(self):
        """Defaults: $0.20 absolute spread / $0.15 min entry. Tunable
        post-deploy via env vars."""
        # Match the literal default coercions in the constant declarations
        self.assertRegex(
            self.src,
            r'ABSOLUTE_SPREAD_THRESHOLD\s*=\s*float\(\s*\n?\s*os\.getenv\("ABSOLUTE_SPREAD_THRESHOLD",\s*"0\.20"\)',
        )
        self.assertRegex(
            self.src,
            r'MIN_ECONOMIC_ENTRY\s*=\s*float\(\s*\n?\s*os\.getenv\("MIN_ECONOMIC_ENTRY",\s*"0\.15"\)',
        )


# ─────────────────────────────────────────────────────────────────────
# Layer 2 — Behavioral classification logic
# ─────────────────────────────────────────────────────────────────────


def _classify_spread_rejection(
    combo_width_share: float,
    entry_cost_share: float,
    absolute_spread_threshold: float = 0.20,
    min_economic_entry: float = 0.15,
) -> str:
    """Mirror of the production classification logic at
    options_scanner.py:~2871. Pure function for test coverage —
    keeps tests fast and isolated from the scanner's heavy imports."""
    if combo_width_share > absolute_spread_threshold:
        return "spread_too_wide_real"
    elif entry_cost_share < min_economic_entry:
        return "entry_cost_too_low"
    else:
        return "spread_too_wide"


class TestSpreadClassificationBehavior(unittest.TestCase):
    """Behavioral tests for the #106 classification rules."""

    def test_real_wide_spread_classified_as_real(self):
        # combo=$0.30, entry=$0.40 → ratio fails AND combo > $0.20
        result = _classify_spread_rejection(
            combo_width_share=0.30,
            entry_cost_share=0.40,
        )
        self.assertEqual(result, "spread_too_wide_real")

    def test_tiny_entry_classified_as_entry_cost_too_low(self):
        # PFE-shape from 2026-05-04: combo=$0.12, entry=$0.06
        # combo NOT > $0.20 (so not real wide), entry < $0.15 (tiny)
        result = _classify_spread_rejection(
            combo_width_share=0.12,
            entry_cost_share=0.06,
        )
        self.assertEqual(result, "entry_cost_too_low")

    def test_boundary_classified_as_legacy_spread_too_wide(self):
        # combo=$0.18, entry=$0.16 → both absolute checks pass
        # (combo NOT > $0.20, entry NOT < $0.15)
        result = _classify_spread_rejection(
            combo_width_share=0.18,
            entry_cost_share=0.16,
        )
        self.assertEqual(result, "spread_too_wide")

    def test_pfe_today_regression(self):
        """Today's exact PFE rejection should classify as entry_cost_too_low."""
        result = _classify_spread_rejection(
            combo_width_share=0.12,
            entry_cost_share=0.06,
        )
        self.assertEqual(result, "entry_cost_too_low")

    def test_cmcsa_today_regression(self):
        """Today's exact CMCSA rejection (per rejection_samples).
        combo_width_share=0.6, entry_cost_share=0.3 → ratio=2.0 (fails),
        combo $0.60 > $0.20 (real wide). Classification: spread_too_wide_real."""
        result = _classify_spread_rejection(
            combo_width_share=0.6,
            entry_cost_share=0.3,
        )
        self.assertEqual(result, "spread_too_wide_real")

    def test_real_wide_takes_precedence_over_tiny_entry(self):
        """If BOTH conditions trigger (combo > $0.20 AND entry < $0.15),
        the spread_too_wide_real classification wins. Real wide is the
        more diagnostically useful signal."""
        # combo=$0.40, entry=$0.05 → both extreme
        result = _classify_spread_rejection(
            combo_width_share=0.40,
            entry_cost_share=0.05,
        )
        self.assertEqual(result, "spread_too_wide_real")


if __name__ == "__main__":
    unittest.main()
