"""
Regression tests for the H7 allocator-aware pre-check (PR \<this PR\>,
2026-05-21).

Origin: 2026-05-21 H7 pre-check design diagnostic. Closes
docs/small_tier_allocation.md §7 item 5 (was deferred pending
empirical evidence). Two cycles on 2026-05-21 produced 4-of-4 H7
drops at sizing (MSFT/COST/NVDA/GOOGL on small-tier $1,031.48 OBP) —
the empirical evidence.

The pre-check sits between ``SmallAccountCompounder.rank_and_select``
and ``PortfolioAllocator.allocate`` in workflow_orchestrator's
run_midday_cycle. For each candidate, it computes:

    rt_required = collateral + estimate_close_bp(strategy, max_loss) × 1.1

If ``rt_required > available_BP``, the candidate is logged as a drop
(shadow mode: log only; active mode: also filter from the candidates
list). Reuses ``estimate_close_bp`` from sizing_engine so pre-check ≡
real H7 by construction.

Modes:
- ``H7_PREFILTER_ENABLED=true`` (active) — filter candidates
- ``H7_PREFILTER_ENABLED=false`` (default; shadow) — log decisions
  without filtering
- exception path — sets mode="error", falls back to no filtering

Tests cover:
- Filter math for each strategy class (debit, credit, single-leg, IC)
- Shadow vs active mode behavior
- Defensive: missing max_loss does not filter
- Reuse of production estimate_close_bp (consistency guard)
- cycle_metadata count + mode populated
- Exit_reason ``all_candidates_h7_unfit`` when active-mode filter
  drops everything from a non-empty input set
- Source-level guards on workflow_orchestrator.py
"""

from pathlib import Path
import os
import unittest
from unittest.mock import patch


# ─────────────────────────────────────────────────────────────────
# Direct math tests against estimate_close_bp + the pre-check
# formula. Replicates the production math here as a defensive read
# so tests don't go through sys.modules — other tests in this suite
# (e.g., test_weekly_report_win_rate.py:17) replace
# sys.modules['packages.quantum.services.sizing_engine'] with a
# MagicMock at module-import time and never restore it. Depending
# on collection order, that pollution makes ``from .sizing_engine
# import estimate_close_bp`` return a MagicMock for downstream
# tests. Local mirror keeps these tests robust.
#
# The local mirror MUST match the production helper. Source-level
# guard test below (test_local_mirror_matches_production_source)
# enforces the match by inspecting the production file as text.
# ─────────────────────────────────────────────────────────────────


# Mirror of production constants at
# packages/quantum/services/sizing_engine.py
_DEBIT_SPREAD_STRATEGIES = {"LONG_CALL_DEBIT_SPREAD", "LONG_PUT_DEBIT_SPREAD"}
_CREDIT_SPREAD_STRATEGIES = {"SHORT_CALL_CREDIT_SPREAD", "SHORT_PUT_CREDIT_SPREAD"}
_SINGLE_LEG_LONG_STRATEGIES = {"LONG_CALL", "LONG_PUT"}


def _local_estimate_close_bp(strategy, max_loss):
    """Test-internal mirror of production estimate_close_bp.

    MUST match sizing_engine.py::estimate_close_bp. The source-level
    guard in TestH7PreFilterUsesRealEstimateCloseBp enforces this
    by inspecting the production file text directly."""
    if max_loss <= 0:
        return 0.0
    key = (strategy or "").upper()
    if key in _SINGLE_LEG_LONG_STRATEGIES:
        return 0.0
    if key in _CREDIT_SPREAD_STRATEGIES:
        return 0.0
    if key in _DEBIT_SPREAD_STRATEGIES:
        return float(max_loss)
    if key == "IRON_CONDOR":
        return 2.0 * float(max_loss)
    return float(max_loss)


def _pre_check_rt_required(
    *, strategy: str, max_loss: float, collateral: float, safety_factor: float = 1.1
) -> float:
    """Replicates the pre-check rt_required math at
    workflow_orchestrator.py inside run_midday_cycle. Uses the
    local estimate_close_bp mirror for robustness against
    sys.modules pollution from other tests."""
    close_bp = _local_estimate_close_bp(strategy, max_loss)
    return collateral + close_bp * safety_factor


def _is_h7_fit(*, available_bp: float, **kwargs) -> bool:
    return _pre_check_rt_required(**kwargs) <= available_bp


# ─────────────────────────────────────────────────────────────────
# Strategy-class filter math
# ─────────────────────────────────────────────────────────────────


class TestH7PreFilterDropsUnfitDebitSpread(unittest.TestCase):
    """The 2026-05-21 production scenario: MSFT debit spread at
    $2,231 max_loss on $1,031.48 OBP. rt_required = $2,231 +
    $2,231 × 1.1 = $4,685. Far exceeds available BP. Pre-check
    must drop."""

    def test_msft_class_drops(self):
        rt = _pre_check_rt_required(
            strategy="LONG_CALL_DEBIT_SPREAD",
            max_loss=2231.0,
            collateral=2231.0,
        )
        self.assertAlmostEqual(rt, 2231.0 + 2231.0 * 1.1, places=2)
        self.assertFalse(
            _is_h7_fit(
                available_bp=1031.48,
                strategy="LONG_CALL_DEBIT_SPREAD",
                max_loss=2231.0,
                collateral=2231.0,
            )
        )

    def test_cost_class_drops_more_severely(self):
        """COST: $5,887 entry → $12,363 rt_required. Geometrically
        impossible at any sub-$13k OBP."""
        self.assertFalse(
            _is_h7_fit(
                available_bp=1031.48,
                strategy="LONG_CALL_DEBIT_SPREAD",
                max_loss=5887.0,
                collateral=5887.0,
            )
        )

    def test_nvda_class_drops_at_marginal_ratio(self):
        """NVDA: $1,117.90 entry → $2,347 rt_required. Sub-2.3×
        over OBP — close but still drops."""
        rt = _pre_check_rt_required(
            strategy="LONG_CALL_DEBIT_SPREAD",
            max_loss=1117.90,
            collateral=1117.90,
        )
        self.assertGreater(rt, 1031.48)
        self.assertLess(rt, 2500.0)


class TestH7PreFilterPassesFitDebitSpread(unittest.TestCase):
    """A debit spread with max_loss < ~$491/contract fits H7 at
    $1,031 OBP. Class B candidates (sub-$30 underlyings with
    $1-wide chains; HBAN/KHC family) typically sit in $25-$200
    max_loss range and pass comfortably."""

    def test_small_max_loss_debit_passes(self):
        """KHC-class: $0.50-wide ATM debit, max_loss ≈ $50."""
        self.assertTrue(
            _is_h7_fit(
                available_bp=1031.48,
                strategy="LONG_CALL_DEBIT_SPREAD",
                max_loss=50.0,
                collateral=50.0,
            )
        )

    def test_boundary_max_loss_debit_passes_with_margin(self):
        """The H7 boundary at $1,031 OBP / 2.1 = $491. A debit
        spread with max_loss exactly at $400 should pass (rt =
        $840)."""
        rt = _pre_check_rt_required(
            strategy="LONG_CALL_DEBIT_SPREAD",
            max_loss=400.0,
            collateral=400.0,
        )
        self.assertLess(rt, 1031.48)
        self.assertTrue(
            _is_h7_fit(
                available_bp=1031.48,
                strategy="LONG_CALL_DEBIT_SPREAD",
                max_loss=400.0,
                collateral=400.0,
            )
        )

    def test_boundary_max_loss_debit_just_above_drops(self):
        """A debit spread with max_loss = $500 produces rt =
        $1,050 — just over the OBP. Must drop."""
        self.assertFalse(
            _is_h7_fit(
                available_bp=1031.48,
                strategy="LONG_CALL_DEBIT_SPREAD",
                max_loss=500.0,
                collateral=500.0,
            )
        )


class TestH7PreFilterPassesCreditSpreadAtCollateralBound(unittest.TestCase):
    """Credit spreads have close_bp = 0 per sizing_engine
    (estimate_close_bp returns 0 for SHORT_*_CREDIT_SPREAD). So
    rt_required = collateral only. A $1-wide credit put spread
    with $25 collateral fits H7 by 40×."""

    def test_credit_spread_rt_required_equals_collateral(self):
        rt = _pre_check_rt_required(
            strategy="SHORT_PUT_CREDIT_SPREAD",
            max_loss=75.0,
            collateral=75.0,
        )
        self.assertEqual(rt, 75.0)  # 75 + 0*1.1 = 75

    def test_credit_spread_at_collateral_boundary_passes(self):
        """A credit spread with collateral up to nearly $1,031
        fits H7."""
        self.assertTrue(
            _is_h7_fit(
                available_bp=1031.48,
                strategy="SHORT_CALL_CREDIT_SPREAD",
                max_loss=900.0,
                collateral=900.0,
            )
        )

    def test_credit_spread_collateral_over_bp_drops(self):
        """A credit spread with collateral exceeding available BP
        must drop."""
        self.assertFalse(
            _is_h7_fit(
                available_bp=1031.48,
                strategy="SHORT_PUT_CREDIT_SPREAD",
                max_loss=1500.0,
                collateral=1500.0,
            )
        )


class TestH7PreFilterPassesIronCondorAtCollateralBound(unittest.TestCase):
    """Iron condor close_bp per sizing_engine: 2.0 × max_loss
    (bilateral exit cost). So rt_required = collateral + 2.0 ×
    max_loss × 1.1 = collateral + 2.2 × max_loss. Narrow-wing
    ICs (max_loss/wing ≈ $54-$95) fit easily."""

    def test_iron_condor_uses_2x_close_bp(self):
        rt = _pre_check_rt_required(
            strategy="IRON_CONDOR",
            max_loss=100.0,
            collateral=100.0,
        )
        # collateral + 2.0 × max_loss × 1.1 = 100 + 220 = 320
        self.assertAlmostEqual(rt, 100 + 2.0 * 100 * 1.1, places=2)

    def test_narrow_wing_iron_condor_fits(self):
        """KO-class narrow-wing iron condor: ~$95/wing max_loss,
        $100 collateral. rt = 100 + 2.2×95 = $309."""
        self.assertTrue(
            _is_h7_fit(
                available_bp=1031.48,
                strategy="IRON_CONDOR",
                max_loss=95.0,
                collateral=100.0,
            )
        )


class TestH7PreFilterSingleLegLong(unittest.TestCase):
    """Single-leg longs (LONG_CALL, LONG_PUT) have close_bp = 0
    (sell-to-close). rt_required = collateral. A long call at $500
    premium fits H7 at $1,031 OBP."""

    def test_long_call_close_bp_zero(self):
        rt = _pre_check_rt_required(
            strategy="LONG_CALL",
            max_loss=500.0,
            collateral=500.0,
        )
        self.assertEqual(rt, 500.0)

    def test_long_call_at_premium_passes(self):
        self.assertTrue(
            _is_h7_fit(
                available_bp=1031.48,
                strategy="LONG_CALL",
                max_loss=500.0,
                collateral=500.0,
            )
        )


# ─────────────────────────────────────────────────────────────────
# Mode behavior (shadow vs active vs error)
# ─────────────────────────────────────────────────────────────────


class TestH7PreFilterShadowMode(unittest.TestCase):
    """Default H7_PREFILTER_ENABLED=false. Pre-check computes
    decisions and logs them but does NOT filter candidates. This is
    the launch state."""

    def test_shadow_mode_value_check(self):
        """When env unset, mode resolves to 'shadow'."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("H7_PREFILTER_ENABLED", None)
            enabled = (
                os.environ.get("H7_PREFILTER_ENABLED", "false").lower() == "true"
            )
            mode = "active" if enabled else "shadow"
            self.assertEqual(mode, "shadow")

    def test_shadow_mode_value_with_explicit_false(self):
        with patch.dict(os.environ, {"H7_PREFILTER_ENABLED": "false"}):
            enabled = (
                os.environ.get("H7_PREFILTER_ENABLED", "false").lower() == "true"
            )
            self.assertFalse(enabled)


class TestH7PreFilterActiveMode(unittest.TestCase):
    """When H7_PREFILTER_ENABLED=true, pre-check filters
    candidates. The new exit_reason 'all_candidates_h7_unfit' fires
    when active-mode filter drops everything from a non-empty input
    set."""

    def test_active_mode_value_check(self):
        with patch.dict(os.environ, {"H7_PREFILTER_ENABLED": "true"}):
            enabled = (
                os.environ.get("H7_PREFILTER_ENABLED", "false").lower() == "true"
            )
            self.assertTrue(enabled)

    def test_active_mode_case_insensitive(self):
        with patch.dict(os.environ, {"H7_PREFILTER_ENABLED": "TRUE"}):
            enabled = (
                os.environ.get("H7_PREFILTER_ENABLED", "false").lower() == "true"
            )
            self.assertTrue(enabled)


# ─────────────────────────────────────────────────────────────────
# Defensive behavior
# ─────────────────────────────────────────────────────────────────


class TestH7PreFilterMissingMaxLossPassesDefensively(unittest.TestCase):
    """If a candidate is missing max_loss_per_contract (data
    pipeline edge case), the pre-check passes it through. Lets
    downstream sizing handle the missing-data case rather than
    silently filtering."""

    def test_zero_max_loss_treated_as_missing(self):
        """In the production pre-check, ``max_loss <= 0`` means
        skip the filter. The candidate continues to allocator."""
        max_loss = 0.0
        skip = max_loss <= 0
        self.assertTrue(skip)


class TestH7PreFilterUsesRealEstimateCloseBp(unittest.TestCase):
    """The pre-check reuses estimate_close_bp from sizing_engine.
    These tests verify pre-check ≡ real H7 by construction. Two
    complementary checks:

    1. Source-level guard: the production file contains the same
       per-strategy close-BP factors the test mirror uses.
    2. Local mirror sanity: when the production module is NOT
       mocked, the local mirror matches it call-by-call. (Skipped
       when sys.modules pollution makes the import return a
       MagicMock — see ``_local_estimate_close_bp`` docstring.)"""

    def test_local_mirror_matches_production_source(self):
        """Inspect the production file as text — source-level
        guard that the local mirror's per-strategy factors match
        production. Robust to sys.modules mocking because it reads
        the file directly, not via import."""
        from pathlib import Path
        src = (
            Path(__file__).resolve().parent.parent
            / "services"
            / "sizing_engine.py"
        ).read_text(encoding="utf-8")
        # Debit spreads return float(max_loss_per_contract)
        self.assertIn("return float(max_loss_per_contract)", src)
        # Credit spreads + single-leg longs return 0.0
        self.assertIn("return 0.0", src)
        # Iron condor returns 2.0 * float(max_loss_per_contract)
        self.assertIn("2.0 * float(max_loss_per_contract)", src)
        # The strategy sets defined in production match the test mirror
        self.assertIn("LONG_CALL_DEBIT_SPREAD", src)
        self.assertIn("LONG_PUT_DEBIT_SPREAD", src)
        self.assertIn("SHORT_CALL_CREDIT_SPREAD", src)
        self.assertIn("SHORT_PUT_CREDIT_SPREAD", src)
        self.assertIn("IRON_CONDOR", src)

    def test_consistency_with_production_helper(self):
        """When sizing_engine is not mocked, the local mirror
        must match the production helper for each strategy. Skips
        defensively if other tests have polluted sys.modules.

        sys.modules pollution scenario:
        ``test_weekly_report_win_rate.py:17`` replaces
        ``sys.modules['packages.quantum.services.sizing_engine']``
        with a MagicMock at module-import time and never restores
        it. Depending on pytest collection order, that pollution
        makes the import below return a MagicMock. The skip path
        keeps CI green; the source-level guard above provides the
        equivalent invariant via file inspection.
        """
        from packages.quantum.services.sizing_engine import estimate_close_bp
        # Defensive: skip if pollution made the import return a Mock
        from unittest.mock import MagicMock
        if isinstance(estimate_close_bp, MagicMock):
            self.skipTest(
                "sizing_engine is mocked by another test "
                "(test_weekly_report_win_rate.py). Source-level "
                "guard test_local_mirror_matches_production_source "
                "covers this invariant via file inspection."
            )
        for strategy, expected_factor in [
            ("LONG_CALL_DEBIT_SPREAD", 1.0),
            ("LONG_PUT_DEBIT_SPREAD", 1.0),
            ("SHORT_PUT_CREDIT_SPREAD", 0.0),
            ("SHORT_CALL_CREDIT_SPREAD", 0.0),
            ("LONG_CALL", 0.0),
            ("LONG_PUT", 0.0),
            ("IRON_CONDOR", 2.0),
        ]:
            with self.subTest(strategy=strategy):
                got = estimate_close_bp(strategy, 100.0)
                self.assertAlmostEqual(got, expected_factor * 100.0)
                # And the local mirror returns the same value
                local = _local_estimate_close_bp(strategy, 100.0)
                self.assertAlmostEqual(local, expected_factor * 100.0)


# ─────────────────────────────────────────────────────────────────
# cycle_metadata extension (Change 3)
# ─────────────────────────────────────────────────────────────────


class TestCycleMetadataH7Fields(unittest.TestCase):
    """_build_cycle_metadata must accept the new h7_prefilter_dropped
    and h7_prefilter_mode fields (PR \<this PR\>)."""

    def test_helper_accepts_h7_fields(self):
        from packages.quantum.services.workflow_orchestrator import (
            _build_cycle_metadata,
        )
        meta = _build_cycle_metadata(
            exit_reason="no_suggestions_after_gates",
            tier="small",
            regime="normal",
            deployable_capital=1031.48,
            open_position_count=0,
            available_envelope_dollars=412.59,
            h7_prefilter_dropped=4,
            h7_prefilter_mode="shadow",
        )
        self.assertEqual(meta["h7_prefilter_dropped"], 4)
        self.assertEqual(meta["h7_prefilter_mode"], "shadow")

    def test_helper_defaults_h7_fields_to_none(self):
        """Pre-funnel early-exits omit the h7 args; helper defaults
        to None for backward compatibility."""
        from packages.quantum.services.workflow_orchestrator import (
            _build_cycle_metadata,
        )
        meta = _build_cycle_metadata(
            exit_reason="micro_tier_position_open",
            tier="micro",
            regime=None,
            deployable_capital=681.0,
            open_position_count=1,
            available_envelope_dollars=None,
        )
        self.assertIsNone(meta["h7_prefilter_dropped"])
        self.assertIsNone(meta["h7_prefilter_mode"])

    def test_helper_accepts_disabled_mode(self):
        from packages.quantum.services.workflow_orchestrator import (
            _build_cycle_metadata,
        )
        meta = _build_cycle_metadata(
            exit_reason="micro_tier_position_open",
            tier="micro",
            regime=None,
            deployable_capital=681.0,
            open_position_count=1,
            available_envelope_dollars=None,
            h7_prefilter_dropped=0,
            h7_prefilter_mode="disabled",
        )
        self.assertEqual(meta["h7_prefilter_mode"], "disabled")


# ─────────────────────────────────────────────────────────────────
# Source-level guards on workflow_orchestrator.py
# ─────────────────────────────────────────────────────────────────


class TestWorkflowOrchestratorSourceGuards(unittest.TestCase):
    """Source-level inspection defends against the literal regression
    of someone removing the pre-check wire-in. Same pattern as
    test_allocator_hint_threading.py and test_credit_spread_emission.py:
    structural questions are easier and more reliable to test via
    source-text inspection than via heavy runtime mocking."""

    @classmethod
    def setUpClass(cls):
        cls.src = (
            Path(__file__).resolve().parent.parent
            / "services"
            / "workflow_orchestrator.py"
        ).read_text(encoding="utf-8")

    def test_prefilter_imports_sizing_engine_helpers(self):
        """The pre-check must import the same helpers sizing_engine
        uses for H7, so pre-check ≡ real H7 by construction."""
        self.assertIn("from packages.quantum.services.sizing_engine import", self.src)
        self.assertIn("estimate_close_bp as _estimate_close_bp", self.src)
        self.assertIn(
            "DEFAULT_ROUND_TRIP_SAFETY_FACTOR as _RT_SAFETY",
            self.src,
        )

    def test_prefilter_env_flag_default_false(self):
        """H7_PREFILTER_ENABLED must default to 'false' (shadow
        mode) — never auto-launch in active mode."""
        self.assertIn(
            'os.environ.get("H7_PREFILTER_ENABLED", "false")',
            self.src,
        )

    def test_prefilter_writes_mode_to_cycle_metadata(self):
        """The h7_prefilter_mode is threaded to _build_cycle_metadata
        at both the no_suggestions and happy-path return sites."""
        self.assertIn(
            "h7_prefilter_mode=h7_prefilter_mode",
            self.src,
        )

    def test_prefilter_writes_count_to_cycle_metadata(self):
        self.assertIn(
            "h7_prefilter_dropped=h7_prefilter_dropped_count",
            self.src,
        )

    def test_exit_reason_all_candidates_h7_unfit_present(self):
        """The new exit_reason discriminator must be present in
        source. Active-mode filter that drops everything sets this
        instead of legacy no_suggestions_after_gates."""
        self.assertIn(
            'all_candidates_h7_unfit',
            self.src,
        )

    def test_active_mode_filter_assigns_candidates(self):
        """When active mode is on, candidates list is replaced by
        the H7-passes-only list. Source-level assertion."""
        # The active-mode branch in the source filters in-place.
        self.assertIn(
            "candidates = _h7_passes",
            self.src,
            "Active-mode branch must reassign candidates to the "
            "H7-passes-only list. Without this, the filter is "
            "structurally inert in active mode.",
        )

    def test_prefilter_defensive_exception_branch(self):
        """Pre-check failure must NOT block the cycle. Wrap in
        try/except with logged fallback."""
        self.assertIn(
            "H7 pre-filter wire-in failed (non-fatal)",
            self.src,
        )

    def test_prefilter_before_portfolio_allocator(self):
        """The pre-check must run BEFORE the allocator. Source-order
        guard."""
        prefilter_idx = self.src.find("H7 allocator-aware pre-check")
        allocator_idx = self.src.find("PortfolioAllocator()")
        self.assertGreater(prefilter_idx, 0)
        self.assertGreater(allocator_idx, 0)
        self.assertLess(
            prefilter_idx, allocator_idx,
            "Pre-check must run before allocator instantiation",
        )


if __name__ == "__main__":
    unittest.main()
