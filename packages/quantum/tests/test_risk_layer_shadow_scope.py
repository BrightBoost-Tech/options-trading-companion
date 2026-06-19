"""Regression: live-entry risk checks must be scoped to the LIVE book.

The bug (2026-06-02, twin of the #1011 dedup contamination): the risk layer
fetched open positions across ALL cohort portfolios with no routing filter, so a
shadow_only / shadow_blocked cohort position (Conservative-cohort BAC,
internal/simulated) contaminated LIVE-capital risk decisions. With the live
account flat, that shadow BAC made "BAC = 100% of risk" -> the autopilot circuit
breaker BLOCKED live entries, and the intraday monitor fired phantom "BAC 100%"
critical alerts every 15 min.

The fix scopes the live-CAPITAL risk aggregates (circuit breaker, intraday
envelope, midday allocator/envelope, mark-to-market envelope) to live_eligible
portfolios via the shared risk.position_scope helper — WITHOUT blinding shadow
cohorts to their own per-position exit management (intraday 5a exit triggers
still run over the full managed set).
"""

import unittest
from pathlib import Path


class _Resp:
    def __init__(self, data):
        self.data = data


class _Q:
    """Fake Supabase query: accumulates eq()/in_() filters, returns matches."""
    def __init__(self, rows, filters=None, in_filter=None):
        self._rows = rows
        self._f = dict(filters or {})
        self._in = in_filter

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        f = dict(self._f); f[col] = val
        return _Q(self._rows, f, self._in)

    def neq(self, col, val):
        f = dict(self._f); f[("__neq__", col)] = val
        return _Q(self._rows, f, self._in)

    def in_(self, col, vals):
        return _Q(self._rows, self._f, (col, set(vals)))

    def execute(self):
        out = []
        for r in self._rows:
            ok = True
            for k, v in self._f.items():
                if isinstance(k, tuple) and k[0] == "__neq__":
                    if r.get(k[1]) == v:
                        ok = False
                elif r.get(k) != v:
                    ok = False
            if ok:
                out.append(r)
        if self._in:
            col, vals = self._in
            out = [r for r in out if r.get(col) in vals]
        return _Resp(out)


class _FakeSupa:
    def __init__(self, portfolios, positions):
        self._p = portfolios
        self._pos = positions

    def table(self, name):
        if name == "paper_portfolios":
            return _Q(self._p)
        if name == "paper_positions":
            return _Q(self._pos)
        return _Q([])


_PORTFOLIOS = [
    {"id": "port-live", "user_id": "u", "routing_mode": "live_eligible"},
    {"id": "port-cons", "user_id": "u", "routing_mode": "shadow_only"},
    {"id": "port-pshadow", "user_id": "u", "routing_mode": "paper_shadow"},
]


class TestPositionScopeHelper(unittest.TestCase):
    def test_only_live_eligible_portfolios(self):
        from packages.quantum.risk.position_scope import live_routed_portfolio_ids
        supa = _FakeSupa(_PORTFOLIOS, [])
        self.assertEqual(live_routed_portfolio_ids(supa, "u"), ["port-live"])

    def test_live_routing_mode_constant(self):
        from packages.quantum.risk.position_scope import LIVE_ROUTING_MODE
        self.assertEqual(LIVE_ROUTING_MODE, "live_eligible")


class TestCircuitBreakerScope(unittest.TestCase):
    """The harmful blocker: _get_open_positions_for_risk_check must return only
    live-routed positions."""

    def _svc(self, positions):
        from packages.quantum.services.paper_autopilot_service import PaperAutopilotService
        svc = PaperAutopilotService.__new__(PaperAutopilotService)
        svc.client = _FakeSupa(_PORTFOLIOS, positions)
        return svc

    def test_shadow_only_position_excluded(self):
        # The exact 2026-06-02 scenario: only open position is shadow BAC; live
        # book flat. The breaker must see an EMPTY set -> no phantom concentration.
        svc = self._svc([
            {"id": "bac", "symbol": "BAC", "portfolio_id": "port-cons", "status": "open"},
        ])
        out = svc._get_open_positions_for_risk_check("u")
        self.assertEqual(out, [], "shadow_only BAC must not reach the live circuit breaker")

    def test_paper_shadow_position_excluded(self):
        svc = self._svc([
            {"id": "x", "symbol": "X", "portfolio_id": "port-pshadow", "status": "open"},
        ])
        self.assertEqual(svc._get_open_positions_for_risk_check("u"), [])

    def test_live_position_still_included(self):
        # The control must still work for REAL exposure.
        svc = self._svc([
            {"id": "aapl", "symbol": "AAPL", "portfolio_id": "port-live", "status": "open"},
            {"id": "bac", "symbol": "BAC", "portfolio_id": "port-cons", "status": "open"},
        ])
        out = svc._get_open_positions_for_risk_check("u")
        self.assertEqual([p["symbol"] for p in out], ["AAPL"],
                         "live position must reach the breaker; shadow must not")


class TestConsumerConsistencySourceGuard(unittest.TestCase):
    """H13: all live-capital risk consumers scope via the shared helper, and the
    intraday monitor keeps per-position exits over the FULL set (0b)."""

    def _src(self, rel):
        return (Path(__file__).resolve().parent.parent / rel).read_text(encoding="utf-8")

    def test_autopilot_circuit_breaker_scopes_live(self):
        src = self._src("services/paper_autopilot_service.py")
        self.assertIn("LIVE_ROUTING_MODE", src)
        self.assertIn('.eq("routing_mode", LIVE_ROUTING_MODE)', src)

    def test_intraday_scopes_envelope_to_live_keeps_exits_full(self):
        src = self._src("jobs/handlers/intraday_risk_monitor.py")
        self.assertIn("live_routed_portfolio_ids", src)
        # #1035/#1036: the envelope + per-position exits now decide on the
        # executable-corroborated mark, but the live/full SCOPE split is
        # UNCHANGED — the envelope runs over the live subset, exits over the full
        # set. Pin that the corroborated sets derive from the right scope.
        self.assertIn(
            "_corr_live_positions = self._corroborate_exit_marks(live_positions)", src)
        self.assertIn("positions=_corr_live_positions", src)
        self.assertIn(
            "_corr_positions = self._corroborate_exit_marks(positions)", src)
        self.assertIn("_collect_intraday_exit_triggers(_corr_positions", src)

    def test_workflow_midday_scopes_live(self):
        src = self._src("services/workflow_orchestrator.py")
        self.assertIn("live_routed_portfolio_ids", src)

    def test_mark_to_market_scopes_live(self):
        src = self._src("jobs/handlers/paper_mark_to_market.py")
        self.assertIn("live_routed_portfolio_ids", src)


class TestIntradayPartitionLogic(unittest.TestCase):
    """The intraday partition: envelope sees live, exits see all."""

    def test_partition_excludes_shadow_from_envelope_keeps_for_exits(self):
        positions = [
            {"id": "aapl", "portfolio_id": "port-live", "status": "open"},
            {"id": "bac", "portfolio_id": "port-cons", "status": "open"},
        ]
        from packages.quantum.risk.position_scope import live_routed_portfolio_ids
        supa = _FakeSupa(_PORTFOLIOS, positions)
        live_ids = set(live_routed_portfolio_ids(supa, "u"))
        live_positions = [p for p in positions if p.get("portfolio_id") in live_ids]
        # envelope (live): only AAPL; exit-management set (full): both
        self.assertEqual([p["id"] for p in live_positions], ["aapl"])
        self.assertEqual(len(positions), 2)


if __name__ == "__main__":
    unittest.main()
