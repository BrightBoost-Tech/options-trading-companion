"""Tests for #62a-D4-PR2a routing dispatch safety gate.

Layer 1 (source-level structural): wiring exists at each gate site,
helper checks routing_mode, marker set, alert convention followed.

Layer 2 (behavioral, helper-scoped): the should_submit_to_broker
helper itself with mocked supabase.
- shadow_only → returns False
- live_eligible → returns True
- missing portfolio → returns False (defensive)

Full-flow behavioral tests (mock_alpaca + _stage_order_internal end
to end) deferred to PR2b when shadow fill path is wired and
meaningful behavioral assertions exist.
"""

import ast
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock


REPO_ROOT = Path(__file__).parent.parent


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────
# Layer 1 — Source-level structural assertions
# ─────────────────────────────────────────────────────────────────────


class TestHelperExists(unittest.TestCase):
    """should_submit_to_broker helper at brokers/execution_router.py."""

    @classmethod
    def setUpClass(cls):
        cls.src = _read("brokers/execution_router.py")

    def test_helper_function_present(self):
        self.assertIn("def should_submit_to_broker", self.src)
        ast.parse(self.src)

    def test_helper_checks_routing_mode(self):
        self.assertIn("routing_mode", self.src)
        self.assertIn("live_eligible", self.src)

    def test_helper_alerts_on_query_failure(self):
        self.assertIn("routing_dispatch_query_failed", self.src)
        self.assertIn("operator_action_required", self.src)
        self.assertIn('severity="critical"', self.src)

    def test_helper_defensive_returns_false_on_missing(self):
        self.assertIn("if not res.data", self.src,
                      "Helper must return False if portfolio is missing.")

    def test_helper_consequence_field_present(self):
        self.assertIn('"consequence"', self.src,
                      "Critical alerts must include consequence field per "
                      "Loud-Error Doctrine convention.")


class TestPaperEndpointsGate(unittest.TestCase):
    """paper_endpoints.py:752 area — autopilot entry gate."""

    @classmethod
    def setUpClass(cls):
        cls.src = _read("paper_endpoints.py")

    def test_helper_imported_and_called(self):
        self.assertIn("should_submit_to_broker", self.src)
        ast.parse(self.src)

    def test_shadow_blocked_marker_set(self):
        self.assertIn("shadow_blocked", self.src)

    def test_gate_marks_execution_mode(self):
        self.assertIn('"execution_mode": "shadow_blocked"', self.src)


class TestExitEvaluatorGate(unittest.TestCase):
    """paper_exit_evaluator.py:1184 area — exit close gate."""

    @classmethod
    def setUpClass(cls):
        cls.src = _read("services/paper_exit_evaluator.py")

    def test_helper_imported_and_called(self):
        self.assertIn("should_submit_to_broker", self.src)
        ast.parse(self.src)

    def test_shadow_blocked_marker_set(self):
        self.assertIn("shadow_blocked", self.src)

    def test_gate_marks_execution_mode(self):
        self.assertIn('"execution_mode": "shadow_blocked"', self.src)


class TestSafetyChecksGate(unittest.TestCase):
    """safety_checks.py:268 area — human approval gate."""

    @classmethod
    def setUpClass(cls):
        cls.src = _read("brokers/safety_checks.py")

    def test_helper_imported_and_called(self):
        self.assertIn("should_submit_to_broker", self.src)
        ast.parse(self.src)

    def test_shadow_blocked_marker_set(self):
        self.assertIn("shadow_blocked", self.src)

    def test_gate_supersedes_approval_via_existing_status(self):
        # Use 'rejected' (existing live_approval_queue.status value) with a
        # rejection_reason note — avoids introducing a new status enum
        # value if the column is enum-constrained.
        self.assertIn("Portfolio routing_mode flipped to shadow_only", self.src)


class TestSyncPathFilter(unittest.TestCase):
    """alpaca_order_sync excludes shadow_only portfolios."""

    @classmethod
    def setUpClass(cls):
        cls.src = _read("jobs/handlers/alpaca_order_sync.py")

    def test_sync_query_filters_shadow_only(self):
        self.assertIn("routing_mode", self.src)
        self.assertIn("shadow_only", self.src,
                      "Sync handler must filter out shadow_only portfolios.")

    def test_sync_uses_not_in_pattern(self):
        # The filter is implemented as a two-step query: fetch shadow
        # portfolio_ids, then exclude them from the pending-orders query.
        self.assertIn("shadow_portfolio_ids", self.src)
        self.assertIn(".not_.in_(\"portfolio_id\"", self.src)


class TestModuleSyntax(unittest.TestCase):
    """All modified files parse without SyntaxError."""

    def test_all_modified_files_parse(self):
        for path in [
            "brokers/execution_router.py",
            "paper_endpoints.py",
            "services/paper_exit_evaluator.py",
            "brokers/safety_checks.py",
            "jobs/handlers/alpaca_order_sync.py",
        ]:
            src = _read(path)
            try:
                ast.parse(src)
            except SyntaxError as e:
                self.fail(f"{path} has a syntax error: {e}")


# ─────────────────────────────────────────────────────────────────────
# Layer 2 — Behavioral (helper-scoped only)
# ─────────────────────────────────────────────────────────────────────


class TestShouldSubmitToBrokerHelper(unittest.TestCase):
    """Direct tests of the should_submit_to_broker helper with mocked
    supabase. Full-flow behavioral tests deferred to PR2b."""

    def _build_mock_supabase(self, return_data):
        mock = MagicMock()
        mock.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = return_data
        return mock

    def test_shadow_only_returns_false(self):
        from packages.quantum.brokers.execution_router import should_submit_to_broker
        mock = self._build_mock_supabase([{"routing_mode": "shadow_only"}])
        self.assertFalse(should_submit_to_broker("test_portfolio_id", mock))

    def test_live_eligible_returns_true(self):
        from packages.quantum.brokers.execution_router import should_submit_to_broker
        mock = self._build_mock_supabase([{"routing_mode": "live_eligible"}])
        self.assertTrue(should_submit_to_broker("test_portfolio_id", mock))

    def test_missing_portfolio_returns_false(self):
        """Defensive: missing portfolio = don't risk real submit."""
        from packages.quantum.brokers.execution_router import should_submit_to_broker
        mock = self._build_mock_supabase([])
        self.assertFalse(should_submit_to_broker("nonexistent_id", mock))

    def test_unknown_routing_mode_returns_false(self):
        """Any value other than 'live_eligible' returns False (e.g.
        future routing_modes added without explicit handling)."""
        from packages.quantum.brokers.execution_router import should_submit_to_broker
        mock = self._build_mock_supabase([{"routing_mode": "future_value"}])
        self.assertFalse(should_submit_to_broker("test_portfolio_id", mock))


if __name__ == "__main__":
    unittest.main()
