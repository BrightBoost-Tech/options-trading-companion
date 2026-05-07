"""Tests for #110 PR-3 — lifecycle EXPERIMENTAL sizing cap.

Three layers:
1. ``load_strategy_lifecycle_states`` — read helper (table read +
   empty / failure handling).
2. ``calculate_sizing(..., lifecycle_state=...)`` — cap behavior at
   each lifecycle state value.
3. Source-level structural guards on the scanner emission gate +
   workflow_orchestrator wiring.

Same ``sys.modules`` pollution shape as PR-B-1 / PR-B-2 could bite
``progression_service`` if test_weekly_report_win_rate.py loads first;
mirror the fix here — clear + capture at file load time.
"""

import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# Pollution remediation — see test_iv_rank_none_routing.py for the
# long explanation. Capture real classes at file-load time.
for _modname in (
    "packages.quantum.services.progression_service",
    "packages.quantum.services.sizing_engine",
):
    sys.modules.pop(_modname, None)
_progression_mod = importlib.import_module(
    "packages.quantum.services.progression_service"
)
_sizing_mod = importlib.import_module(
    "packages.quantum.services.sizing_engine"
)
load_strategy_lifecycle_states = _progression_mod.load_strategy_lifecycle_states
calculate_sizing = _sizing_mod.calculate_sizing

assert callable(load_strategy_lifecycle_states), (
    "progression_service was mocked at file-load time"
)
assert callable(calculate_sizing), (
    "sizing_engine was mocked at file-load time"
)


SCANNER_PATH = (
    Path(__file__).parent.parent / "options_scanner.py"
)
ORCHESTRATOR_PATH = (
    Path(__file__).parent.parent / "services" / "workflow_orchestrator.py"
)


class TestLoadStrategyLifecycleStates(unittest.TestCase):
    """Helper test: cycle-cached read returns dict mapping strategy
    name -> current_state, fails soft to empty dict on read errors.
    """

    def _make_supabase(self, rows):
        chain = MagicMock()
        chain.execute.return_value = MagicMock(data=list(rows))
        for m in ("select", "eq", "neq", "gte", "lte", "lt", "gt",
                  "in_", "order", "limit"):
            getattr(chain, m).return_value = chain
        sb = MagicMock()
        sb.table.return_value = chain
        return sb

    def test_full_seed_returned_as_dict(self):
        sb = self._make_supabase([
            {"strategy_name": "IRON_CONDOR", "current_state": "live_full"},
            {"strategy_name": "LONG_CALL_DEBIT_SPREAD", "current_state": "experimental"},
            {"strategy_name": "FOO", "current_state": "designed"},
        ])
        result = load_strategy_lifecycle_states(sb)
        self.assertEqual(result, {
            "IRON_CONDOR": "live_full",
            "LONG_CALL_DEBIT_SPREAD": "experimental",
            "FOO": "designed",
        })

    def test_empty_table_returns_empty_dict(self):
        sb = self._make_supabase([])
        result = load_strategy_lifecycle_states(sb)
        self.assertEqual(result, {})

    def test_db_failure_returns_empty_dict(self):
        sb = MagicMock()
        sb.table.return_value.select.return_value.execute.side_effect = (
            RuntimeError("simulated DB failure")
        )
        result = load_strategy_lifecycle_states(sb)
        self.assertEqual(result, {})


class TestSizingCapAtEachState(unittest.TestCase):
    """calculate_sizing must apply the EXPERIMENTAL cap correctly at
    each lifecycle state value.
    """

    def _size(self, lifecycle_state, **overrides):
        kwargs = dict(
            account_buying_power=10000.0,
            max_loss_per_contract=200.0,
            collateral_required_per_contract=200.0,
            risk_budget_dollars=2000.0,    # would size to ~10 contracts
            max_contracts=100,
            strategy="LONG_CALL_DEBIT_SPREAD",
            lifecycle_state=lifecycle_state,
        )
        kwargs.update(overrides)
        return calculate_sizing(**kwargs)

    def test_live_full_no_cap(self):
        result = self._size("live_full")
        self.assertGreater(result["contracts"], 1)
        self.assertFalse(result["experimental_capped"])
        self.assertEqual(result["lifecycle_state"], "live_full")

    def test_experimental_caps_to_one_when_normal_is_more(self):
        result = self._size("experimental")
        self.assertEqual(result["contracts"], 1)
        self.assertTrue(result["experimental_capped"])
        self.assertIn("experimental lifecycle", result["reason"])

    def test_experimental_no_cap_event_when_already_one(self):
        """Normal math returns 1 → cap is a no-op, no event flag."""
        result = self._size(
            "experimental",
            risk_budget_dollars=200.0,  # exactly one contract
        )
        self.assertEqual(result["contracts"], 1)
        self.assertFalse(result["experimental_capped"])

    def test_experimental_honors_zero_subthreshold(self):
        """Sub-threshold rejection (normal=0) is preserved — cap is a
        ceiling, not a floor.
        """
        result = self._size(
            "experimental",
            risk_budget_dollars=10.0,  # way below 1 contract risk
        )
        self.assertEqual(result["contracts"], 0)
        self.assertFalse(result["experimental_capped"])

    def test_designed_defensive_no_override(self):
        """If a designed candidate somehow reaches sizing (defensive),
        normal math runs — sizing is not the right place to gate.
        """
        result = self._size("designed")
        self.assertGreater(result["contracts"], 1)
        self.assertFalse(result["experimental_capped"])

    def test_deprecated_defensive_no_override(self):
        result = self._size("deprecated")
        self.assertGreater(result["contracts"], 1)
        self.assertFalse(result["experimental_capped"])

    def test_default_none_treated_as_live_full(self):
        """Calls without lifecycle_state preserve pre-#110 behavior."""
        kwargs = dict(
            account_buying_power=10000.0,
            max_loss_per_contract=200.0,
            collateral_required_per_contract=200.0,
            risk_budget_dollars=2000.0,
            max_contracts=100,
            strategy="LONG_CALL_DEBIT_SPREAD",
        )
        result = calculate_sizing(**kwargs)
        self.assertGreater(result["contracts"], 1)
        self.assertFalse(result["experimental_capped"])


class TestScannerLifecycleGate(unittest.TestCase):
    """Source-level guards on the scanner candidate-emission gate."""

    @classmethod
    def setUpClass(cls):
        cls.src = SCANNER_PATH.read_text(encoding="utf-8")

    def test_lifecycle_states_loaded_once_per_cycle(self):
        self.assertIn("load_strategy_lifecycle_states", self.src)
        # Outer fetch happens inside scan_for_opportunities, before
        # the per-symbol fan-out.
        self.assertIn("lifecycle_states_map", self.src)

    def test_designed_and_deprecated_filtered_at_emission(self):
        """The scanner must short-circuit before constructing the
        candidate dict for designed/deprecated strategies."""
        # Anchor on the candidate_dict construction; the gate must
        # appear immediately above.
        anchor = self.src.find("candidate_dict = {")
        self.assertGreater(anchor, 0)
        window = self.src[max(0, anchor - 800):anchor]
        self.assertIn('candidate_lifecycle_state', window)
        self.assertIn('"designed", "deprecated"', window)
        self.assertIn("return None", window)

    def test_lifecycle_state_attached_to_candidate_dict(self):
        """The emitted candidate dict carries the lifecycle_state key
        so downstream sizing can apply the cap.
        """
        # Any occurrence of the field literal inside a candidate
        # construction is sufficient; we don't pin to one site.
        self.assertIn('"lifecycle_state": candidate_lifecycle_state', self.src)


class TestWorkflowOrchestratorWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = ORCHESTRATOR_PATH.read_text(encoding="utf-8")

    def test_calculate_sizing_receives_lifecycle_state(self):
        """The orchestrator's calculate_sizing call must thread the
        lifecycle_state from the candidate dict. The call spans many
        lines with nested parens (float() casts, .get() defaults), so
        a balanced-paren scan isn't viable — use a liberal window.
        """
        # Locate the calculate_sizing(...) call site. Workflow file has
        # exactly one such call (verified at PR review time).
        anchor = self.src.find("calculate_sizing(\n")
        self.assertGreater(
            anchor, 0,
            "calculate_sizing(...) call not found in orchestrator",
        )
        window = self.src[anchor:anchor + 2000]
        self.assertIn("lifecycle_state=", window)
        self.assertIn('cand.get("lifecycle_state"', window)


if __name__ == "__main__":
    unittest.main()
