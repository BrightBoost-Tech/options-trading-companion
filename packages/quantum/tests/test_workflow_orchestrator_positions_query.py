"""
Source-level structural assertions for the paper-positions query fix
(2026-04-27).

Critical operational fix: workflow_orchestrator's _fetch_positions
helpers in both run_morning_cycle and run_midday_cycle previously
queried the `positions` table (Plaid-synced live brokerage holdings)
instead of `paper_positions` (the paper-trading table). Stale Plaid
sync rows from 2025-12/2026-03 were summed by RiskBudgetEngine to
~$508.75 of 'risk usage' against a $200 cap, triggering 'Risk budget
exhausted. Skipping midday cycle.' on every cycle since the live
broker handoff on 2026-04-25.

Tests assert the query targets `paper_positions` (with `status='open'`
filter) for both cycles. The negative regression guard ensures
`.table('positions')` is never reintroduced for paper risk budget
purposes in workflow_orchestrator.
"""

import os
import re
import unittest


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
ORCHESTRATOR_PATH = os.path.join(
    REPO_ROOT, "packages", "quantum", "services", "workflow_orchestrator.py"
)


def _load_orchestrator_source() -> str:
    with open(ORCHESTRATOR_PATH, "r", encoding="utf-8") as f:
        return f.read()


class TestMorningCyclePaperPositionsQuery(unittest.TestCase):
    """Morning cycle (~line 1091): _fetch_positions must query
    paper_positions with status='open'."""

    def setUp(self):
        self.src = _load_orchestrator_source()
        # Anchor on `run_morning_cycle` definition; the helper is the
        # first `async def _fetch_positions` after that point.
        morning_pos = self.src.find("async def run_morning_cycle")
        self.assertGreater(
            morning_pos, 0,
            "Could not locate run_morning_cycle definition",
        )
        # Take a window from the function start through the next ~3500
        # chars — enough to capture the supabase.table(...) call
        # inside _fetch_positions.
        self.block = self.src[morning_pos:morning_pos + 3500]

    def test_morning_queries_paper_positions(self):
        self.assertIn(
            '.table("paper_positions")', self.block,
            "Morning _fetch_positions must query paper_positions, "
            "not the live `positions` table.",
        )

    def test_morning_filters_status_open(self):
        self.assertIn(
            '.eq("status", "open")', self.block,
            "Morning _fetch_positions must filter status='open' to "
            "exclude closed paper positions from risk budget calc.",
        )


class TestMiddayCyclePaperPositionsQuery(unittest.TestCase):
    """Midday cycle (~line 1891): _fetch_positions must query
    paper_positions with status='open'."""

    def setUp(self):
        self.src = _load_orchestrator_source()
        midday_pos = self.src.find("async def run_midday_cycle")
        self.assertGreater(
            midday_pos, 0,
            "Could not locate run_midday_cycle definition",
        )
        self.block = self.src[midday_pos:midday_pos + 3500]

    def test_midday_queries_paper_positions(self):
        self.assertIn(
            '.table("paper_positions")', self.block,
            "Midday _fetch_positions must query paper_positions.",
        )

    def test_midday_filters_status_open(self):
        self.assertIn(
            '.eq("status", "open")', self.block,
            "Midday _fetch_positions must filter status='open'.",
        )


class TestNoPositionsTableForRiskBudget(unittest.TestCase):
    """Regression guard: workflow_orchestrator must not query
    `.table('positions')` for paper risk budget. Pre-fix,
    _fetch_positions queried `positions` (live brokerage holdings)
    which contained stale Plaid sync data blocking all trading via
    false 'budget exhausted' state.

    The `positions` table itself is not deprecated — it's still the
    correct target for v4 ledger reconciliation, holdings sync,
    cash service, dashboard endpoints, etc. This test only asserts
    that workflow_orchestrator (the suggestion-generation path)
    never reads from it.
    """

    def test_no_positions_table_query_in_workflow_orchestrator(self):
        src = _load_orchestrator_source()
        matches = re.findall(
            r'\.table\(\s*[\'"]positions[\'"]\s*\)', src
        )
        self.assertEqual(
            len(matches), 0,
            f"workflow_orchestrator must not query .table('positions'). "
            f"Use paper_positions instead. Found {len(matches)} match(es): "
            f"this regression caused the 2026-04-27 'budget exhausted' "
            f"production incident.",
        )


class TestModuleSyntaxValid(unittest.TestCase):
    """Verify workflow_orchestrator.py is syntactically valid Python
    after the query swap. Uses ast.parse to avoid triggering the
    heavy transitive dependency tree."""

    def test_module_parses(self):
        import ast
        src = _load_orchestrator_source()
        try:
            ast.parse(src)
        except SyntaxError as e:
            self.fail(f"workflow_orchestrator.py has a syntax error: {e}")


if __name__ == "__main__":
    unittest.main()
