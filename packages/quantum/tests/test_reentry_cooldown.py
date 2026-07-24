"""Just-stopped re-entry cooldown — HARD LOCKOUT (2026-06-08 whipsaw fix).

The per-symbol loss envelope stopped NFLX at 14:15Z (−$84); the 16:30Z scan
re-entered the identical structure on live money because monitor and scanner
shared no state. These pin the writer (per-symbol stop → cooldown), the window
computation, the two reader gates, cross-cohort isolation, fail-closed reads,
and the default-ON flag.
"""

import os
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from packages.quantum.tests._alpaca_stub import ensure_alpaca as _ensure_alpaca

_ensure_alpaca()

from packages.quantum.services import reentry_cooldown as rc  # noqa: E402
from packages.quantum.risk.risk_envelope import (  # noqa: E402
    check_loss_envelopes,
    check_all_envelopes,
    EnvelopeConfig,
)

LIVE = "3d289dca"   # aggressive / live champion cohort
SHADOW = "ec545555"  # conservative shadow cohort


# ── Fake PostgREST layer applying eq/gt/in_ to in-memory rows ───────────────

class _Q:
    def __init__(self, store, raise_on):
        self.store, self.raise_on = store, raise_on
        self._rows = list(store["rows"])
        self._insert = None

    def select(self, *a, **k):
        return self

    def insert(self, row):
        self._insert = row
        return self

    def eq(self, col, val):
        self._rows = [r for r in self._rows if r.get(col) == val]
        return self

    def gt(self, col, val):
        self._rows = [r for r in self._rows if str(r.get(col, "")) > str(val)]
        return self

    def in_(self, col, vals):
        self._rows = [r for r in self._rows if r.get(col) in vals]
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        if self.raise_on:
            raise RuntimeError("db down")
        if self._insert is not None:
            self.store["rows"].append(self._insert)
            return types.SimpleNamespace(data=[{"id": "new", **self._insert}])
        return types.SimpleNamespace(data=list(self._rows))


class _FakeSB:
    def __init__(self, rows=None, raise_on=False, cohort_map=None):
        self.store = {"rows": list(rows or [])}
        self.raise_on = raise_on
        self.cohort_map = cohort_map or {}

    def table(self, name):
        if name == "policy_lab_cohorts":
            rows = [{"id": cid, "portfolio_id": pid}
                    for pid, cid in self.cohort_map.items()]
            return _Q({"rows": rows}, self.raise_on)
        return _Q(self.store, self.raise_on)


def _future(hours=4):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def _past():
    return (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()


def _cd_row(cohort, symbol, until):
    return {"cohort_id": cohort, "symbol": symbol, "cooldown_until": until}


# ── Flag ────────────────────────────────────────────────────────────────────

class TestFlag(unittest.TestCase):
    def setUp(self):
        os.environ.pop(rc.FLAG_ENV, None)

    def test_default_on_unset(self):
        self.assertTrue(rc.is_enabled())

    def test_empty_string_is_on(self):
        with patch.dict(os.environ, {rc.FLAG_ENV: ""}):
            self.assertTrue(rc.is_enabled())
        with patch.dict(os.environ, {rc.FLAG_ENV: "  "}):
            self.assertTrue(rc.is_enabled())

    def test_explicit_falsy_off(self):
        for v in ("0", "false", "no", "off", "OFF"):
            with patch.dict(os.environ, {rc.FLAG_ENV: v}):
                self.assertFalse(rc.is_enabled(), v)

    def test_truthy_on(self):
        for v in ("1", "true", "yes", "on"):
            with patch.dict(os.environ, {rc.FLAG_ENV: v}):
                self.assertTrue(rc.is_enabled(), v)


# ── Window ──────────────────────────────────────────────────────────────────

class TestWindow(unittest.TestCase):
    def setUp(self):
        os.environ.pop(rc.OVERRIDE_ENV, None)

    def test_next_open_default(self):
        no = (datetime.now(timezone.utc) + timedelta(hours=15)).isoformat()
        until = rc.compute_cooldown_until(clock_fn=lambda: {"next_open": no})
        self.assertEqual(
            datetime.fromisoformat(until),
            datetime.fromisoformat(no),
        )

    def test_override_minutes(self):
        with patch.dict(os.environ, {rc.OVERRIDE_ENV: "30"}):
            until = rc.compute_cooldown_until(clock_fn=lambda: {"next_open": _future()})
        delta = datetime.fromisoformat(until) - datetime.now(timezone.utc)
        self.assertTrue(timedelta(minutes=28) < delta < timedelta(minutes=32))

    def test_clock_failure_falls_back_24h_never_zero(self):
        def _boom():
            raise RuntimeError("clock unreachable")
        until = rc.compute_cooldown_until(clock_fn=_boom)
        parsed = datetime.fromisoformat(until)
        # ~24h ahead, and crucially NOT in the past (zero/past = no lockout).
        self.assertGreater(parsed, datetime.now(timezone.utc) + timedelta(hours=23))

    def test_missing_next_open_falls_back_not_zero(self):
        until = rc.compute_cooldown_until(clock_fn=lambda: {})
        self.assertGreater(datetime.fromisoformat(until),
                           datetime.now(timezone.utc) + timedelta(hours=23))


# ── Writer + idempotency + fail-loud ────────────────────────────────────────

class TestWriter(unittest.TestCase):
    def test_inserts_cooldown_row(self):
        sb = _FakeSB()
        ok = rc.write_cooldown(
            sb, cohort_id=LIVE, symbol="NFLX", cooldown_until=_future(),
            reason=rc.COOLDOWN_REASON, triggering_position_id="pos-1",
            realized_loss=-84.0,
        )
        self.assertTrue(ok)
        self.assertEqual(len(sb.store["rows"]), 1)
        self.assertEqual(sb.store["rows"][0]["cohort_id"], LIVE)
        self.assertEqual(sb.store["rows"][0]["symbol"], "NFLX")

    def test_idempotent_skip_when_active(self):
        sb = _FakeSB(rows=[_cd_row(LIVE, "NFLX", _future())])
        ok = rc.write_cooldown(sb, cohort_id=LIVE, symbol="NFLX",
                               cooldown_until=_future())
        self.assertFalse(ok)  # skipped, no duplicate
        self.assertEqual(len(sb.store["rows"]), 1)

    def test_write_failure_is_loud_not_raised(self):
        sb = _FakeSB(raise_on=True)
        with patch("packages.quantum.observability.alerts.alert") as _a:
            ok = rc.write_cooldown(sb, cohort_id=LIVE, symbol="NFLX",
                                   cooldown_until=_future())
        self.assertFalse(ok)  # never raises into the monitor cycle
        self.assertTrue(_a.called)  # loud critical alert fired


# ── is_active / active_symbols + fail-closed ────────────────────────────────

class TestReadChecks(unittest.TestCase):
    def test_active_true_future_false_past(self):
        sb = _FakeSB(rows=[_cd_row(LIVE, "NFLX", _future())])
        self.assertTrue(rc.is_active(sb, LIVE, "NFLX"))
        sb2 = _FakeSB(rows=[_cd_row(LIVE, "NFLX", _past())])
        self.assertFalse(rc.is_active(sb2, LIVE, "NFLX"))  # expired

    def test_query_error_raises_cooldownqueryerror(self):
        sb = _FakeSB(raise_on=True)
        with self.assertRaises(rc.CooldownQueryError):
            rc.is_active(sb, LIVE, "NFLX")

    def test_missing_table_code_fails_open(self):
        # Deploy window (migration not yet applied / stale schema cache): a
        # STRUCTURED UndefinedTable code fails OPEN — keyed on .code, NOT a
        # message string.
        for code in ("PGRST205", "42P01"):
            class _MissingTableSB:
                def table(self, name):
                    e = RuntimeError("table missing")
                    e.code = code  # structured code, as postgrest APIError exposes
                    raise e
            self.assertFalse(rc.is_active(_MissingTableSB(), LIVE, "NFLX"), code)
            self.assertEqual(
                rc.active_symbols(_MissingTableSB(), LIVE, ["NFLX"]), set(), code)

    def test_codeless_error_fails_closed_not_open(self):
        # An error WITHOUT an UndefinedTable code (incl. one whose MESSAGE
        # mentions the table) must fail CLOSED — no string-match fail-open.
        class _StringySB:
            def table(self, name):
                raise RuntimeError(
                    "could not find the table reentry_cooldowns in the schema cache"
                )
        with self.assertRaises(rc.CooldownQueryError):
            rc.is_active(_StringySB(), LIVE, "NFLX")

    def test_active_symbols_subset(self):
        sb = _FakeSB(rows=[_cd_row(LIVE, "NFLX", _future()),
                           _cd_row(LIVE, "SPY", _past())])
        self.assertEqual(rc.active_symbols(sb, LIVE, ["NFLX", "SPY", "QQQ"]),
                         {"NFLX"})

    def test_cross_cohort_isolation(self):
        # A LIVE-cohort cooldown does NOT bench the SHADOW cohort's same symbol.
        sb = _FakeSB(rows=[_cd_row(LIVE, "NFLX", _future())])
        self.assertTrue(rc.is_active(sb, LIVE, "NFLX"))
        self.assertFalse(rc.is_active(sb, SHADOW, "NFLX"))

    def test_resolve_cohort_id(self):
        sb = _FakeSB(cohort_map={"814cb84b": LIVE})
        self.assertEqual(rc.resolve_cohort_id(sb, "814cb84b"), LIVE)
        self.assertIsNone(rc.resolve_cohort_id(sb, "unknown"))


# ── Writer source: EnvelopeResult.symbol_loss_stops ─────────────────────────

class TestEnvelopeSymbolLossStops(unittest.TestCase):
    def _pos(self, pid, symbol, upl, cohort=LIVE):
        return {
            "id": pid, "symbol": symbol, "unrealized_pl": upl,
            "cohort_id": cohort, "quantity": 1, "avg_entry_price": 3.0,
        "legs": [
            {"symbol": "NFLX260918P00100000", "action": "buy",
             "type": "put", "strike": 100.0, "expiry": "2026-09-18",
             "quantity": 1},
            {"symbol": "NFLX260918P00095000", "action": "sell",
             "type": "put", "strike": 95.0, "expiry": "2026-09-18",
             "quantity": 1},
        ],
            "portfolio_id": "pf",
        }

    def test_per_symbol_breach_recorded(self):
        # equity 2300 → 3% = $69 threshold; −$200 breaches.
        out = []
        check_loss_envelopes(2300.0, 0.0, 0.0, [self._pos("p1", "NFLX", -200.0)],
                             EnvelopeConfig(), symbol_loss_stops_out=out)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["symbol"], "NFLX")
        self.assertEqual(out[0]["cohort_id"], LIVE)
        self.assertEqual(out[0]["position_id"], "p1")
        self.assertEqual(out[0]["realized_loss"], -200.0)  # trigger-time loss

    def test_within_limit_not_recorded(self):
        out = []
        check_loss_envelopes(2300.0, 0.0, 0.0, [self._pos("p1", "NFLX", -10.0)],
                             EnvelopeConfig(), symbol_loss_stops_out=out)
        self.assertEqual(out, [])

    def test_check_all_envelopes_surfaces_it(self):
        result = check_all_envelopes(
            positions=[self._pos("p1", "NFLX", -200.0)],
            equity=2300.0, daily_pnl=0.0, weekly_pnl=0.0, config=EnvelopeConfig(),
        )
        self.assertEqual(len(result.symbol_loss_stops), 1)
        self.assertEqual(result.symbol_loss_stops[0]["symbol"], "NFLX")
        self.assertIn("symbol_loss_stops", result.to_dict())


# ── Monitor writer hook ─────────────────────────────────────────────────────

class TestMonitorWriter(unittest.TestCase):
    def _monitor(self, sb):
        from packages.quantum.jobs.handlers.intraday_risk_monitor import IntradayRiskMonitor
        m = IntradayRiskMonitor.__new__(IntradayRiskMonitor)
        m.supabase = sb
        return m

    def test_writes_cooldown_per_symbol_stop(self):
        os.environ.pop(rc.FLAG_ENV, None)  # default ON
        sb = _FakeSB()
        m = self._monitor(sb)
        result = types.SimpleNamespace(symbol_loss_stops=[
            {"cohort_id": LIVE, "symbol": "NFLX", "position_id": "p1",
             "realized_loss": -84.0},
        ])
        with patch.object(rc, "compute_cooldown_until", return_value=_future()):
            n = m._write_reentry_cooldowns(result, "u1")
        self.assertEqual(n, 1)
        self.assertEqual(sb.store["rows"][0]["symbol"], "NFLX")

    def test_flag_off_writes_nothing(self):
        sb = _FakeSB()
        m = self._monitor(sb)
        result = types.SimpleNamespace(symbol_loss_stops=[
            {"cohort_id": LIVE, "symbol": "NFLX", "position_id": "p1",
             "realized_loss": -84.0}])
        with patch.dict(os.environ, {rc.FLAG_ENV: "0"}):
            n = m._write_reentry_cooldowns(result, "u1")
        self.assertEqual(n, 0)
        self.assertEqual(sb.store["rows"], [])

    def test_no_stops_no_write(self):
        os.environ.pop(rc.FLAG_ENV, None)
        sb = _FakeSB()
        m = self._monitor(sb)
        result = types.SimpleNamespace(symbol_loss_stops=[])
        self.assertEqual(m._write_reentry_cooldowns(result, "u1"), 0)


# ── Reader integration (autopilot per-cohort) — source pins ─────────────────

class TestAutopilotGatesWired(unittest.TestCase):
    """The two reader gates live in _execute_per_cohort (the live re-entry
    path), authoritative stage gate fail-closed, and run BEFORE staging /
    independent of position_id (add-to-position not exempted)."""

    def _src(self):
        import inspect
        from packages.quantum.services.paper_autopilot_service import (
            PaperAutopilotService,
        )
        return inspect.getsource(PaperAutopilotService._execute_per_cohort)

    def test_filter_gate_present(self):
        src = self._src()
        self.assertIn("active_symbols(", src)        # filter gate
        self.assertIn("resolve_cohort_id(", src)     # cohort-keyed

    def test_stage_gate_present_and_typed(self):
        src = self._src()
        self.assertIn("is_active(", src)             # authoritative re-check
        self.assertIn("SymbolCooldownActive", src)   # typed rejection

    def test_stage_gate_fails_closed_on_query_error(self):
        src = self._src()
        # CooldownQueryError at the stage gate → raise (block), not pass.
        self.assertIn("CooldownQueryError", src)
        gate = src[src.index("STAGE gate"):]
        self.assertIn("raise rc.SymbolCooldownActive", gate)

    def test_stage_gate_runs_before_staging(self):
        src = self._src()
        self.assertLess(src.index("is_active("),
                        src.index("_stage_order_internal("))

    def test_position_id_not_used_to_exempt(self):
        # The cooldown gate keys on (cohort, ticker) only — never position_id
        # (an add-to-position MUST be blocked; the #1038 seam, deliberately not
        # repeated here). The gate block references ticker + cohort_id, not a
        # position_id exemption.
        src = self._src()
        gate = src[src.index("STAGE gate"):src.index("_stage_order_internal(")]
        self.assertNotIn("position_id is None", gate)


class TestMonitorWriterWired(unittest.TestCase):
    def test_monitor_calls_writer_after_force_close(self):
        import inspect
        from packages.quantum.jobs.handlers.intraday_risk_monitor import IntradayRiskMonitor
        src = inspect.getsource(IntradayRiskMonitor._check_user)
        self.assertIn("_write_reentry_cooldowns(", src)
        # writer keyed on the structured symbol_loss_stops, not the 5b loop
        wsrc = inspect.getsource(IntradayRiskMonitor._write_reentry_cooldowns)
        self.assertIn("symbol_loss_stops", wsrc)


if __name__ == "__main__":
    unittest.main()
