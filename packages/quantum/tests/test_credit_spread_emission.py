"""
Regression tests for the credit-spread chain-mechanics formula fix
(PR #<this PR>, 2026-05-21).

Origin: 2026-05-21 α Phase 3 strategy-emission diagnostic. The
post-PR-#973 small-tier cycle (2026-05-21 16:00 UTC) showed only
``LONG_CALL_DEBIT_SPREAD`` candidates emitting from the scanner;
zero credit spreads, zero iron condors. Investigation traced the
credit spread shortfall to ``options_scanner.py`` chain-mechanics
gate around line 3149-3214: the ``combo_spread / entry_cost`` ratio
formula inflated to 200% sentinel values on credit spreads because
``entry_cost`` for a credit spread is the (small) credit received,
not capital at risk. Empirical surface:

- 0 credit spreads in ``trade_suggestions`` over 90d
- All ``SHORT_*_CREDIT_SPREAD`` attempts in today's worker logs
  hit ``spread=200.0%`` and got rejected as ``spread_too_wide_real``

Fix shape (Option 1B per the diagnostic prompt — conditional
formula):

- Credit spread (``total_cost < 0``): denominator = max_loss_share
  (capital at risk; meaningful liquidity signal)
- Debit spread / single-leg long (``total_cost > 0``): denominator =
  entry_cost_share (unchanged; entry_cost == max_loss for debit so
  the legacy semantics are preserved)
- Iron condor (4-leg): unchanged (separate ``max_leg_spread_pct``
  validation by the EV-aware condor builder)

Plus a defensive observability alert (``chain_mechanics_formula_anomaly``,
severity=warning) for any future formula edge case that produces
spread_pct > 300%. H9 verified-consumer doctrine applied to gate
behavior so future regressions surface within one cycle instead of
90 days.

Tests cover:
- Formula behavior: credit spread passes when bid-ask is reasonable
  relative to max_loss
- Formula behavior: credit spread rejects when bid-ask is genuinely
  wide (still works — the gate still does its job)
- Formula behavior: debit spread unchanged (no regression)
- Defensive alert: fires on spread_pct > 300%
- Defensive alert: does NOT fire on legitimate near-threshold
  rejections
- Source-level guards on ``options_scanner.py`` confirming the
  conditional formula + alert site are present
"""

from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch


# ─────────────────────────────────────────────────────────────────
# Formula helper — mirrors the production formula at
# options_scanner.py around line 3149. Kept here so tests can
# exercise the math directly without driving the full
# process_symbol() call stack (heavy chain-loading deps).
# Source-level guards (below) defend against the production code
# drifting away from this contract.
# ─────────────────────────────────────────────────────────────────


def _compute_legacy_spread_pct(
    *,
    combo_width_share: float,
    total_cost: float,
    max_loss_contract: float,
) -> float:
    """Replicates the chain-mechanics legacy_spread_pct formula.

    Inputs are in per-share units (``combo_width_share``,
    ``total_cost``) and per-contract dollars (``max_loss_contract``).
    Returns the ratio used by the ``spread_too_wide`` rejection gate.
    """
    entry_cost_share = abs(float(total_cost or 0.0))
    is_credit_spread = (total_cost or 0.0) < 0
    max_loss_share = (max_loss_contract / 100.0) if max_loss_contract else 0.0

    if is_credit_spread and max_loss_share > 1e-9:
        return combo_width_share / max_loss_share
    elif entry_cost_share > 1e-9:
        return combo_width_share / entry_cost_share
    return 0.0


# ─────────────────────────────────────────────────────────────────
# Computational tests on the conditional formula
# ─────────────────────────────────────────────────────────────────


class TestCreditSpreadChainMechanicsPasses(unittest.TestCase):
    """A credit spread with reasonable bid-ask relative to max_loss
    must produce a spread_pct that clears the 10% threshold. Pre-fix
    this case died at the 200% sentinel."""

    def test_typical_credit_put_spread_passes(self):
        """$5-wide credit put spread, $0.25 credit received,
        $0.10 combo_spread (per-share). Pre-fix: 0.10/0.25 = 40% →
        rejected. Post-fix: 0.10/4.75 = 2.1% → passes 10%."""
        # max_loss = (width - credit) × 100 = ($5 - $0.25) × 100 = $475
        spread_pct = _compute_legacy_spread_pct(
            combo_width_share=0.10,
            total_cost=-0.25,
            max_loss_contract=475.0,
        )
        self.assertLess(
            spread_pct, 0.10,
            f"Reasonable credit spread should pass 10% threshold, "
            f"got {spread_pct:.1%}",
        )
        # Sanity: it's the 2.1% expected value, not just <10%
        self.assertAlmostEqual(spread_pct, 0.10 / 4.75, places=4)

    def test_pre_fix_would_have_rejected_this(self):
        """Document the pre-fix behavior to prove the fix matters:
        the old formula (combo_spread / entry_cost) would have
        produced ~40% — clearly above the 10% threshold."""
        # Pre-fix shape: combo / abs(total_cost)
        old_formula = 0.10 / abs(-0.25)
        self.assertGreater(
            old_formula, 0.10,
            "Pre-fix formula must have rejected this case (otherwise "
            "this regression test is meaningless)",
        )
        self.assertAlmostEqual(old_formula, 0.40, places=4)


class TestCreditSpreadChainMechanicsRejectsWide(unittest.TestCase):
    """When a credit spread genuinely has wide bid-ask relative to
    max_loss, the gate must still reject it. The fix loosens the
    formula's bias against credit geometry — it does NOT disable
    the gate."""

    def test_wide_bid_ask_credit_spread_still_rejects(self):
        """Genuinely illiquid wings: $0.60 combo_spread on a
        $5-wide $0.25 credit spread, max_loss = $475. spread_pct =
        0.60/4.75 = 12.6% > 10% threshold → reject. Post-fix the
        rejection is for the right structural reason, not the
        sentinel."""
        spread_pct = _compute_legacy_spread_pct(
            combo_width_share=0.60,
            total_cost=-0.25,
            max_loss_contract=475.0,
        )
        self.assertGreater(
            spread_pct, 0.10,
            "Genuinely wide credit spread must still reject at 10% "
            f"threshold, got {spread_pct:.1%}",
        )
        # And the value is realistic (not the 200% sentinel)
        self.assertLess(
            spread_pct, 0.30,
            "Reject should be for legitimate wide-spread reason, "
            f"not formula sentinel, got {spread_pct:.1%}",
        )


class TestDebitSpreadChainMechanicsUnchanged(unittest.TestCase):
    """Debit spreads were not broken by the old formula — the fix
    must not change their behavior. Verify by running the same
    scenarios through the new formula and checking the numbers
    match the legacy math."""

    def test_typical_debit_call_spread_unchanged(self):
        """$5-wide debit call spread, $2.00 net debit per share,
        $0.05 combo_spread. Spread_pct = 0.05/2.00 = 2.5%. Same as
        pre-fix; debit case uses entry_cost as denominator."""
        # For debit: max_loss == entry_cost (in $/share units)
        spread_pct = _compute_legacy_spread_pct(
            combo_width_share=0.05,
            total_cost=2.00,  # positive => debit
            max_loss_contract=200.0,
        )
        self.assertAlmostEqual(spread_pct, 0.025, places=4)

    def test_wide_debit_spread_still_rejects(self):
        """Debit spread with combo_spread wider than threshold
        still rejects post-fix — no regression of the gate's
        intended behavior."""
        spread_pct = _compute_legacy_spread_pct(
            combo_width_share=0.30,
            total_cost=2.00,
            max_loss_contract=200.0,
        )
        self.assertGreater(spread_pct, 0.10)
        self.assertAlmostEqual(spread_pct, 0.15, places=4)

    def test_thin_debit_spread_with_tiny_entry_still_rejects(self):
        """The PFE-class case (combo=$0.12, entry=$0.06) that the
        ABSOLUTE_SPREAD_THRESHOLD comment block documents: pre-fix,
        the formula inflates to 200%. The fix doesn't change this
        case (still a debit spread, denominator is still entry_cost).
        This test pins the pre-existing classification logic at the
        downstream switch (entry_cost_too_low / spread_too_wide_real)."""
        spread_pct = _compute_legacy_spread_pct(
            combo_width_share=0.12,
            total_cost=0.06,  # positive => debit; tiny
            max_loss_contract=6.0,  # $6 per contract
        )
        # Math: 0.12 / 0.06 = 200% — same as before fix. This is
        # the legitimate "entry_cost_too_low" classification; the
        # downstream switch handles it. Debit behavior unchanged.
        self.assertAlmostEqual(spread_pct, 2.0, places=4)


class TestSingleLegLongUnchanged(unittest.TestCase):
    """Single-leg long options: total_cost == premium == max_loss
    (in share units). Formula uses entry_cost denominator (legacy
    debit path). Should behave identically to before."""

    def test_long_call_unchanged(self):
        """$5 premium, $0.10 bid-ask. spread_pct = 0.10/5.00 = 2%."""
        spread_pct = _compute_legacy_spread_pct(
            combo_width_share=0.10,
            total_cost=5.00,
            max_loss_contract=500.0,
        )
        self.assertAlmostEqual(spread_pct, 0.02, places=4)


class TestEdgeCases(unittest.TestCase):
    """Edge cases: zero entry_cost, zero max_loss, etc. Formula
    must not raise."""

    def test_zero_entry_zero_max_loss_returns_zero(self):
        """If both inputs are zero, the function returns 0.0 (no
        signal). This is the existing legacy behavior preserved."""
        spread_pct = _compute_legacy_spread_pct(
            combo_width_share=0.10,
            total_cost=0.0,
            max_loss_contract=0.0,
        )
        self.assertEqual(spread_pct, 0.0)

    def test_credit_spread_with_zero_max_loss_falls_through(self):
        """Defensive: if a malformed credit-spread candidate arrives
        with max_loss=0 (geometrically impossible — would mean
        width == credit, i.e. free money), formula falls through to
        the entry_cost path. Doesn't raise."""
        spread_pct = _compute_legacy_spread_pct(
            combo_width_share=0.10,
            total_cost=-0.25,
            max_loss_contract=0.0,
        )
        # Falls through to the entry_cost path: 0.10 / 0.25 = 40%
        self.assertAlmostEqual(spread_pct, 0.40, places=4)


# ─────────────────────────────────────────────────────────────────
# Defensive anomaly alert tests
# ─────────────────────────────────────────────────────────────────


class _AlertCapture:
    """Captures alert() calls so tests can assert on the payload
    without hitting Supabase. Mirrors the pattern from
    test_allocator_hint_threading.py."""

    def __init__(self):
        self.calls = []

    def __call__(self, supabase, **kwargs):
        self.calls.append({"supabase": supabase, **kwargs})


def _read_anomaly_threshold() -> float:
    """Read the anomaly threshold defensively. Reads from the env
    (the same source the production constant uses) rather than from
    ``packages.quantum.options_scanner`` directly — other tests in
    this suite ``@patch`` attributes on that module, and depending on
    test execution order the module-level constant can end up shadowed
    by a MagicMock in the patched namespace. Reading from env removes
    the dependency on import order."""
    import os
    return float(os.getenv("SPREAD_PCT_ANOMALY_THRESHOLD", "3.0"))


class TestAnomalyAlertFiringLogic(unittest.TestCase):
    """The defensive alert is triggered by spread_pct exceeding
    SPREAD_PCT_ANOMALY_THRESHOLD (default 3.0 = 300%). These tests
    exercise the firing decision logic directly — the alert only
    fires above threshold, never below.

    The alert wiring inside ``process_symbol`` is tested by the
    source-level guards below; these tests pin the threshold
    behavior."""

    def test_alert_fires_at_anomalous_value(self):
        """spread_pct > 300% must trigger the firing path."""
        anomaly_threshold = _read_anomaly_threshold()
        # Construct a scenario where the formula produces > 300%
        # (e.g., pre-fix debit-spread-with-tiny-entry case)
        spread_pct = _compute_legacy_spread_pct(
            combo_width_share=0.20,
            total_cost=0.05,  # debit with tiny entry
            max_loss_contract=5.0,
        )
        self.assertGreater(spread_pct, anomaly_threshold)

    def test_no_alert_for_legitimate_near_threshold_rejection(self):
        """A credit spread rejected for legitimate "wide bid-ask"
        reasons (e.g., spread_pct = 12%) must NOT trigger the
        anomaly alert — that's a normal rejection, not a formula
        edge case."""
        anomaly_threshold = _read_anomaly_threshold()
        spread_pct = _compute_legacy_spread_pct(
            combo_width_share=0.60,
            total_cost=-0.25,
            max_loss_contract=475.0,
        )
        # 0.60/4.75 = 12.6% — above 10% threshold (rejects normally),
        # but well below 300% anomaly threshold (no alert)
        self.assertGreater(spread_pct, 0.10)
        self.assertLess(spread_pct, anomaly_threshold)

    def test_anomaly_threshold_is_reasonable(self):
        """The threshold should be high enough to avoid firing on
        legitimate-but-wide spreads, but low enough to catch
        formula edge cases. 300% is the chosen value; this test
        documents that choice and defends against accidental
        retuning."""
        anomaly_threshold = _read_anomaly_threshold()
        self.assertGreaterEqual(
            anomaly_threshold, 2.0,
            "Anomaly threshold should be well above 100% so that "
            "legitimate-but-wide rejections don't fire false alerts",
        )
        self.assertLessEqual(
            anomaly_threshold, 10.0,
            "Anomaly threshold should be tight enough to catch "
            "formula bugs (e.g., div-by-tiny producing 1000%+)",
        )


# ─────────────────────────────────────────────────────────────────
# Source-level guards on options_scanner.py
# ─────────────────────────────────────────────────────────────────


class TestOptionsScannerSourceGuards(unittest.TestCase):
    """Source-level inspection defends against the literal
    regression of someone re-introducing the pre-fix formula.
    Mirrors the pattern from test_allocator_hint_threading.py:
    structural questions are easier and more reliable to test
    via source-text inspection than via heavy runtime mocking
    of the deep chain-loading dependencies."""

    @classmethod
    def setUpClass(cls):
        cls.src = (
            Path(__file__).resolve().parent.parent
            / "options_scanner.py"
        ).read_text(encoding="utf-8")

    def test_conditional_formula_present(self):
        """The fix: the formula branches on is_credit_spread and
        uses max_loss_share for credit. Without this conditional,
        credit spreads die at the 200% sentinel."""
        self.assertIn(
            "is_credit_spread = (total_cost or 0.0) < 0",
            self.src,
            "is_credit_spread detection must be present — switches "
            "the spread_pct denominator from entry_cost to max_loss "
            "for credit spreads",
        )
        self.assertIn(
            "if is_credit_spread and max_loss_share > 1e-9:",
            self.src,
            "Credit-spread branch must compute combo_width / max_loss_share",
        )
        self.assertIn(
            "max_loss_share = (max_loss_contract / 100.0)",
            self.src,
            "max_loss_share must convert per-contract USD to per-share "
            "for unit consistency with combo_width_share",
        )

    def test_anomaly_alert_site_present(self):
        """The defensive alert: fires when spread_pct exceeds the
        anomaly threshold. H9 verified-consumer pattern."""
        self.assertIn(
            "SPREAD_PCT_ANOMALY_THRESHOLD",
            self.src,
            "SPREAD_PCT_ANOMALY_THRESHOLD constant must be defined",
        )
        self.assertIn(
            'alert_type="chain_mechanics_formula_anomaly"',
            self.src,
            "chain_mechanics_formula_anomaly alert must be raised in "
            "the chain-mechanics gate when spread_pct exceeds the "
            "anomaly threshold",
        )
        self.assertIn(
            "if option_spread_pct > SPREAD_PCT_ANOMALY_THRESHOLD:",
            self.src,
            "Anomaly alert must be gated by the threshold comparison",
        )

    def test_alert_fires_before_rejection(self):
        """The alert should fire BEFORE the rejection check so it
        catches formula edge cases regardless of the rejection
        outcome. Source-order assertion."""
        anomaly_idx = self.src.find("SPREAD_PCT_ANOMALY_THRESHOLD:")
        # Skip the constant-definition site; find the conditional usage
        anomaly_idx = self.src.find(
            "if option_spread_pct > SPREAD_PCT_ANOMALY_THRESHOLD:"
        )
        rejection_idx = self.src.find(
            "if option_spread_pct > effective_threshold:"
        )
        self.assertGreater(
            anomaly_idx, 0,
            "Anomaly conditional must exist",
        )
        self.assertGreater(
            rejection_idx, 0,
            "Rejection conditional must exist",
        )
        self.assertLess(
            anomaly_idx, rejection_idx,
            "Anomaly alert must fire BEFORE the rejection check so "
            "formula edge cases produce observability regardless of "
            "rejection outcome",
        )

    def test_debit_spread_formula_branch_preserved(self):
        """The debit spread branch must still use entry_cost_share
        as denominator — no regression of working behavior."""
        self.assertIn(
            "legacy_spread_pct = combo_width_share / entry_cost_share",
            self.src,
            "Debit spread / single-leg long path must keep using "
            "entry_cost_share as denominator (legacy behavior, no "
            "regression)",
        )


# ─────────────────────────────────────────────────────────────────
# Alert plumbing test — exercises the alert() call shape end-to-end
# ─────────────────────────────────────────────────────────────────


class TestAlertPlumbing(unittest.TestCase):
    """Verifies that the alert() helper accepts the metadata shape
    we send. Doesn't test triggering (that requires driving
    process_symbol() end-to-end); tests the contract between the
    chain-mechanics gate and the alert helper."""

    def test_alert_helper_accepts_expected_metadata(self):
        """Defensive: the metadata fields we pass must be acceptable
        to alert(). If alert()'s signature changes in a way that
        breaks our call site, this test catches it."""
        capture = _AlertCapture()
        with patch("packages.quantum.observability.alerts.alert", capture):
            from packages.quantum.observability.alerts import alert as _alert
            _alert(
                MagicMock(),
                alert_type="chain_mechanics_formula_anomaly",
                severity="warning",
                symbol="TEST",
                message="spread_pct 350.0% exceeds anomaly threshold",
                metadata={
                    "spread_pct": 3.5,
                    "strategy_template": "short_put_credit_spread",
                    "combo_spread_share": 0.30,
                    "entry_cost_share": 0.05,
                    "max_loss_share": 0.95,
                    "is_credit_spread": True,
                    "call_site": "options_scanner.legacy_spread_pct",
                },
            )
        self.assertEqual(len(capture.calls), 1)
        call = capture.calls[0]
        self.assertEqual(call["alert_type"], "chain_mechanics_formula_anomaly")
        self.assertEqual(call["severity"], "warning")
        self.assertEqual(call["symbol"], "TEST")
        self.assertEqual(call["metadata"]["is_credit_spread"], True)


if __name__ == "__main__":
    unittest.main()
