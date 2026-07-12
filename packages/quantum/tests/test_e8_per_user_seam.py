"""PR-① F-A4-E8: the intraday monitor's PER-USER loop must not persist green.

Drives IntradayRiskMonitor.execute() END-TO-END through a _check_user failure —
the full route to the seam, NOT a source-string pin of the outer run() raise (the
#1126 costume one layer up). Classification asserted via the REAL runner classifier.
"""
import contextlib
import unittest
from unittest import mock

from packages.quantum.jobs.handlers import intraday_risk_monitor as mod
from packages.quantum.jobs.runner import _classify_handler_return


@contextlib.contextmanager
def _dummy_session(*a, **k):
    class _S:
        summary = None
    yield _S()


class TestE8PerUserSeam(unittest.TestCase):
    def setUp(self):
        # agent_session is imported INSIDE execute() from its source module.
        self._patch = mock.patch(
            "packages.quantum.observability.agent_sessions.agent_session",
            _dummy_session)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()

    def _monitor(self, user_ids, failing):
        with mock.patch.object(mod, "get_admin_client", return_value=object()):
            m = mod.IntradayRiskMonitor()
        m._is_market_open = lambda: True
        m._get_active_user_ids = lambda payload: user_ids

        def _check(uid):
            if uid in failing:
                raise RuntimeError(f"boom {uid}")
            return {"user_id": uid, "violations": 0, "force_closes_submitted": 0}

        m._check_user = _check
        return m

    def test_single_user_failure_raises(self):
        # the normal one-user account: a single _check_user failure = complete cycle
        m = self._monitor(["u1"], {"u1"})
        with self.assertRaises(Exception):
            m.execute({})

    def test_all_users_failure_raises(self):
        m = self._monitor(["u1", "u2"], {"u1", "u2"})
        with self.assertRaises(Exception):
            m.execute({})

    def test_mixed_is_typed_partial(self):
        m = self._monitor(["u1", "u2"], {"u1"})
        result = m.execute({})
        self.assertEqual(result["users_failed"], 1)
        self.assertEqual(result["counts"]["errors"], 1)
        self.assertEqual(result["status"], "partial")
        self.assertFalse(result["ok"])
        # the REAL runner classifier must now see partial (was 'succeeded' — the bug)
        self.assertEqual(_classify_handler_return(result), "partial")

    def test_all_success_is_succeeded_byte_identical_classification(self):
        m = self._monitor(["u1", "u2"], set())
        result = m.execute({})
        self.assertEqual(result["users_failed"], 0)
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["ok"])
        self.assertEqual(_classify_handler_return(result), "succeeded")


if __name__ == "__main__":
    unittest.main()
