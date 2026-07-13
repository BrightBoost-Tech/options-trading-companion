"""PR-① F-E8-3: a FAILED book/discovery read raises to the TOP, never []-as-empty.

ORIGIN-TO-TOP (the sharpened §9 doctrine): inject the failure AT ORIGIN — the
Supabase query itself throws — and assert AT THE TOP that the job goes non-green.
`_check_user` and `_fetch_open_positions` and `get_active_user_ids` are REAL in
these tests; NO intermediate function is mocked (a mock forfeits every layer
beneath it). The two directions are distinguishable by the ORIGIN (throw vs
empty-success), not by inspecting intermediate state.
"""
import contextlib
import os
import unittest
from unittest import mock

from packages.quantum.jobs.handlers import intraday_risk_monitor as mod
from packages.quantum.jobs.handlers.utils import get_active_user_ids


@contextlib.contextmanager
def _dummy_session(*a, **k):
    class _S:
        summary = None
    yield _S()


class _Query:
    """Chainable Supabase stub. execute() throws (failed read) or returns `data`."""
    def __init__(self, throw=False, data=None):
        self._throw = throw
        self._data = [] if data is None else data

    def table(self, *a, **k): return self
    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def neq(self, *a, **k): return self
    def in_(self, *a, **k): return self

    def execute(self):
        if self._throw:
            raise RuntimeError("DB down at ORIGIN")
        return mock.Mock(data=self._data)


class TestE8FetchPositionsOrigin(unittest.TestCase):
    def _monitor(self, supa):
        with mock.patch.object(mod, "get_admin_client", return_value=supa):
            return mod.IntradayRiskMonitor()

    def test_failed_read_raises_not_empty(self):
        # ORIGIN: the portfolio/position query throws → RAISE (was silent []).
        with self.assertRaises(Exception):
            self._monitor(_Query(throw=True))._fetch_open_positions("u1")

    def test_empty_success_returns_empty(self):
        # ORIGIN: query SUCCEEDS with [] → a genuinely-empty book, still [].
        self.assertEqual(self._monitor(_Query(throw=False, data=[]))._fetch_open_positions("u1"), [])


class TestE8ExecuteOriginToTop(unittest.TestCase):
    def setUp(self):
        self._p = mock.patch(
            "packages.quantum.observability.agent_sessions.agent_session", _dummy_session)
        self._p.start()
        for k in ("USER_ID", "TASK_USER_ID", "TRADING_USER_IDS"):
            os.environ.pop(k, None)

    def tearDown(self):
        self._p.stop()

    def _monitor(self, supa):
        with mock.patch.object(mod, "get_admin_client", return_value=supa):
            m = mod.IntradayRiskMonitor()
        m._is_market_open = lambda: True
        return m

    def test_positions_query_throw_makes_job_non_green(self):
        # ORIGIN→TOP: positions query throws; _check_user + _fetch_open_positions REAL.
        m = self._monitor(_Query(throw=True))
        m._get_active_user_ids = lambda payload: ["u1"]   # explicit user → skip discovery DB
        with self.assertRaises(Exception):
            m.execute({})

    def test_discovery_query_throw_makes_job_non_green(self):
        # ORIGIN→TOP: user-discovery query throws; get_active_user_ids REAL; never no_users.
        m = self._monitor(_Query(throw=True))          # no explicit user → discovery path
        with self.assertRaises(Exception):
            m.execute({})


class TestE8ActiveUserDiscoveryOrigin(unittest.TestCase):
    def setUp(self):
        for k in ("TRADING_USER_IDS",):
            os.environ.pop(k, None)

    def test_failed_discovery_raises_not_empty(self):
        with self.assertRaises(Exception):
            get_active_user_ids(_Query(throw=True))

    def test_empty_success_returns_empty(self):
        # genuinely-empty user_settings (query succeeds) → [] (legit, not a failure)
        self.assertEqual(get_active_user_ids(_Query(throw=False, data=[])), [])

    def test_success_returns_user_ids(self):
        self.assertEqual(
            get_active_user_ids(_Query(throw=False, data=[{"user_id": "u1"}, {"user_id": "u2"}])),
            ["u1", "u2"])


if __name__ == "__main__":
    unittest.main()
