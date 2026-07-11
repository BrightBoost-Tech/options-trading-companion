"""E7 (2026-07-11) — viability re-wire on the ACTIVE executor route.

The M4 wiring (07-06) put the viability bias in
PaperAutopilotService.get_executable_suggestions — but policy-lab mode NEVER
calls it: execute_top_suggestions returns _execute_per_cohort at the
is_policy_lab_enabled() early-return, BEFORE that method. So the armed flag
steered nothing from 07-06 to 07-11 (the #1126 class, third instance).

These tests DRIVE _execute_per_cohort itself — the production route — with a
fake Supabase client, and assert on the ORDER suggestions reach
_stage_order_internal. Per CLAUDE.md §9: a wiring test EXECUTES the production
route, it does not REFERENCE the production function (no inspect.getsource, no
re-implemented sort). Model: test_autopilot_cohort_dedup_scope.py.

Tiers (canonical_ranker._VIABILITY_TIERS): SPY ×1.30, most others ×1.15.
Scenario: DB returns [BAC raev 25, SPY raev 20] (raw-EV-desc, as the .order()
would give). Armed → SPY 20×1.30 = 26 beats BAC 25 → staged [SPY, BAC].
Flag-off → raw order preserved → [BAC, SPY].

Seam pin: the .limit(max_suggestions_per_day) MUST move off the DB query to a
post-re-rank Python slice — else a server-side LIMIT truncates by RAW EV before
the re-rank and strands the biased winner. Asserted two ways: (1) with cap=1
armed, the RE-RANKED winner (SPY) is the one staged, not the raw winner (BAC);
(2) production calls .limit() ZERO times on the query builder.
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
    """Fake trade_suggestions query. .order()/.limit() are no-ops that return
    self (rows come back in INSERTION order — the test inserts them raw-EV-desc,
    as the real DB .order() would). .limit() also RECORDS its calls so the seam
    fix (limit moved to a Python slice) can be pinned structurally-by-execution:
    production must not call it on the query builder."""

    def __init__(self, rows, filters=None, limit_calls=None):
        self._rows = rows
        self._f = dict(filters or {})
        self._limit_calls = limit_calls if limit_calls is not None else []

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        f = dict(self._f)
        f[col] = val
        return _SuggQuery(self._rows, f, self._limit_calls)

    def order(self, *a, **k):
        return self

    def limit(self, n):
        self._limit_calls.append(n)
        return self

    def execute(self):
        out = [r for r in self._rows if all(r.get(k) == v for k, v in self._f.items())]
        return _Resp(list(out))


class _FakeSupabase:
    def __init__(self, suggestions, limit_calls):
        self._sugg = suggestions
        self._limit_calls = limit_calls

    def table(self, name):
        if name == "trade_suggestions":
            return _SuggQuery(self._sugg, limit_calls=self._limit_calls)
        return _SuggQuery([])  # other tables unused in these tests


def _sugg(sid, ticker, raev):
    return {
        "id": sid, "user_id": "user-1", "ticker": ticker, "symbol": ticker,
        "cohort_name": "aggressive", "status": "pending", "cycle_date": _TODAY,
        "ev": raev, "risk_adjusted_ev": raev,
    }


def _run(rows, *, bias_on, max_per_day, monkeypatch_env):
    """Drive the real _execute_per_cohort with one live cohort and the given
    pending rows. Returns (staged_suggestion_ids_in_order, db_limit_calls)."""
    from packages.quantum.services.paper_autopilot_service import PaperAutopilotService

    limit_calls: list = []
    svc = PaperAutopilotService.__new__(PaperAutopilotService)
    svc.client = _FakeSupabase(rows, limit_calls)
    svc.get_open_positions = lambda uid: []
    svc.get_already_executed_suggestion_ids_today = lambda uid: set()
    svc._stamp_blocked_reason = lambda *a, **k: None

    cfg = types.SimpleNamespace(max_suggestions_per_day=max_per_day)
    configs = {"aggressive": cfg}
    portfolios = {"aggressive": "port-agg"}

    staged: list = []
    from packages.quantum.brokers.execution_router import ExecutionMode

    monkeypatch_env()  # set/unset UNIVERSE_VIABILITY_BIAS_ENABLED before the run

    with mock.patch("packages.quantum.services.reentry_cooldown.is_enabled", return_value=False), \
         mock.patch("packages.quantum.risk.utilization_gate.is_enabled", return_value=False), \
         mock.patch("packages.quantum.policy_lab.config.load_cohort_configs", return_value=configs), \
         mock.patch("packages.quantum.policy_lab.fork._get_cohort_portfolios", return_value=portfolios), \
         mock.patch("packages.quantum.paper_endpoints.get_analytics_service", return_value=mock.MagicMock()), \
         mock.patch("packages.quantum.paper_endpoints._suggestion_to_ticket", side_effect=lambda s: {"sid": s["id"]}), \
         mock.patch("packages.quantum.paper_endpoints._process_orders_for_user", return_value={"processed": 0}), \
         mock.patch("packages.quantum.brokers.execution_router.get_execution_mode", return_value=ExecutionMode.ALPACA_LIVE), \
         mock.patch("packages.quantum.paper_endpoints._stage_order_internal",
                    side_effect=lambda *a, **k: staged.append(k.get("suggestion_id_override")) or "ord-x"):
        svc._execute_per_cohort("user-1")
    return staged, limit_calls


class TestE7ViabilityRewireRoute(unittest.TestCase):
    # DB returns raw-EV-desc: BAC(25) then SPY(20).
    ROWS = [_sugg("bac-id", "BAC", 25.0), _sugg("spy-id", "SPY", 20.0)]

    def test_armed_biased_winner_leads_staging(self):
        # SPY 20 × 1.30 = 26 > BAC 25 → the re-rank flips the order.
        def env():
            import os
            os.environ["UNIVERSE_VIABILITY_BIAS_ENABLED"] = "1"
        staged, _ = _run(list(self.ROWS), bias_on=True, max_per_day=5, monkeypatch_env=env)
        self.assertEqual(staged, ["spy-id", "bac-id"],
                         "armed: SPY (×1.30) must be staged before BAC through the live route")

    def test_flag_off_raw_order_preserved(self):
        def env():
            import os
            os.environ.pop("UNIVERSE_VIABILITY_BIAS_ENABLED", None)
        staged, _ = _run(list(self.ROWS), bias_on=False, max_per_day=5, monkeypatch_env=env)
        self.assertEqual(staged, ["bac-id", "spy-id"],
                         "flag-off: raw-EV order (BAC 25 > SPY 20) is byte-identical to legacy")

    def test_seam_limit_applied_after_rerank(self):
        # THE SEAM: cap=1. If the limit still ran on the DB query, the biased
        # winner would be truncated away by raw EV. Post-re-rank slice keeps
        # the RE-RANKED winner (SPY), and the DB query is never .limit()'d.
        def env():
            import os
            os.environ["UNIVERSE_VIABILITY_BIAS_ENABLED"] = "1"
        staged, limit_calls = _run(list(self.ROWS), bias_on=True, max_per_day=1, monkeypatch_env=env)
        self.assertEqual(staged, ["spy-id"],
                         "cap=1 armed: the re-ranked winner (SPY) survives, not the raw winner (BAC)")
        self.assertEqual(limit_calls, [],
                         "seam: .limit() must NOT run on the DB query (moved to a Python slice)")

    def tearDown(self):
        import os
        os.environ.pop("UNIVERSE_VIABILITY_BIAS_ENABLED", None)


if __name__ == "__main__":
    unittest.main()
