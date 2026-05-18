"""
Regression tests for the 2 silent-failure query sites rewritten as
part of #62a-D1.

Pre-PR shape: both sites queried `is_champion = True` (a non-existent
column on `policy_lab_cohorts`), wrapped in `try/except: pass`, and
returned None on every call.

Post-PR shape: both sites query `promoted_at IS NOT NULL ORDER BY
promoted_at DESC LIMIT 1`, returning the most-recently-promoted
cohort. The silent try/except pattern is removed in favor of:

- paper_autopilot_service._get_champion_portfolio — logs warning on
  exception, returns None (caller treats None as "use default
  portfolio")
- paper_exit_evaluator._resolve_position_cohort path 3 — exception
  feeds the `_resolution_failures` list which drives the existing
  loud `paper_exit_cohort_resolve_exhausted` alert
"""

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


class _Chain:
    """Mock Supabase fluent-query chain that captures the column-filter
    sequence so tests can assert the rewritten sites no longer query
    the non-existent `is_champion` column."""

    def __init__(self, rows=None, raise_on_execute=None):
        self.rows = rows or []
        self.raise_on_execute = raise_on_execute
        self.calls = []  # records (kind, *args) tuples

    def table(self, name):
        self.calls.append(("table", name))
        return self

    def select(self, *args, **kwargs):
        return self

    def eq(self, col, val):
        self.calls.append(("eq", col, val))
        return self

    @property
    def not_(self):
        return _Not(self)

    def order(self, *args, **kwargs):
        self.calls.append(("order", args, kwargs))
        return self

    def limit(self, n):
        return self

    def execute(self):
        if self.raise_on_execute:
            raise self.raise_on_execute
        return MagicMock(data=self.rows)


class _Not:
    def __init__(self, parent):
        self.parent = parent

    def is_(self, col, val):
        self.parent.calls.append(("not_.is_", col, val))
        return self.parent


class _Client:
    def __init__(self, chain):
        self._chain = chain

    def table(self, name):
        return self._chain.table(name)


# ─────────────────────────────────────────────────────────────────
# Site 1 — paper_autopilot_service._get_champion_portfolio
# ─────────────────────────────────────────────────────────────────


class TestGetChampionPortfolioRewrite(unittest.TestCase):
    """Site 1: returns portfolio_id of the promoted champion cohort,
    or None when no cohort is promoted."""

    def _build_service(self, chain):
        from packages.quantum.services.paper_autopilot_service import (
            PaperAutopilotService,
        )
        return PaperAutopilotService(supabase_client=_Client(chain))

    def test_returns_promoted_portfolio_id(self):
        chain = _Chain(rows=[{"portfolio_id": "port-aggressive"}])
        svc = self._build_service(chain)
        result = svc._get_champion_portfolio("user-1")
        self.assertEqual(result, "port-aggressive")

    def test_query_does_not_reference_is_champion_column(self):
        chain = _Chain(rows=[{"portfolio_id": "port-aggressive"}])
        svc = self._build_service(chain)
        svc._get_champion_portfolio("user-1")
        eq_filters = [c for c in chain.calls if c[0] == "eq"]
        cols_queried = [c[1] for c in eq_filters]
        self.assertNotIn(
            "is_champion", cols_queried,
            "Pre-PR query used 'is_champion' (non-existent column); "
            "post-PR must not."
        )

    def test_query_filters_by_promoted_at_not_null(self):
        chain = _Chain(rows=[{"portfolio_id": "port-aggressive"}])
        svc = self._build_service(chain)
        svc._get_champion_portfolio("user-1")
        not_null = [c for c in chain.calls if c[0] == "not_.is_"]
        self.assertEqual(len(not_null), 1)
        self.assertEqual(not_null[0][1], "promoted_at")

    def test_returns_none_when_no_cohort_promoted(self):
        chain = _Chain(rows=[])
        svc = self._build_service(chain)
        result = svc._get_champion_portfolio("user-1")
        self.assertIsNone(result)

    def test_returns_none_on_db_exception(self):
        chain = _Chain(raise_on_execute=ConnectionError("simulated"))
        svc = self._build_service(chain)
        # Must not raise — the silent try/except is gone in favor of
        # a loud log + defensive None return.
        result = svc._get_champion_portfolio("user-1")
        self.assertIsNone(result)


# ─────────────────────────────────────────────────────────────────
# Site 2 — paper_exit_evaluator._resolve_position_cohort path 3
# ─────────────────────────────────────────────────────────────────


class TestResolvePositionCohortPathThreeRewrite(unittest.TestCase):
    """Site 2: path 3 fallback in _resolve_position_cohort returns
    the promoted champion's cohort_name when paths 1 and 2 fail."""

    def _build_evaluator(self, chain):
        from packages.quantum.services.paper_exit_evaluator import (
            PaperExitEvaluator,
        )
        return PaperExitEvaluator(supabase_client=_Client(chain))

    def test_path3_returns_promoted_cohort_name(self):
        # Position with no cohort_id and no portfolio_id → falls
        # through to path 3, which now finds the promoted champion.
        chain = _Chain(rows=[{"cohort_name": "aggressive"}])
        evaluator = self._build_evaluator(chain)
        position = {
            "id": "pos-1",
            "user_id": "user-1",
            "cohort_id": None,
            "portfolio_id": None,
        }
        result = evaluator._resolve_position_cohort(position)
        self.assertEqual(result, "aggressive")

    def test_path3_query_does_not_reference_is_champion(self):
        chain = _Chain(rows=[{"cohort_name": "aggressive"}])
        evaluator = self._build_evaluator(chain)
        position = {
            "id": "pos-1",
            "user_id": "user-1",
            "cohort_id": None,
            "portfolio_id": None,
        }
        evaluator._resolve_position_cohort(position)
        eq_filters = [c for c in chain.calls if c[0] == "eq"]
        cols_queried = [c[1] for c in eq_filters]
        self.assertNotIn("is_champion", cols_queried)

    def test_path3_query_uses_promoted_at_lookup(self):
        chain = _Chain(rows=[{"cohort_name": "aggressive"}])
        evaluator = self._build_evaluator(chain)
        position = {
            "id": "pos-1",
            "user_id": "user-1",
            "cohort_id": None,
            "portfolio_id": None,
        }
        evaluator._resolve_position_cohort(position)
        not_null = [c for c in chain.calls if c[0] == "not_.is_"]
        self.assertEqual(len(not_null), 1)
        self.assertEqual(not_null[0][1], "promoted_at")

    def test_path3_returns_none_when_no_cohort_promoted(self):
        # All 3 paths return empty/None. The function returns None;
        # the loud aggregate alert path is NOT triggered (alert only
        # fires when ALL paths RAISED, not when they returned empty).
        chain = _Chain(rows=[])
        evaluator = self._build_evaluator(chain)
        position = {
            "id": "pos-1",
            "user_id": "user-1",
            "cohort_id": None,
            "portfolio_id": None,
        }
        result = evaluator._resolve_position_cohort(position)
        self.assertIsNone(result)


# ─────────────────────────────────────────────────────────────────
# Source-level guards (defend against silent-try/except reintroduction)
# ─────────────────────────────────────────────────────────────────


class TestSilentTryExceptRemoved(unittest.TestCase):
    """The pre-PR shape was `try / ... is_champion ... / except: pass`.
    Source-level guards defend against reintroduction in either site."""

    def test_paper_autopilot_no_is_champion_column_query(self):
        from pathlib import Path
        src = (
            Path(__file__).resolve().parent.parent
            / "services" / "paper_autopilot_service.py"
        ).read_text(encoding="utf-8")
        # The string 'is_champion' may appear in the function's
        # backward-explanatory docstring; what's forbidden is a
        # `.eq("is_champion", True)` runtime query.
        self.assertNotIn('.eq("is_champion"', src)
        self.assertNotIn(".eq('is_champion'", src)

    def test_paper_exit_evaluator_no_is_champion_column_query(self):
        from pathlib import Path
        src = (
            Path(__file__).resolve().parent.parent
            / "services" / "paper_exit_evaluator.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn('.eq("is_champion"', src)
        self.assertNotIn(".eq('is_champion'", src)


if __name__ == "__main__":
    unittest.main()
