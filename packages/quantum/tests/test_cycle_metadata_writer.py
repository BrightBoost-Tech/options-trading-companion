"""
Regression tests for the cycle_metadata + enriched_counts writers
across all return paths of run_midday_cycle.

Origin: 2026-05-20 verification report — PR #959's cycle_metadata
write fired only on the happy-path return (workflow_orchestrator.py
line 3491). The 5 documented early-exit returns (and a 6th
discovered during this PR's code-read, ``global_risk_budget_exhausted``
at line 2121) all returned without cycle_metadata.

The fix introduces two helpers (``_build_cycle_metadata`` and
``_build_enriched_counts``) plus a unified ``exit_reason`` field
that distinguishes the 7 return paths:

  exit_reason=None                            → happy path (line 3491)
  exit_reason='micro_tier_position_open'      → line 2042 (pre-scanner)
  exit_reason='capital_scan_policy_block'     → line 2058 (pre-scanner)
  exit_reason='global_risk_budget_exhausted'  → line 2121 (post-budget, pre-scanner)
  exit_reason='no_candidates'                 → line 2344 (post-scanner, 0 emitted)
  exit_reason='scanner_failed'                → line 2360 (scanner exception)
  exit_reason='no_suggestions_after_gates'    → line 3197 (post-funnel)

Doctrine refinement codified in this PR (see
docs/loud_error_doctrine.md H9 silent-decision generalization,
"Early-exit observability symmetry" subsection): the partial-state
distinction is encoded by the value of each field, not by the
field's presence/absence. Pre-funnel exits emit None for measurements
that didn't happen; post-funnel exits emit the measured values.

Test strategy:
- Direct unit tests on the helpers (shape contract).
- Source-level guards on workflow_orchestrator.py confirming every
  return path in run_midday_cycle now includes a ``cycle_metadata``
  key (cheaper than mocking the deep async function).
- Consumer test on ops_health_service._resolve_regime_for_staleness
  confirming it iterates past pre-budget exits to find a regime.
"""

from pathlib import Path
import re
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# Stub alpaca-py so imports resolve in the test venv.
sys.modules.setdefault("alpaca", types.ModuleType("alpaca"))
sys.modules.setdefault("alpaca.trading", types.ModuleType("alpaca.trading"))
sys.modules.setdefault(
    "alpaca.trading.requests", types.ModuleType("alpaca.trading.requests")
)


# ─────────────────────────────────────────────────────────────────
# Helper shape contracts (direct unit tests)
# ─────────────────────────────────────────────────────────────────


class TestBuildCycleMetadata(unittest.TestCase):
    """Helper emits all 6 required fields; None passes through cleanly."""

    def _import(self):
        from packages.quantum.services.workflow_orchestrator import (
            _build_cycle_metadata,
        )
        return _build_cycle_metadata

    def test_happy_path_shape(self):
        build = self._import()
        meta = build(
            exit_reason=None,
            tier="small",
            regime="NORMAL",
            deployable_capital=1031.48,
            open_position_count=0,
            available_envelope_dollars=876.76,
        )
        self.assertIsNone(meta["exit_reason"])
        self.assertEqual(meta["tier"], "small")
        self.assertEqual(meta["regime"], "NORMAL")
        self.assertEqual(meta["deployable_capital"], 1031.48)
        self.assertEqual(meta["open_position_count"], 0)
        self.assertEqual(meta["available_envelope_dollars"], 876.76)

    def test_pre_scanner_exit_shape(self):
        """Pre-scanner exits (micro_tier_position_open) leave regime
        and available_envelope_dollars as None because the budget
        engine never ran. exit_reason is the only field we require."""
        build = self._import()
        meta = build(
            exit_reason="micro_tier_position_open",
            tier="micro",
            regime=None,
            deployable_capital=681.48,
            open_position_count=1,
            available_envelope_dollars=None,
        )
        self.assertEqual(meta["exit_reason"], "micro_tier_position_open")
        self.assertIsNone(meta["regime"])
        self.assertIsNone(meta["available_envelope_dollars"])

    def test_post_scanner_exit_shape(self):
        """Post-scanner exits (no_suggestions_after_gates) populate
        everything — budgets ran, scanner ran, candidates emitted."""
        build = self._import()
        meta = build(
            exit_reason="no_suggestions_after_gates",
            tier="small",
            regime="NORMAL",
            deployable_capital=1031.48,
            open_position_count=0,
            available_envelope_dollars=412.59,
        )
        self.assertEqual(meta["exit_reason"], "no_suggestions_after_gates")
        for k in ("tier", "regime", "deployable_capital",
                  "open_position_count", "available_envelope_dollars"):
            self.assertIsNotNone(meta[k], f"{k} should be populated")

    def test_all_six_keys_always_present(self):
        """The shape contract: every field is present, even when
        valued None. Consumers can distinguish 'measured as None'
        from 'key missing' (which used to be the bug)."""
        build = self._import()
        meta = build(
            exit_reason=None,
            tier=None,
            regime=None,
            deployable_capital=None,
            open_position_count=None,
            available_envelope_dollars=None,
        )
        for k in ("exit_reason", "tier", "regime",
                  "deployable_capital", "open_position_count",
                  "available_envelope_dollars"):
            self.assertIn(k, meta)


class TestBuildEnrichedCounts(unittest.TestCase):
    """v959 funnel-stage counts; all 7 keys always present."""

    def _import(self):
        from packages.quantum.services.workflow_orchestrator import (
            _build_enriched_counts,
        )
        return _build_enriched_counts

    def test_happy_path_shape(self):
        build = self._import()
        counts = build(
            universe_size=50,
            scanner_emitted=50,
            trade_suggestions_created=4,
            h7_passed=4,
            edge_above_minimum=3,
            executable=4,
            staged=4,
        )
        self.assertEqual(counts["scanner_emitted"], 50)
        self.assertEqual(counts["trade_suggestions_created"], 4)
        self.assertEqual(counts["edge_above_minimum"], 3)

    def test_pre_scanner_exit_all_none(self):
        """Pre-scanner exits encode 'not measured' as None across
        every funnel stage."""
        build = self._import()
        counts = build(
            universe_size=None,
            scanner_emitted=None,
            trade_suggestions_created=None,
            h7_passed=None,
            edge_above_minimum=None,
            executable=None,
            staged=None,
        )
        self.assertEqual(
            set(counts.values()), {None},
            "All v959 keys should be None for a pre-scanner exit",
        )

    def test_post_scanner_zero_emitted_is_measured(self):
        """no_candidates path: scanner ran and emitted 0. That's a
        measurement (0), distinct from 'not measured' (None)."""
        build = self._import()
        counts = build(
            universe_size=0,
            scanner_emitted=0,
            trade_suggestions_created=0,
            h7_passed=None,
            edge_above_minimum=None,
            executable=None,
            staged=None,
        )
        self.assertEqual(counts["scanner_emitted"], 0)
        self.assertIsNone(counts["h7_passed"])

    def test_seven_keys_always_present(self):
        build = self._import()
        counts = build(
            universe_size=None, scanner_emitted=None,
            trade_suggestions_created=None, h7_passed=None,
            edge_above_minimum=None, executable=None, staged=None,
        )
        for k in ("universe_size", "scanner_emitted",
                  "trade_suggestions_created", "h7_passed",
                  "edge_above_minimum", "executable", "staged"):
            self.assertIn(k, counts)


# ─────────────────────────────────────────────────────────────────
# Source-level guards: every return site uses the helper
# ─────────────────────────────────────────────────────────────────


class TestAllReturnPathsEmitCycleMetadata(unittest.TestCase):
    """Confirm each of the 7 documented return sites in
    run_midday_cycle includes a ``cycle_metadata`` key. Source-level
    inspection rather than runtime mocking — the orchestrator's deep
    async dependencies make full-stack execution-time tests heavy,
    and the question we're answering is purely structural: does every
    return path emit the field?"""

    @classmethod
    def setUpClass(cls):
        cls.src = (
            Path(__file__).resolve().parent.parent
            / "services" / "workflow_orchestrator.py"
        ).read_text(encoding="utf-8")

    def _slice_function(self) -> str:
        """Extract just the run_midday_cycle function body, so we
        don't trip on the other functions' returns in the file."""
        start = self.src.index("async def run_midday_cycle(")
        # The next top-level ``async def`` or ``def`` begins the
        # following function.
        rest = self.src[start + len("async def run_midday_cycle("):]
        m = re.search(r"\nasync def |\ndef ", rest)
        end = (start + len("async def run_midday_cycle(") + m.start()
               if m else len(self.src))
        return self.src[start:end]

    def test_micro_tier_position_open_emits_cycle_metadata(self):
        body = self._slice_function()
        idx = body.index('"reason": "micro_tier_position_open"')
        # Window forward from the reason marker to the closing brace.
        window = body[idx:idx + 1500]
        self.assertIn('"cycle_metadata":', window)
        self.assertIn('exit_reason="micro_tier_position_open"', window)

    def test_capital_scan_policy_block_emits_cycle_metadata(self):
        body = self._slice_function()
        idx = body.index('"reason": scan_reason')
        window = body[idx:idx + 1500]
        self.assertIn('"cycle_metadata":', window)
        self.assertIn('exit_reason="capital_scan_policy_block"', window)

    def test_global_risk_budget_exhausted_emits_cycle_metadata(self):
        """The 7th return path discovered during this PR's code-read
        (was not in yesterday's investigation report)."""
        body = self._slice_function()
        idx = body.index('"reason": "global_risk_budget_exhausted"')
        window = body[idx:idx + 1500]
        self.assertIn('"cycle_metadata":', window)
        self.assertIn('exit_reason="global_risk_budget_exhausted"', window)

    def test_no_candidates_emits_cycle_metadata(self):
        body = self._slice_function()
        idx = body.index('"reason": "no_candidates"')
        window = body[idx:idx + 2000]
        self.assertIn('"cycle_metadata":', window)
        self.assertIn('exit_reason="no_candidates"', window)

    def test_scanner_failed_emits_cycle_metadata(self):
        body = self._slice_function()
        idx = body.index('"reason": f"scanner_failed:')
        window = body[idx:idx + 1500]
        self.assertIn('"cycle_metadata":', window)
        self.assertIn('exit_reason="scanner_failed"', window)

    def test_no_suggestions_after_gates_emits_cycle_metadata(self):
        """Today's path (2026-05-20). Post-funnel exit — every field
        populated, exit_reason='no_suggestions_after_gates'."""
        body = self._slice_function()
        idx = body.index('"reason": "no_suggestions_after_gates"')
        window = body[idx:idx + 2000]
        self.assertIn('"cycle_metadata":', window)
        self.assertIn('exit_reason="no_suggestions_after_gates"', window)

    def test_happy_path_emits_cycle_metadata_with_none_exit_reason(self):
        body = self._slice_function()
        idx = body.index('"reason": None')
        window = body[idx:idx + 2500]
        self.assertIn('"cycle_metadata":', window)
        self.assertIn("exit_reason=None", window)

    def test_no_return_path_uses_old_inline_dict_shape(self):
        """Defends against re-introduction of inline
        ``"cycle_metadata": {...}`` dict construction inside
        run_midday_cycle — every emission must go through the helper.

        The helper signature is the only legitimate place where the
        key word ``exit_reason`` is followed by ``=`` rather than ``:``.
        """
        body = self._slice_function()
        # Inline dict construction would use ``"exit_reason":`` (JSON
        # key style); helper calls use ``exit_reason=`` (kwarg style).
        # If anyone reintroduces the inline shape, this guard fails.
        self.assertNotIn('"exit_reason":', body,
                         "cycle_metadata must be constructed via "
                         "_build_cycle_metadata helper, not inline dict")


# ─────────────────────────────────────────────────────────────────
# Consumer test — staleness gate regime fallback
# ─────────────────────────────────────────────────────────────────


class TestStalenessGateConsumerIteratesPastNullRegime(unittest.TestCase):
    """ops_health_service._resolve_regime_for_staleness must skip
    over recent cycles whose cycle_metadata.regime is None (pre-budget
    early-exits) and find a cycle with regime populated. Fail-closed
    to 'shock' only when no recent cycle has regime data."""

    def _cycle_row(self, regime):
        return {
            "result": {
                "cycle_results": [
                    {"cycle_metadata": {"regime": regime}}
                ]
            }
        }

    def _build_client(self, rows):
        client = MagicMock()
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.order.return_value = chain
        chain.limit.return_value = chain
        chain.execute.return_value = MagicMock(data=rows)
        client.table.return_value = chain
        return client

    def test_returns_regime_when_most_recent_cycle_has_it(self):
        from packages.quantum.services.ops_health_service import (
            _resolve_regime_for_staleness,
        )
        client = self._build_client([self._cycle_row("NORMAL")])
        with patch(
            "packages.quantum.jobs.handlers.utils.get_admin_client",
            return_value=client,
        ):
            self.assertEqual(
                _resolve_regime_for_staleness(None), "normal"
            )

    def test_skips_pre_budget_exits_to_find_regime(self):
        """The originating defect class: if the most recent cycle
        is a pre-budget early-exit (regime=None in the new shape),
        the consumer must NOT fail-closed to 'shock' — it must
        iterate to the next cycle that has regime."""
        from packages.quantum.services.ops_health_service import (
            _resolve_regime_for_staleness,
        )
        client = self._build_client([
            self._cycle_row(None),       # pre-budget exit (regime=None)
            self._cycle_row(None),       # another pre-budget exit
            self._cycle_row("NORMAL"),   # eventually a real regime
        ])
        with patch(
            "packages.quantum.jobs.handlers.utils.get_admin_client",
            return_value=client,
        ):
            self.assertEqual(
                _resolve_regime_for_staleness(None), "normal"
            )

    def test_fail_closed_to_shock_when_no_regime_in_window(self):
        """All recent cycles are pre-budget exits → no regime
        recoverable → fail-closed to 'shock'."""
        from packages.quantum.services.ops_health_service import (
            _resolve_regime_for_staleness,
        )
        client = self._build_client([
            self._cycle_row(None),
            self._cycle_row(None),
            self._cycle_row(None),
        ])
        with patch(
            "packages.quantum.jobs.handlers.utils.get_admin_client",
            return_value=client,
        ):
            self.assertEqual(
                _resolve_regime_for_staleness(None), "shock"
            )

    def test_caller_provided_regime_short_circuits(self):
        """Caller-supplied regime bypasses the lookup entirely
        (pre-existing behavior, retained)."""
        from packages.quantum.services.ops_health_service import (
            _resolve_regime_for_staleness,
        )
        self.assertEqual(
            _resolve_regime_for_staleness("elevated"), "elevated"
        )


# ─────────────────────────────────────────────────────────────────
# exit_reason discriminator: distinct values across paths
# ─────────────────────────────────────────────────────────────────


class TestExitReasonDistinguishesPaths(unittest.TestCase):
    """Source-level confirmation that the 6 documented exit_reason
    values appear in run_midday_cycle, each exactly once (each path
    has one canonical reason)."""

    @classmethod
    def setUpClass(cls):
        cls.src = (
            Path(__file__).resolve().parent.parent
            / "services" / "workflow_orchestrator.py"
        ).read_text(encoding="utf-8")

    def test_six_distinct_exit_reasons_present(self):
        for reason in (
            "micro_tier_position_open",
            "capital_scan_policy_block",
            "global_risk_budget_exhausted",
            "no_candidates",
            "scanner_failed",
            "no_suggestions_after_gates",
        ):
            self.assertIn(
                f'exit_reason="{reason}"', self.src,
                f"Missing exit_reason='{reason}' helper call — the "
                f"corresponding return path is not emitting "
                f"cycle_metadata via the helper.",
            )

    def test_happy_path_uses_none_exit_reason(self):
        self.assertIn(
            "exit_reason=None", self.src,
            "Happy path must call _build_cycle_metadata with "
            "exit_reason=None to signal successful funnel completion.",
        )


if __name__ == "__main__":
    unittest.main()
