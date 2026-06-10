"""Tests for the IPO readiness monitor (SPCX diagnostic, 2026-06-09).

OBSERVE-ONLY job: probes equity quote + options chain, reads the system's
own gate verdicts for the day, carries first-seen state in its own
job_runs.result, and writes INFO alerts on transitions. Pins:
- first-seen transitions set state + fire alerts exactly once
- prior state carries forward (no re-alert on later runs)
- provider failures are fail-soft per symbol (job still succeeds)
- gate verdicts read from the system's own tables
- env watch-list parse (default SPCX; empty retires)
- history-gate progress arithmetic (approx trading days vs 50 closes)
"""

import unittest
from datetime import date
from unittest import mock

from packages.quantum.jobs.handlers import ipo_readiness_monitor as irm


class _Resp:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def gte(self, *a, **k): return self
    def order(self, *a, **k): return self
    def limit(self, *a, **k): return self

    def insert(self, rec):
        self._rows.append(rec)
        return self

    def execute(self):
        return _Resp(list(self._rows))


class _FakeSupabase:
    def __init__(self, tables=None):
        self.tables = tables or {}

    def table(self, name):
        return _Q(self.tables.setdefault(name, []))


class _FakeMD:
    def __init__(self, quote=None, chain=None, quote_raises=False, chain_raises=False):
        self._quote = quote
        self._chain = chain
        self._quote_raises = quote_raises
        self._chain_raises = chain_raises

    def get_recent_quote(self, sym):
        if self._quote_raises:
            raise RuntimeError("quote api down")
        return self._quote

    def get_option_chain(self, sym, **k):
        if self._chain_raises:
            raise RuntimeError("chain api down")
        return self._chain


def _run(md, tables=None, env=None):
    sb = _FakeSupabase(tables)
    with mock.patch.object(irm, "get_admin_client", return_value=sb), \
         mock.patch("packages.quantum.market_data.PolygonService", return_value=md), \
         mock.patch.dict("os.environ", env or {}, clear=False):
        result = irm.run({})
    return result, sb


class TestTransitions(unittest.TestCase):
    def test_first_quote_sets_state_and_alerts(self):
        result, sb = _run(_FakeMD(quote={"price": 135.0}, chain=None))
        rep = result["report"]["SPCX"]
        self.assertTrue(rep["quote_seen_today"])
        self.assertIsNotNone(rep["first_quote_date"])
        self.assertIsNone(rep["first_chain_date"])
        kinds = [r.get("alert_type") for r in sb.tables.get("risk_alerts", [])]
        self.assertIn("ipo_watch_first_equity_quote", kinds)
        self.assertNotIn("ipo_watch_first_option_chain", kinds)

    def test_first_chain_sets_state_and_alerts(self):
        result, sb = _run(_FakeMD(quote={"price": 135.0}, chain=[{"symbol": "O:SPCX..."}]))
        rep = result["report"]["SPCX"]
        self.assertTrue(rep["chain_seen_today"])
        self.assertIsNotNone(rep["first_chain_date"])
        kinds = [r.get("alert_type") for r in sb.tables.get("risk_alerts", [])]
        self.assertIn("ipo_watch_first_option_chain", kinds)

    def test_prior_state_carries_and_no_realert(self):
        prior_run = {"result": {"state": {"SPCX": {
            "first_quote_date": "2026-06-12", "first_chain_date": "2026-06-16",
        }}}, "job_name": irm.JOB_NAME, "status": "succeeded"}
        result, sb = _run(
            _FakeMD(quote={"price": 140.0}, chain=[{"x": 1}]),
            tables={"job_runs": [prior_run]},
        )
        rep = result["report"]["SPCX"]
        self.assertEqual(rep["first_quote_date"], "2026-06-12")
        self.assertEqual(rep["first_chain_date"], "2026-06-16")
        self.assertEqual(sb.tables.get("risk_alerts", []), [])

    def test_no_quote_no_state(self):
        result, _ = _run(_FakeMD(quote={}, chain=None))
        rep = result["report"]["SPCX"]
        self.assertFalse(rep["quote_seen_today"])
        self.assertIsNone(rep["first_quote_date"])
        self.assertIsNone(rep["approx_daily_closes"])


class TestFailSoft(unittest.TestCase):
    def test_provider_failures_do_not_fail_the_job(self):
        result, _ = _run(_FakeMD(quote_raises=True, chain_raises=True))
        self.assertTrue(result["ok"])
        rep = result["report"]["SPCX"]
        self.assertFalse(rep["quote_seen_today"])
        self.assertFalse(rep["chain_seen_today"])


class TestWatchList(unittest.TestCase):
    def test_default_is_spcx(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("IPO_WATCH_SYMBOLS", None)
            self.assertEqual(irm._watch_symbols(), ["SPCX"])

    def test_env_list_parse(self):
        with mock.patch.dict("os.environ", {"IPO_WATCH_SYMBOLS": "spcx, abcd"}):
            self.assertEqual(irm._watch_symbols(), ["SPCX", "ABCD"])

    def test_empty_retires_watch(self):
        with mock.patch.dict("os.environ", {"IPO_WATCH_SYMBOLS": "  "}):
            self.assertEqual(irm._watch_symbols(), [])
        result, _ = _run(_FakeMD(quote={"price": 1.0}), env={"IPO_WATCH_SYMBOLS": ""})
        self.assertEqual(result["report"], {})


class TestHistoryGateProgress(unittest.TestCase):
    def test_approx_trading_days(self):
        # 2026-06-12 (Fri) through 2026-06-19 (Fri) = 6 weekdays
        self.assertEqual(
            irm._approx_trading_days("2026-06-12", date(2026, 6, 19)), 6,
        )
        self.assertIsNone(irm._approx_trading_days(None, date(2026, 6, 19)))
        self.assertIsNone(irm._approx_trading_days("garbage", date(2026, 6, 19)))

    def test_gate_remaining_in_report(self):
        prior_run = {"result": {"state": {"SPCX": {"first_quote_date": "2026-06-12"}}},
                     "job_name": irm.JOB_NAME, "status": "succeeded"}
        result, _ = _run(
            _FakeMD(quote={"price": 140.0}, chain=None),
            tables={"job_runs": [prior_run]},
        )
        rep = result["report"]["SPCX"]
        self.assertIsNotNone(rep["approx_daily_closes"])
        self.assertEqual(
            rep["history_gate_remaining"],
            max(0, irm.HISTORY_GATE_CLOSES - rep["approx_daily_closes"]),
        )


class TestGateVerdictReads(unittest.TestCase):
    def test_reads_rejections_selection_suggestions(self):
        today = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).date().isoformat()
        tables = {
            "suggestion_rejections": [
                {"symbol": "SPCX", "cycle_date": today, "reason": "insufficient_history"},
            ],
            "universe_selection_log": [
                {"selected_at": f"{today}T16:00:00+00:00",
                 "selected_symbols": ["SPCX", "NFLX"]},
            ],
            "trade_suggestions": [],
        }
        result, _ = _run(_FakeMD(quote={"price": 135.0}, chain=None), tables=tables)
        rep = result["report"]["SPCX"]
        self.assertEqual(rep["rejection_reasons_today"], ["insufficient_history"])
        self.assertTrue(rep["scanned_today"])
        self.assertEqual(rep["suggestions_today"], 0)


if __name__ == "__main__":
    unittest.main()
