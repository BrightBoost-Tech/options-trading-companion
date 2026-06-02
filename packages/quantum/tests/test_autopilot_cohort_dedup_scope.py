"""Regression: per-cohort dedup scope in paper_autopilot_service._execute_per_cohort.

The bug (2026-06-01): cohort_held was built from get_open_positions(user_id) —
the WHOLE account — so a shadow_only cohort's open position for a symbol skipped
EVERY later cohort's pending suggestion for that symbol, including the live
aggressive champion. This silently lost live trades (BAC 2026-06-01).

The fix scopes cohort_held to THIS cohort's portfolio. These tests assert:
  - a shadow (conservative) BAC position does NOT block the live (aggressive)
    cohort's BAC entry — the live cohort still executes;
  - within-cohort dedup STILL holds — a cohort IS skipped for a symbol its OWN
    portfolio already holds (no double-entry).
"""

import types
import unittest
from datetime import datetime, timezone
from unittest import mock


_TODAY = datetime.now(timezone.utc).date().isoformat()


class _Resp:
    def __init__(self, data):
        self.data = data


class _SuggQuery:
    """Fake trade_suggestions query supporting the two chains _execute_per_cohort
    uses (all-pending + per-cohort), filtering by accumulated eq()."""
    def __init__(self, rows, filters=None):
        self._rows = rows
        self._f = dict(filters or {})

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        f = dict(self._f); f[col] = val
        return _SuggQuery(self._rows, f)

    def order(self, *a, **k):
        return self

    def limit(self, n):
        return self

    def execute(self):
        out = [r for r in self._rows if all(r.get(k) == v for k, v in self._f.items())]
        return _Resp(out)


class _FakeSupabase:
    def __init__(self, suggestions):
        self._sugg = suggestions

    def table(self, name):
        if name == "trade_suggestions":
            return _SuggQuery(self._sugg)
        return _SuggQuery([])  # other tables unused in these tests


def _suggestion(sid, cohort):
    return {"id": sid, "user_id": "user-1", "ticker": "BAC", "symbol": "BAC",
            "cohort_name": cohort, "status": "pending", "cycle_date": _TODAY,
            "ev": 50.0, "risk_adjusted_ev": 50.0}


def _run(open_positions):
    """Run _execute_per_cohort with conservative+aggressive cohorts, each with a
    pending BAC suggestion, and the given open positions. Returns the list of
    suggestion_ids that reached _stage_order_internal (i.e. were NOT deduped)."""
    from packages.quantum.services.paper_autopilot_service import PaperAutopilotService

    svc = PaperAutopilotService.__new__(PaperAutopilotService)
    svc.client = _FakeSupabase([_suggestion("con-bac", "conservative"),
                                _suggestion("agg-bac", "aggressive")])
    svc.get_open_positions = lambda uid: open_positions
    svc.get_already_executed_suggestion_ids_today = lambda uid: set()

    cfg = types.SimpleNamespace(max_suggestions_per_day=5)
    # conservative FIRST (matches today's scenario: shadow grabbed BAC first)
    configs = {"conservative": cfg, "aggressive": cfg}
    portfolios = {"conservative": "port-cons", "aggressive": "port-agg"}

    staged = []
    from packages.quantum.brokers.execution_router import ExecutionMode

    with mock.patch("packages.quantum.policy_lab.config.load_cohort_configs", return_value=configs), \
         mock.patch("packages.quantum.policy_lab.fork._get_cohort_portfolios", return_value=portfolios), \
         mock.patch("packages.quantum.paper_endpoints.get_analytics_service", return_value=mock.MagicMock()), \
         mock.patch("packages.quantum.paper_endpoints._suggestion_to_ticket", side_effect=lambda s: {"sid": s["id"]}), \
         mock.patch("packages.quantum.paper_endpoints._process_orders_for_user", return_value={"processed": 0}), \
         mock.patch("packages.quantum.brokers.execution_router.get_execution_mode", return_value=ExecutionMode.ALPACA_LIVE), \
         mock.patch("packages.quantum.paper_endpoints._stage_order_internal",
                    side_effect=lambda *a, **k: staged.append(k.get("suggestion_id_override")) or "ord-x"):
        svc._execute_per_cohort("user-1")
    return staged


class TestCohortDedupScope(unittest.TestCase):
    def test_shadow_position_does_not_starve_live_cohort(self):
        # conservative/shadow_only holds BAC (in port-cons). The aggressive/live
        # cohort's BAC must STILL execute (the bug skipped it).
        staged = _run([{"symbol": "BAC", "portfolio_id": "port-cons", "status": "open"}])
        self.assertIn("agg-bac", staged,
                      "live (aggressive) BAC must execute despite a shadow (conservative) BAC position")
        self.assertNotIn("con-bac", staged,
                         "conservative must be deduped against its OWN BAC position")

    def test_within_cohort_dedup_still_holds(self):
        # aggressive already holds BAC (in port-agg) → aggressive BAC must be
        # SKIPPED (no double-entry within a cohort). conservative has no BAC
        # position here → conservative BAC executes.
        staged = _run([{"symbol": "BAC", "portfolio_id": "port-agg", "status": "open"}])
        self.assertNotIn("agg-bac", staged,
                         "a cohort must still dedup against its own open position")
        self.assertIn("con-bac", staged,
                      "conservative (no BAC in its portfolio) must execute")

    def test_no_positions_both_cohorts_execute(self):
        staged = _run([])
        self.assertIn("agg-bac", staged)
        self.assertIn("con-bac", staged)


class TestDedupScopeSourceGuard(unittest.TestCase):
    def test_cohort_held_scoped_by_portfolio_id(self):
        # Regression guard against reverting to the user-wide build.
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent / "services" /
               "paper_autopilot_service.py").read_text(encoding="utf-8")
        self.assertIn('p.get("portfolio_id") == portfolio_id', src)


if __name__ == "__main__":
    unittest.main()
