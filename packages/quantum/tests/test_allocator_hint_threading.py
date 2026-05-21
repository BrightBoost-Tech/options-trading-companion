"""
Regression tests for PR #958's small-tier allocator wiring completion.

Origin: 2026-05-20 small-tier kill-site investigation. PR #958
(small-tier allocation-aware sizing, shipped 2026-05-18) correctly
designed the PortfolioAllocator + the ``allocation_hint`` parameter
signatures on both consumer functions (``calculate_variable_sizing``
and ``RiskBudgetEngine.compute``), but did NOT thread the hint from
``workflow_orchestrator``'s sizing call site. Producer (allocator)
attached ``_allocator_allocated_budget`` to each candidate dict;
no consumer read the field. Sizing fell through to the legacy
multiplier-stack at ~3% × score_mult ≈ $24.76 per-trade budget on
$1,031.48 capital — ~8× smaller than the allocator's intended
~$186-$370 budget. ``contracts_by_risk = floor($24.76 / max_loss) = 0``
for any debit spread with max_loss > $24.76, which is all of them.

The first small-tier cycle on 2026-05-20 produced 4 candidates and 0
created trade_suggestions — the empirical surface of the wiring gap.

This PR completes PR #958's intended wiring with three changes:
1. ``workflow_orchestrator.py:2697-2703`` passes
   ``allocation_hint=cand.get("_allocator_allocated_budget")`` to
   ``calculate_variable_sizing``.
2. ``workflow_orchestrator.py:2705-2710`` conditionally skips the
   ``min(..., budgets.max_risk_per_trade)`` clamp when
   ``sizing_vars["allocation_hint_applied"]`` is True — otherwise
   the cycle-start RBE.max_risk_per_trade (legacy small-tier ~3%)
   throttles the allocator's hint back down.
3. ``calculate_variable_sizing`` fires
   ``allocator_hint_dropped`` (severity=high) when called WITHOUT
   ``allocation_hint`` but the candidate has
   ``_allocator_allocated_budget`` set — H9 verified-consumer
   doctrine applied to the fix itself. Future regression that
   drops the threading fires the alert immediately instead of
   producing another silent-cycle outage.

Tests cover:
- Direct unit tests on ``calculate_variable_sizing``'s
  allocation-hint behavior (correct budget; alert fires on drop).
- Micro tier unaffected (allocator dormant by design).
- Source-level guard on ``workflow_orchestrator.py`` confirming
  the threading is in place and the conditional clamp is present.
"""

from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

# NOTE: deliberately does NOT install an alpaca-py stub via
# sys.modules.setdefault (the pattern used in some other test
# files in this directory). This test file's alphabetical sort
# order places it BEFORE test_alpaca_authoritative_equity.py
# (l < p at position 2 in "al{l,p}..."), so an alpaca-module
# stub installed here would mask the real alpaca.trading.requests
# import in equity_state.py and cause downstream
# test_*_weekly_pnl assertions to fail with NoneType-arithmetic
# errors. None of this file's tests need alpaca imports — the
# tests exercise small_account_compounder (pure-Python) and
# read workflow_orchestrator.py as source text. Repro:
# pytest test_allocator_hint_threading.py
#        test_alpaca_authoritative_equity.py — fails without
# this caveat; passes with it.


class _AlertCapture:
    """Captures alert() calls so tests can assert on the payload
    without hitting Supabase."""

    def __init__(self):
        self.calls = []

    def __call__(self, supabase, **kwargs):
        self.calls.append({"supabase": supabase, **kwargs})


# ─────────────────────────────────────────────────────────────────
# Direct unit tests on calculate_variable_sizing
# ─────────────────────────────────────────────────────────────────


class TestAllocatorHintProducesCorrectBudget(unittest.TestCase):
    """When ``allocation_hint`` is threaded, the small-tier path
    returns the allocator's budget directly. When absent, the
    legacy multiplier-stack produces a ~6-8× smaller value."""

    def _call(self, capital, allocation_hint=None, score=50, candidate_extras=None):
        from packages.quantum.services.analytics.small_account_compounder import (
            SmallAccountCompounder,
        )
        tier = SmallAccountCompounder.get_tier(capital)
        candidate = {"score": score}
        if candidate_extras:
            candidate.update(candidate_extras)
        return SmallAccountCompounder.calculate_variable_sizing(
            candidate=candidate,
            capital=capital,
            tier=tier,
            regime="normal",
            compounding=True,
            allocation_hint=allocation_hint,
        )

    def test_small_tier_with_hint_uses_hint_directly(self):
        """The 2026-05-20 production scenario: $1,031 capital,
        score=50 candidate, allocator emits $186."""
        result = self._call(capital=1031.48, allocation_hint=186.31, score=50)
        self.assertEqual(result["risk_budget"], 186.31)
        self.assertTrue(result.get("allocation_hint_applied"))

    def test_small_tier_without_hint_falls_through_to_legacy(self):
        """Without the hint, the legacy 3% × 0.8 path produces
        $24.76 on $1031.48 — the broken pre-fix behavior."""
        result = self._call(capital=1031.48, allocation_hint=None, score=50)
        # 0.03 × 0.80 × $1,031.48 = $24.7555
        self.assertAlmostEqual(result["risk_budget"], 24.7555, places=3)
        self.assertNotIn("allocation_hint_applied", result)

    def test_legacy_path_budget_is_smaller_than_hint_path(self):
        """The empirical 8× gap that broke production: at small tier,
        the allocator-aware budget is materially larger than the
        legacy fallback."""
        with_hint = self._call(capital=1031.48, allocation_hint=186.31, score=50)
        without_hint = self._call(capital=1031.48, allocation_hint=None, score=50)
        ratio = with_hint["risk_budget"] / without_hint["risk_budget"]
        self.assertGreater(
            ratio, 7.0,
            f"Allocator-aware budget should be 7-8x larger than legacy "
            f"fallback (allocator's per-cycle distribution math), "
            f"got {ratio:.2f}x",
        )


# ─────────────────────────────────────────────────────────────────
# Defensive alert behavior (H9 verified-consumer)
# ─────────────────────────────────────────────────────────────────


class TestAllocatorHintDroppedAlert(unittest.TestCase):
    """The defensive alert fires when the producer wrote the budget
    to the candidate dict but the consumer received None — that's
    the wiring-regression signature."""

    def _call_with_capture(
        self,
        capital,
        candidate,
        allocation_hint=None,
        regime="normal",
    ):
        from packages.quantum.services.analytics.small_account_compounder import (
            SmallAccountCompounder,
        )
        tier = SmallAccountCompounder.get_tier(capital)
        capture = _AlertCapture()
        with patch(
            "packages.quantum.observability.alerts.alert", capture
        ), patch(
            "packages.quantum.observability.alerts._get_admin_supabase",
            return_value=MagicMock(),
        ):
            SmallAccountCompounder.calculate_variable_sizing(
                candidate=candidate,
                capital=capital,
                tier=tier,
                regime=regime,
                compounding=True,
                allocation_hint=allocation_hint,
            )
        return capture

    def test_alert_fires_when_candidate_has_budget_but_hint_is_none(self):
        capture = self._call_with_capture(
            capital=1031.48,
            candidate={
                "score": 50,
                "symbol": "AAPL",
                "_allocator_allocated_budget": 186.31,
            },
            allocation_hint=None,
        )
        self.assertEqual(
            len(capture.calls), 1,
            "Exactly one allocator_hint_dropped alert expected",
        )
        call = capture.calls[0]
        self.assertEqual(call["alert_type"], "allocator_hint_dropped")
        self.assertEqual(call["severity"], "high")
        self.assertEqual(call["symbol"], "AAPL")
        # The metadata should capture the producer's intended budget
        # so the operator can quantify the regression's impact.
        self.assertEqual(call["metadata"]["allocator_budget"], 186.31)
        self.assertEqual(call["metadata"]["tier"], "small")
        self.assertIn("doctrine_ref", call["metadata"])

    def test_alert_does_NOT_fire_when_hint_threaded_correctly(self):
        """Happy path: producer wrote the budget AND consumer received
        it. No regression, no alert."""
        capture = self._call_with_capture(
            capital=1031.48,
            candidate={
                "score": 50,
                "symbol": "AAPL",
                "_allocator_allocated_budget": 186.31,
            },
            allocation_hint=186.31,
        )
        self.assertEqual(
            len(capture.calls), 0,
            "Happy path (hint threaded correctly) must not alert",
        )

    def test_no_allocator_output_no_alert(self):
        """Cycle where the allocator didn't run (e.g., 0 candidates,
        or upstream failure) — no ``_allocator_allocated_budget`` on
        the candidate. Falls through to legacy without firing the
        alert. This is the small-tier-allocator-bypass scenario the
        function's docstring describes."""
        capture = self._call_with_capture(
            capital=1031.48,
            candidate={"score": 50, "symbol": "AAPL"},
            allocation_hint=None,
        )
        self.assertEqual(
            len(capture.calls), 0,
            "Candidate without _allocator_allocated_budget must not alert "
            "(legacy small-tier path is the documented fallback)",
        )

    def test_micro_tier_does_not_fire_alert_even_if_budget_set(self):
        """Per docs/small_tier_allocation.md and small_account_compounder
        line 105-110, micro tier IGNORES allocation_hint by design. The
        producer (allocator) should not write the budget for micro tier
        candidates; if it somehow did (test fixture, dev bypass), the
        defensive alert should NOT fire at micro tier because the
        producer's output is not load-bearing there."""
        capture = self._call_with_capture(
            capital=681.48,  # micro tier
            candidate={
                "score": 50,
                "symbol": "AAPL",
                "_allocator_allocated_budget": 186.31,
            },
            allocation_hint=None,
        )
        self.assertEqual(
            len(capture.calls), 0,
            "Micro tier must not fire allocator_hint_dropped — allocator "
            "is gated off for micro by design",
        )

    def test_legacy_path_still_runs_after_alert(self):
        """The alert fires BEFORE falling through to legacy; the
        sizing function still returns a usable budget so the cycle
        continues at degraded sizing rather than blocking."""
        from packages.quantum.services.analytics.small_account_compounder import (
            SmallAccountCompounder,
        )
        tier = SmallAccountCompounder.get_tier(1031.48)
        with patch(
            "packages.quantum.observability.alerts.alert"
        ), patch(
            "packages.quantum.observability.alerts._get_admin_supabase",
            return_value=MagicMock(),
        ):
            result = SmallAccountCompounder.calculate_variable_sizing(
                candidate={
                    "score": 50,
                    "symbol": "AAPL",
                    "_allocator_allocated_budget": 186.31,
                },
                capital=1031.48,
                tier=tier,
                regime="normal",
                compounding=True,
                allocation_hint=None,  # The regression shape
            )
        # Sizing still returned a number (the legacy fallback budget).
        # Not what we WANTED, but the cycle doesn't break.
        self.assertGreater(result["risk_budget"], 0)
        self.assertAlmostEqual(result["risk_budget"], 24.7555, places=3)


# ─────────────────────────────────────────────────────────────────
# Source-level guard on workflow_orchestrator
# ─────────────────────────────────────────────────────────────────


class TestWorkflowOrchestratorThreading(unittest.TestCase):
    """The 2026-05-20 production regression was: producer writes,
    consumer call site doesn't pass the value. Source-level
    inspection defends against the literal regression: re-introducing
    the call without ``allocation_hint=`` would be caught here.

    Source-level (rather than runtime) because the orchestrator's
    deep async dependencies make execution-time tests heavy; the
    question is purely structural — does the call site thread the
    field?"""

    @classmethod
    def setUpClass(cls):
        cls.src = (
            Path(__file__).resolve().parent.parent
            / "services" / "workflow_orchestrator.py"
        ).read_text(encoding="utf-8")

    def test_sizing_call_threads_allocation_hint(self):
        """The fix: the sizing call inside ``run_midday_cycle``
        threads ``allocation_hint=cand.get("_allocator_allocated_budget")``."""
        self.assertIn(
            'allocation_hint=cand.get("_allocator_allocated_budget")',
            self.src,
            "calculate_variable_sizing call must thread the allocator's "
            "per-candidate budget as allocation_hint. Without this, the "
            "producer's output is silently dropped and small-tier sizing "
            "falls through to the legacy ~3% multiplier stack.",
        )

    def test_recommended_risk_clamp_is_conditional_on_hint_applied(self):
        """When allocation_hint_applied=True, the workflow_orchestrator
        must NOT clamp against ``budgets.max_risk_per_trade`` — that
        value was computed at cycle-start without the hint and would
        throttle the allocator's distribution back to legacy values."""
        self.assertIn(
            'sizing_vars.get("allocation_hint_applied")',
            self.src,
            "The recommended_risk clamp must be conditional on whether "
            "the allocator-aware path was taken; otherwise the allocator's "
            "hint gets clamped down by the legacy-stack max_risk_per_trade.",
        )

    def test_producer_write_site_still_exists(self):
        """Sanity: the allocator wire-in still writes the budget to
        the candidate dict. This is the producer half of the chain."""
        self.assertIn(
            '_r.candidate["_allocator_allocated_budget"] = _r.allocated_budget',
            self.src,
            "PortfolioAllocator wire-in must still write the per-candidate "
            "budget to the candidate dict — that's the producer half of "
            "the verified-consumer chain.",
        )


if __name__ == "__main__":
    unittest.main()
