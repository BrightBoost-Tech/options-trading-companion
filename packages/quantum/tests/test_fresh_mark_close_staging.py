"""Evaluate-fresh / execute-fresh close staging — regression tests.

The bug (2026-06-04): the 15-min intraday monitor decides KEEP/CLOSE on
fresh in-memory marks (_refresh_marks — never persisted), but
_close_position re-reads the DB row and stages the close limit from the
persisted current_mark (written only by the scheduled jobs at
13:15Z/20:00Z/20:30Z → up to ~6.5h stale). Decision-price and order-price
came from different observations:
  - PROFIT side (observed, BAC): fresh >= $3.19 triggered, close staged at
    the stale $3.03 → +$192 captured of >= $255 detected.
  - LOSS side (the dangerous one): on a falling position the stale mark is
    ABOVE market → the sell-to-close limit stages above market → rests →
    watchdog-cancels → re-detects → re-stages at the SAME stale mark →
    loops unfilled until the next persisting job. Protection failure.

The fix: _close_position gains exit_price_override (default None =
byte-identical legacy DB read for every other caller); _execute_force_close
passes the EXACT in-memory mark its decision used, guarded (finite, > 0 —
degraded refresh falls back to the DB read with a logged reason, never a
fabricated/third number). Part-B companion: _refresh_marks persists the
fresh marks (fail-soft) so DB current_mark is 15-min fresh for everyone.
"""

import importlib
import math
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

import pytest

from packages.quantum.services.paper_exit_evaluator import PaperExitEvaluator


@pytest.fixture(autouse=True)
def _evict_sys_modules_pollution():
    """Defense against cross-test sys.modules MagicMock pollution.

    Other test files (test_weekly_report_win_rate.py, test_outcome_logic.py,
    test_inbox_ranker_comprehensive.py, ...) replace real modules with
    MagicMocks at module level — session-wide. _close_position lazily
    imports TradeTicket from packages.quantum.models AT CALL TIME, so in
    full-suite order it would resolve the mock and every staged-ticket
    assertion here would see MagicMock attributes. Evict any mocked entry
    and re-import the real module before each test."""
    for name in (
        "packages.quantum.models",
        "packages.quantum.market_data",
        "packages.quantum.execution.transaction_cost_model",
    ):
        mod = sys.modules.get(name)
        if mod is not None and isinstance(mod, MagicMock):
            sys.modules.pop(name, None)
            importlib.import_module(name)
    yield

USER_ID = "user-1"
POS_ID = "pos-11111111-2222-3333-4444-555555555555"

STALE_DB_MARK = 3.03   # what the last persisting job wrote
FRESH_LOSS_MARK = 2.40  # market fell since persist (stop/envelope case)
FRESH_PROFIT_MARK = 3.20  # market rose since persist (the BAC case)


def _position(current_mark=STALE_DB_MARK):
    return {
        "id": POS_ID,
        "user_id": USER_ID,
        "symbol": "BAC",
        "status": "open",
        "quantity": 4.0,
        "avg_entry_price": 2.55,
        "current_mark": current_mark,
        "max_credit": 2.55,
        "portfolio_id": "port-1",
        "suggestion_id": None,
        "trace_id": None,
        "legs": [
            {"symbol": "O:BAC260626C00050000", "action": "buy", "type": "call",
             "strike": 50, "expiry": "2026-06-26", "quantity": 4},
            {"symbol": "O:BAC260626C00055000", "action": "sell", "type": "call",
             "strike": 55, "expiry": "2026-06-26", "quantity": 4},
        ],
    }


def _close_position_supabase(position):
    """Supabase mock for _close_position's reads: routing query (alpaca
    entry), position fetch (the STALE DB row), empty idempotency, order-row
    refetch for submit."""

    def table(name):
        t = MagicMock()
        if name == "paper_positions":
            t.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
                data=position
            )
        elif name == "paper_orders":
            def select_side(cols):
                chain = MagicMock()
                for m in ("eq", "in_", "order", "limit"):
                    getattr(chain, m).return_value = chain
                if cols == "id, alpaca_order_id":
                    # routing: position was opened via a broker order → ALPACA path
                    chain.execute.return_value = MagicMock(
                        data=[{"id": "entry-1", "alpaca_order_id": "alp-entry-1"}]
                    )
                elif cols == "*":
                    chain.single.return_value.execute.return_value = MagicMock(
                        data={"id": "close-1", "order_json": {}, "requested_price": 1.0}
                    )
                else:
                    # idempotency: no existing close orders
                    chain.execute.return_value = MagicMock(data=[])
                return chain

            t.select.side_effect = select_side
            t.update.return_value.eq.return_value.execute.return_value = MagicMock()
        return t

    sb = MagicMock()
    sb.table.side_effect = table
    return sb


def _run_close(position, exit_price_override=...):
    """Drive _close_position with all broker seams patched; return the
    staged ticket."""
    staged = {}

    def capture_stage(supabase, analytics, user_id, ticket, portfolio_id,
                      position_id=None, trace_id_override=None, **kw):
        staged["ticket"] = ticket
        return "close-order-1"

    sb = _close_position_supabase(position)
    evaluator = PaperExitEvaluator.__new__(PaperExitEvaluator)
    evaluator.client = sb

    kwargs = {}
    if exit_price_override is not ...:
        kwargs["exit_price_override"] = exit_price_override

    with patch("packages.quantum.paper_endpoints._stage_order_internal",
               side_effect=capture_stage), \
         patch("packages.quantum.paper_endpoints.get_analytics_service",
               return_value=MagicMock()), \
         patch("packages.quantum.brokers.execution_router.should_submit_to_broker",
               return_value=True), \
         patch("packages.quantum.brokers.alpaca_order_handler.submit_and_track",
               return_value={}), \
         patch("packages.quantum.brokers.alpaca_client.get_alpaca_client",
               return_value=MagicMock()):
        result = evaluator._close_position(
            user_id=USER_ID, position_id=POS_ID, reason="risk_envelope:test",
            **kwargs,
        )
    return staged["ticket"], result


class TestClosePositionOverride:
    def test_loss_side_legacy_stages_stale_db_mark(self):
        """BEFORE-fix behavior (and the byte-identical default): with no
        override, a loss-scenario close stages at the STALE DB mark ($3.03)
        even though the market is at $2.40 — an above-market sell limit
        that rests, watchdog-cancels, and never fills."""
        ticket, _ = _run_close(_position(current_mark=STALE_DB_MARK))
        assert ticket.limit_price == pytest.approx(STALE_DB_MARK)
        assert ticket.limit_price > FRESH_LOSS_MARK  # above market → no-fill loop

    def test_loss_side_override_stages_fresh_mark(self):
        """AFTER: the stop/envelope close stages at the decision's fresh
        mark — at market, fillable."""
        ticket, _ = _run_close(
            _position(current_mark=STALE_DB_MARK),
            exit_price_override=FRESH_LOSS_MARK,
        )
        assert ticket.limit_price == pytest.approx(FRESH_LOSS_MARK)

    def test_profit_side_override_stages_fresh_mark(self):
        """AFTER (the BAC shape): the target_profit close stages at the
        fresh mark, not the stale undercapturing one."""
        ticket, _ = _run_close(
            _position(current_mark=STALE_DB_MARK),
            exit_price_override=FRESH_PROFIT_MARK,
        )
        assert ticket.limit_price == pytest.approx(FRESH_PROFIT_MARK)

    def test_none_override_is_byte_identical_to_legacy(self):
        """Explicit None behaves exactly like the no-arg legacy call —
        what the scheduled evaluator and all other callers get."""
        t_default, _ = _run_close(_position())
        t_none, _ = _run_close(_position(), exit_price_override=None)
        assert t_default.limit_price == t_none.limit_price == pytest.approx(STALE_DB_MARK)

    def test_999_sign_convention_untouched(self):
        """The override feeds the same ticket fields — is_credit_close is
        still set for a long multi-leg close (the #999 boundary negates)."""
        ticket, _ = _run_close(_position(), exit_price_override=FRESH_PROFIT_MARK)
        assert ticket.is_credit_close is True
        assert ticket.time_in_force == "day"  # closes still DAY (#1021 untouched)


# ── The monitor seam: _execute_force_close passes the guarded fresh mark ────
def _force_close_supabase():
    def table(name):
        t = MagicMock()
        chain = MagicMock()
        for m in ("select", "eq", "in_", "order", "limit"):
            getattr(chain, m).return_value = chain
        chain.execute.return_value = MagicMock(data=[])
        t.select.return_value = chain
        return t

    sb = MagicMock()
    sb.table.side_effect = table
    return sb


def _run_force_close(fresh_mark, reason="per_symbol_loss"):
    from packages.quantum.jobs.handlers.intraday_risk_monitor import IntradayRiskMonitor

    monitor = IntradayRiskMonitor.__new__(IntradayRiskMonitor)
    monitor.supabase = _force_close_supabase()
    monitor._log_alert = MagicMock()

    position = _position()
    position["current_mark"] = fresh_mark  # the in-memory refreshed mark

    captured = {}

    class FakeEvaluator:
        def __init__(self, supabase):
            pass

        def _close_position(self, **kwargs):
            captured.update(kwargs)
            return {"order_id": "close-1", "routed_to": "alpaca"}

    with patch(
        "packages.quantum.services.paper_exit_evaluator.PaperExitEvaluator",
        FakeEvaluator,
    ):
        ok = monitor._execute_force_close(position, reason, USER_ID)
    return ok, captured


class TestForceClosePassthrough:
    def test_valid_fresh_mark_passed_through(self):
        ok, kwargs = _run_force_close(fresh_mark=2.40)
        assert ok is True
        assert kwargs["exit_price_override"] == pytest.approx(2.40)

    def test_degraded_marks_fall_back_to_db_read(self):
        """Invalid fresh marks (refresh degraded) → override None → the
        legacy DB read inside _close_position. Never a fabricated number."""
        for bad in (None, 0, -1.5, float("nan"), float("inf"), "garbage"):
            ok, kwargs = _run_force_close(fresh_mark=bad)
            assert ok is True, f"close must still run for mark={bad!r}"
            assert kwargs["exit_price_override"] is None, f"mark={bad!r}"


# ── Layer-1 exit mark-sanity gate: OBSERVE-ONLY at the call site ────────────
# The gate hook lives in _execute_force_close. These prove the exit is
# byte-identical whether the observe flag is on or off, that the gate only
# fires for the two mark-derived reasons, and that a gate exception can NEVER
# stop the close (the FAIL-SAFE invariant). The verdict-logic tests live in
# test_exit_mark_corroboration.py.
class TestExitMarkSanityCallSite:
    def _close_kwargs(self, reason, flag, gate_side_effect=None):
        captured = {}
        env = {"EXIT_MARK_SANITY_OBSERVE_ENABLED": flag} if flag is not None else {}
        observe_calls = []

        def _fake_observe(*a, **k):
            observe_calls.append(k)
            if gate_side_effect:
                raise gate_side_effect

        from packages.quantum.jobs.handlers.intraday_risk_monitor import IntradayRiskMonitor
        monitor = IntradayRiskMonitor.__new__(IntradayRiskMonitor)
        monitor.supabase = _force_close_supabase()
        monitor._log_alert = MagicMock()
        position = _position()
        position["current_mark"] = 2.40

        class FakeEvaluator:
            def __init__(self, supabase):
                pass

            def _close_position(self, **kwargs):
                captured.update(kwargs)
                return {"order_id": "close-1", "routed_to": "alpaca"}

        with patch.dict(os.environ, env, clear=False):
            if flag is None:
                os.environ.pop("EXIT_MARK_SANITY_OBSERVE_ENABLED", None)
            with patch(
                "packages.quantum.services.paper_exit_evaluator.PaperExitEvaluator",
                FakeEvaluator,
            ), patch(
                "packages.quantum.analytics.exit_mark_corroboration.observe_exit_mark",
                _fake_observe,
            ):
                ok = monitor._execute_force_close(position, reason, USER_ID)
        return ok, captured, observe_calls

    def test_flag_on_off_byte_identical_exit(self):
        """The staged close (exit_price_override) is identical on vs off."""
        _, off, off_calls = self._close_kwargs("intraday_target_profit", flag=None)
        _, on, on_calls = self._close_kwargs("intraday_target_profit", flag="1")
        assert off["exit_price_override"] == on["exit_price_override"] == pytest.approx(2.40)
        assert off["reason"] == on["reason"]  # same close routing
        assert len(off_calls) == 0 and len(on_calls) == 1  # only the observe differs

    def test_gate_fires_only_for_mark_derived_reasons(self):
        for reason, expect in [
            ("intraday_target_profit", 1),
            ("intraday_stop_loss", 1),
            ("intraday_expiration_day", 0),   # date-derived → not logged
            ("per_symbol_loss", 0),           # envelope (5b) → not logged here
        ]:
            ok, _, calls = self._close_kwargs(reason, flag="1")
            assert ok is True
            assert len(calls) == expect, reason

    def test_gate_exception_never_stops_the_exit(self):
        """FAIL-SAFE: inject a gate exception → the close STILL fires."""
        ok, kwargs, calls = self._close_kwargs(
            "intraday_target_profit", flag="1",
            gate_side_effect=RuntimeError("gate boom"),
        )
        assert ok is True
        assert kwargs["exit_price_override"] == pytest.approx(2.40)  # exit unchanged
        assert len(calls) == 1  # the gate was attempted and threw — exit survived


# ── Stage-2: EXIT_MARK_SANITY_ENFORCE_ENABLED at the call site ──────────────
# Stage-1's observe-only contract is deliberately superseded (06-12): under
# the enforce flag, a target_profit fire whose observation row says
# would_suppress=true is NOT staged. Every safety edge is pinned here:
# stop_loss untouchable, flag-off byte-identical, None/error rows fail-open.
class TestStage2Enforcement:
    def _run(self, reason, *, enforce, observe="1", gate_row=...):
        captured = {}
        alerts = []
        env = {"EXIT_MARK_SANITY_OBSERVE_ENABLED": observe or "",
               "EXIT_MARK_SANITY_ENFORCE_ENABLED": enforce or ""}

        def _fake_observe(*a, **k):
            return None if gate_row is ... else gate_row

        from packages.quantum.jobs.handlers.intraday_risk_monitor import IntradayRiskMonitor
        monitor = IntradayRiskMonitor.__new__(IntradayRiskMonitor)
        monitor.supabase = _force_close_supabase()
        monitor._log_alert = lambda **k: alerts.append(k)
        position = _position()
        position["current_mark"] = 2.40

        class FakeEvaluator:
            def __init__(self, supabase):
                pass

            def _close_position(self, **kwargs):
                captured.update(kwargs)
                return {"order_id": "close-1", "routed_to": "alpaca"}

        with patch.dict(os.environ, env, clear=False):
            with patch(
                "packages.quantum.services.paper_exit_evaluator.PaperExitEvaluator",
                FakeEvaluator,
            ), patch(
                "packages.quantum.analytics.exit_mark_corroboration.observe_exit_mark",
                _fake_observe,
            ):
                ok = monitor._execute_force_close(position, reason, USER_ID)
        return ok, captured, alerts

    _SUPPRESS_ROW = {
        "would_suppress": True, "suppress_reason": "divergence_exceeded",
        "triggering_mark": -0.65, "achievable_close": -7.60,
        "divergence_frac": 0.914,
    }

    def test_enforce_on_suppresses_target_profit(self):
        ok, captured, alerts = self._run(
            "intraday_target_profit", enforce="1", gate_row=self._SUPPRESS_ROW,
        )
        assert ok is False
        assert captured == {}  # _close_position never called
        assert any(a.get("alert_type") == "exit_tp_suppressed_phantom_mark"
                   for a in alerts)

    def test_stop_loss_never_suppressed_even_on_malicious_row(self):
        """Asymmetry guard #2: even a (contractually impossible) stop_loss
        row with would_suppress=true must not stop the protective close."""
        ok, captured, _ = self._run(
            "intraday_stop_loss", enforce="1", gate_row=self._SUPPRESS_ROW,
        )
        assert ok is True
        assert captured["exit_price_override"] == pytest.approx(2.40)

    def test_enforce_off_is_stage1_byte_identical(self):
        ok, captured, alerts = self._run(
            "intraday_target_profit", enforce="0", gate_row=self._SUPPRESS_ROW,
        )
        assert ok is True
        assert captured["exit_price_override"] == pytest.approx(2.40)
        assert not any(a.get("alert_type") == "exit_tp_suppressed_phantom_mark"
                       for a in alerts)

    def test_none_row_fails_open(self):
        """observe_exit_mark returns None (db write failed) → close proceeds."""
        ok, captured, _ = self._run(
            "intraday_target_profit", enforce="1", gate_row=None,
        )
        assert ok is True
        assert captured["exit_price_override"] == pytest.approx(2.40)

    def test_corroborated_allow_proceeds(self):
        ok, captured, _ = self._run(
            "intraday_target_profit", enforce="1",
            gate_row={"would_suppress": False,
                      "suppress_reason": "corroborated_allow"},
        )
        assert ok is True
        assert captured["exit_price_override"] == pytest.approx(2.40)

    def test_0612_1330z_phantom_end_to_end_suppresses(self):
        """The real 06-12 13:30:04Z QQQ condor fire, computed through the
        FIXED gate (price-normalized divergence) and fed to the enforcing
        call site: triggering mark −0.65 (+$96 implied) vs achievable −7.60
        (−$599) on the degenerate C750 book (bid 0.76 / ask 14.09). The
        verdict must be divergence_exceeded and the close must NOT stage."""
        from packages.quantum.analytics import exit_mark_corroboration as emc
        legs = [
            {"symbol": "O:QQQ260710P00645000", "action": "sell", "strike": 645.0, "quantity": 1},
            {"symbol": "O:QQQ260710P00640000", "action": "buy", "strike": 640.0, "quantity": 1},
            {"symbol": "O:QQQ260710C00750000", "action": "sell", "strike": 750.0, "quantity": 1},
            {"symbol": "O:QQQ260710C00755000", "action": "buy", "strike": 755.0, "quantity": 1},
        ]
        quotes = {
            "O:QQQ260710P00645000": {"bid": 4.26, "ask": 4.33, "last": 4.35},
            "O:QQQ260710P00640000": {"bid": 3.70, "ask": 3.90, "last": 3.91},
            "O:QQQ260710C00750000": {"bid": 0.76, "ask": 14.09, "last": 8.79},
            "O:QQQ260710C00755000": {"bid": 7.12, "ask": 7.42, "last": 7.57},
        }
        verdict = emc.compute_corroboration(
            exit_type="target_profit", triggering_mark=-0.65,
            triggering_implied_pl=96.0, quantity=-1.0, avg_entry_price=1.61,
            legs=legs, leg_quotes=quotes,
        )
        assert verdict["would_suppress"] is True
        assert verdict["suppress_reason"] == "divergence_exceeded"
        assert verdict["achievable_close"] == pytest.approx(-7.60, abs=0.01)
        assert abs(verdict["divergence_frac"]) > 0.10  # decisively past tolerance

        ok, captured, alerts = self._run(
            "intraday_target_profit", enforce="1", gate_row=verdict,
        )
        assert ok is False
        assert captured == {}
        assert any(a.get("alert_type") == "exit_tp_suppressed_phantom_mark"
                   for a in alerts)


# ── Part B: the monitor persists its fresh marks (fail-soft) ───────────────
def _refresh_supabase(capture_updates, fail=False):
    def table(name):
        t = MagicMock()
        if name == "paper_positions":
            def capture(payload):
                if fail:
                    raise RuntimeError("db down")
                capture_updates.append(payload)
                up = MagicMock()
                up.eq.return_value.execute.return_value = MagicMock()
                return up

            t.update.side_effect = capture
        return t

    sb = MagicMock()
    sb.table.side_effect = table
    return sb


def _run_refresh(fail_persist=False):
    from packages.quantum.jobs.handlers.intraday_risk_monitor import IntradayRiskMonitor
    from packages.quantum.services.cache_key_builder import normalize_symbol

    updates = []
    monitor = IntradayRiskMonitor.__new__(IntradayRiskMonitor)
    monitor.supabase = _refresh_supabase(updates, fail=fail_persist)
    monitor._log_alert = MagicMock()

    # Leg-less position → the simple mid path (same persist machinery).
    pos = {
        "id": POS_ID, "user_id": USER_ID, "symbol": "BAC",
        "quantity": 4.0, "avg_entry_price": 2.55,
        "current_mark": STALE_DB_MARK, "unrealized_pl": 192.0, "legs": [],
    }
    snapshots = {normalize_symbol("BAC"): {"quote": {"bid": 3.18, "ask": 3.22}}}

    with patch(
        "packages.quantum.services.market_data_truth_layer.MarketDataTruthLayer"
    ) as TL:
        TL.return_value.snapshot_many.return_value = snapshots
        out = monitor._refresh_marks([pos])
    return out, updates


class TestPartBPersist(unittest.TestCase):
    def test_fresh_marks_persisted(self):
        out, updates = _run_refresh()
        # In-memory refresh happened (mid 3.20)
        self.assertAlmostEqual(out[0]["current_mark"], 3.20, places=2)
        # ...and was persisted
        self.assertEqual(len(updates), 1)
        self.assertAlmostEqual(updates[0]["current_mark"], 3.20, places=2)
        self.assertIn("unrealized_pl", updates[0])

    def test_persist_failure_is_fail_soft(self):
        """A write failure must not break the eval — fresh in-memory marks
        still returned."""
        out, updates = _run_refresh(fail_persist=True)
        self.assertAlmostEqual(out[0]["current_mark"], 3.20, places=2)
        self.assertEqual(updates, [])  # nothing captured; no exception raised


# ── Composition: #1017 shadow realism on top of the fresh base ─────────────
class TestShadowRealismComposition:
    def test_1017_adjusts_fill_not_requested_price(self):
        """After the fix, requested_price = the fresh mark; #1017 still
        adjusts the FILL RESULT (adverse of mid) and never mutates
        requested_price — no double-count, base and adjustment compose."""
        from packages.quantum.execution.transaction_cost_model import TransactionCostModel

        order = {
            "id": "close-1",
            "requested_qty": 4,
            "filled_qty": 0,
            "order_type": "limit",
            "requested_price": FRESH_LOSS_MARK,  # the fresh base from this fix
            "side": "sell",
            "order_json": {"legs": [{"symbol": "A"}, {"symbol": "B"}]},
            "tcm": {"expected_fill_price": FRESH_LOSS_MARK,
                    "expected_spread_cost_usd": 8.0},  # 8/(4*100)=0.02/share
        }
        result = TransactionCostModel.simulate_fill(order, quote=None)
        assert result["avg_fill_price"] == pytest.approx(FRESH_LOSS_MARK - 0.02)
        assert order["requested_price"] == pytest.approx(FRESH_LOSS_MARK)  # unmutated


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
