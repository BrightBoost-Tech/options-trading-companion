"""Behavioral tests for the phantom-mark-safe autopilot entry-halt breaker
(P2#6 — the deferred GATE-path sibling of the #1071 force-close fix).

Before this fix the circuit breaker in ``execute_top_suggestions`` fed
``check_all_envelopes`` a DOUBLE-phantom signal:
  - numerator  = ``tightened_daily_pnl`` = min(Σ DB unrealized_pl, broker
                 equity−last_equity) — both carry the Alpaca per-leg
                 last-trade phantom mark (the 06-17 class).
  - denominator = ``get_alpaca_equity`` (live, phantom-marked) — the same
                 bad mark depresses it and inflates the loss %.
A phantom of the 06-17 magnitude (broker −285 vs executable −15, ~−13-15%
of a ~$1.9-2.1k book) at the 11:30 CT executor would have BLOCKED the day's
single execution shot — strictly worse than a force-close (a blocked shot
has no retry).

The fix routes the breaker through the #1071 seam:
  daily_pnl = realized_pnl_since (DB-authoritative) + corroborated_unrealized
              (executable-side, excludes + flags the unpriceable, H9)
  equity    = get_alpaca_last_equity + daily_pnl   (de-phantomed denominator)
with a fail-SAFE fallback to the legacy ``tightened_daily_pnl`` /
``_estimate_equity`` when scope or the realized query is unavailable.

These tests drive the real ``execute_top_suggestions`` breaker path. The
``check_all_envelopes`` call is replaced with a shim that delegates the
daily/weekly DECISION to the real ``check_loss_envelopes`` (isolating the
loss feeder from greeks/concentration/stress) so the block/no-block verdict
flows from the real threshold math against the breaker's computed values.

The VALUE→decision proof (−15 on a clean denom is no breach; −300 is) lives
in test_equity_brake_corroboration.py (the #1071 seam). This module proves
the BREAKER computes and feeds those values (routing), translates passed
into block/no-block, and honours the fail-safe + uncorroborated posture.
"""
import contextlib
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# Stub alpaca-py per the repo convention (module import pulls equity_state,
# whose Alpaca client is imported lazily; the stub keeps collection clean).
_alpaca_pkg = types.ModuleType("alpaca")
_alpaca_trading = types.ModuleType("alpaca.trading")
_alpaca_trading_requests = types.ModuleType("alpaca.trading.requests")


class _StubPortfolioHistoryRequest:
    def __init__(self, period=None, timeframe=None, **_):
        self.period = period
        self.timeframe = timeframe


_alpaca_trading_requests.GetPortfolioHistoryRequest = _StubPortfolioHistoryRequest
sys.modules.setdefault("alpaca", _alpaca_pkg)
sys.modules.setdefault("alpaca.trading", _alpaca_trading)
sys.modules.setdefault("alpaca.trading.requests", _alpaca_trading_requests)

from packages.quantum.services.paper_autopilot_service import PaperAutopilotService
from packages.quantum.services import equity_state
from packages.quantum.risk.risk_envelope import check_loss_envelopes, EnvelopeConfig

# Returned by the patched _execute_per_cohort — proves the breaker PASSED
# (did not block) and control reached execution.
_EXECUTED_SENTINEL = {"status": "executed", "executed_count": 1, "_sentinel": True}

# A clean prior-session equity base; with a small daily P&L the % stays well
# clear of the −5% daily-loss limit, so only a real loss trips the brake.
_LAST_EQUITY = 2150.88


def _pos(pid, sym="MARA"):
    # Shape is irrelevant to the patched corroborated_unrealized; `id` is the
    # only field check_loss_envelopes needs (force_close_ids population).
    return {"id": pid, "symbol": sym}


def _fake_ops_module():
    m = types.ModuleType("packages.quantum.ops_endpoints")
    m.is_trading_paused = lambda: (False, None)
    return m


def _fake_staleness_module():
    m = types.ModuleType("packages.quantum.risk.staleness_gate")

    class _Stale:
        blocked = False
        reason = None
        age_seconds = 0
        stale_symbols = []

    m.check_staleness_gate = lambda: _Stale()
    return m


class _BreakerHarness:
    """Drive execute_top_suggestions to the breaker and capture its effects.

    The pre-breaker pause + staleness gates are stubbed open via sys.modules
    (avoids importing the heavy real modules). The post-breaker path is
    short-circuited by forcing the policy-lab branch and stubbing
    _execute_per_cohort to a sentinel — so a non-blocking breaker returns the
    sentinel and a blocking one returns its own block dict.
    """

    def __init__(
        self,
        *,
        positions,
        realized=None,                # realized_pnl_since() return
        corroborated=(0.0, []),       # corroborated_unrealized() return
        last_equity=_LAST_EQUITY,     # get_alpaca_last_equity() return
        legacy_daily=None,            # tightened_daily_pnl() return (fail-safe)
        legacy_equity=None,           # get_alpaca_equity() return (fail-safe)
        weekly=0.0,
        scope_ids=("port-1",),
        scope_raises=False,
    ):
        self.positions = positions
        self.realized = realized
        self.corroborated = corroborated
        self.last_equity = last_equity
        self.legacy_daily = legacy_daily
        self.legacy_equity = legacy_equity
        self.weekly = weekly
        self.scope_ids = scope_ids
        self.scope_raises = scope_raises
        self.captured = {}

    def _fake_check_all(self, positions, equity, daily_pnl, weekly_pnl, config,
                        observe_scope=None):
        # Record what the breaker actually fed the envelope, then delegate the
        # daily/weekly verdict to the REAL loss feeder against those values.
        # observe_scope is the OBSERVE-ONLY greek-cap-counterfactual dedup key
        # (mirrors the real signature); it never affects the brake verdict.
        self.captured["observe_scope"] = observe_scope
        self.captured["equity"] = equity
        self.captured["daily_pnl"] = daily_pnl
        self.captured["weekly_pnl"] = weekly_pnl
        cfg = config or EnvelopeConfig.from_env()
        viol, fci, _ = check_loss_envelopes(equity, daily_pnl, weekly_pnl, positions, cfg)
        res = MagicMock()
        res.violations = viol
        res.force_close_ids = fci
        res.sizing_multiplier = 1.0
        res.passed = not any(getattr(v, "severity", "") == "force_close" for v in viol)
        return res

    def run(self):
        svc = PaperAutopilotService.__new__(PaperAutopilotService)
        svc.client = MagicMock()
        svc.config = {"max_trades_per_day": 3, "min_score": 0.0}
        svc._get_open_positions_for_risk_check = MagicMock(return_value=self.positions)
        svc._execute_per_cohort = MagicMock(return_value=_EXECUTED_SENTINEL)

        if self.scope_raises:
            lr = MagicMock(side_effect=RuntimeError("scope down"))
        else:
            lr = MagicMock(return_value=list(self.scope_ids))

        alert_mock = MagicMock()

        with contextlib.ExitStack() as stk:
            stk.enter_context(patch.dict(sys.modules, {
                "packages.quantum.ops_endpoints": _fake_ops_module(),
                "packages.quantum.risk.staleness_gate": _fake_staleness_module(),
            }))
            stk.enter_context(patch(
                "packages.quantum.risk.risk_envelope.check_all_envelopes",
                side_effect=self._fake_check_all,
            ))
            stk.enter_context(patch(
                "packages.quantum.risk.position_scope.live_routed_portfolio_ids", lr,
            ))
            stk.enter_context(patch(
                "packages.quantum.policy_lab.config.is_policy_lab_enabled",
                return_value=True,
            ))
            stk.enter_context(patch.object(
                equity_state, "get_alpaca_weekly_pnl", return_value=self.weekly))
            m_realized = stk.enter_context(patch.object(
                equity_state, "realized_pnl_since", return_value=self.realized))
            m_corr = stk.enter_context(patch.object(
                equity_state, "corroborated_unrealized", return_value=self.corroborated))
            m_last = stk.enter_context(patch.object(
                equity_state, "get_alpaca_last_equity", return_value=self.last_equity))
            m_tight = stk.enter_context(patch.object(
                equity_state, "tightened_daily_pnl", return_value=self.legacy_daily))
            m_geq = stk.enter_context(patch.object(
                equity_state, "get_alpaca_equity", return_value=self.legacy_equity))
            stk.enter_context(patch(
                "packages.quantum.services.paper_autopilot_service.alert", alert_mock))
            stk.enter_context(patch(
                "packages.quantum.services.paper_autopilot_service._get_admin_supabase",
                MagicMock()))
            result = svc.execute_top_suggestions("user-x")

        return {
            "result": result,
            "captured": self.captured,
            "alert": alert_mock,
            "per_cohort": svc._execute_per_cohort,
            "realized_pnl_since": m_realized,
            "corroborated_unrealized": m_corr,
            "get_alpaca_last_equity": m_last,
            "tightened_daily_pnl": m_tight,
            "get_alpaca_equity": m_geq,
        }


def _blocked(result) -> bool:
    return isinstance(result, dict) and result.get("status") == "blocked"


class TestBreakerRoutesThroughCorroborated(unittest.TestCase):
    """The breaker feeds the corroborated daily_pnl + de-phantomed denominator,
    never the raw delta / phantom-marked equity."""

    def test_feeds_corroborated_value_not_raw_delta(self):
        out = _BreakerHarness(
            positions=[_pos("mara")],
            realized=0.0,
            corroborated=(-15.0, []),     # executable-side unrealized
            last_equity=_LAST_EQUITY,
            legacy_daily=-285.0,          # phantom legacy value — must NOT be used
            legacy_equity=1865.0,         # phantom legacy equity — must NOT be used
        ).run()

        # daily_pnl fed = realized(0) + corroborated(-15) = -15, NOT the -285 phantom.
        self.assertAlmostEqual(out["captured"]["daily_pnl"], -15.0, places=4)
        # equity fed = last_equity + daily_pnl = 2135.88, NOT 1865 (phantom live
        # equity) and NOT the raw 2150.88 last_equity.
        self.assertAlmostEqual(out["captured"]["equity"], _LAST_EQUITY - 15.0, places=4)
        # The legacy phantom-bearing helpers were not consulted on this path.
        out["tightened_daily_pnl"].assert_not_called()
        out["get_alpaca_equity"].assert_not_called()
        out["corroborated_unrealized"].assert_called_once()
        out["get_alpaca_last_equity"].assert_called_once()

    def test_realized_component_is_summed_in(self):
        out = _BreakerHarness(
            positions=[_pos("p", "SPY")],
            realized=-40.0,
            corroborated=(-15.0, []),
        ).run()
        # realized(-40) + corroborated(-15) = -55 fed to the brake.
        self.assertAlmostEqual(out["captured"]["daily_pnl"], -55.0, places=4)


class TestPhantomDoesNotFalseHalt(unittest.TestCase):
    """06-17 class: leg-skewed phantom reads ~-13-15%; the corroborated value
    is a benign ~-0.7% → the breaker must NOT block the day's execution shot."""

    def test_phantom_mark_no_false_halt(self):
        out = _BreakerHarness(
            positions=[_pos("mara")],
            realized=0.0,
            corroborated=(-15.0, []),     # executable −15 → −0.7% on clean denom
            last_equity=_LAST_EQUITY,
            legacy_daily=-285.0,          # the phantom that WOULD have read −15.3%
            legacy_equity=1865.0,
        ).run()
        # Not blocked → control reached _execute_per_cohort (the sentinel).
        self.assertFalse(_blocked(out["result"]))
        self.assertEqual(out["result"], _EXECUTED_SENTINEL)
        out["per_cohort"].assert_called_once()


class TestRealLossStillHalts(unittest.TestCase):
    """A genuine corroborated loss past −5% must still block — the fix must not
    blind the breaker to real drawdown (realized OR executable unrealized)."""

    def test_real_realized_loss_halts(self):
        out = _BreakerHarness(
            positions=[_pos("p", "SPY")],
            realized=-200.0,              # real realized loss (DB-authoritative)
            corroborated=(-15.0, []),     # plus a small executable unrealized
            last_equity=_LAST_EQUITY,
        ).run()
        # daily -215 on denom 1935.88 ≈ -11% < -5% → block.
        self.assertTrue(_blocked(out["result"]))
        self.assertEqual(out["result"]["reason"], "risk_envelope_breach")
        out["per_cohort"].assert_not_called()

    def test_real_executable_loss_halts(self):
        out = _BreakerHarness(
            positions=[_pos("p")],
            realized=0.0,
            corroborated=(-300.0, []),    # real executable drawdown, corroborated
            last_equity=_LAST_EQUITY,
        ).run()
        # daily -300 on denom 1850.88 ≈ -16% < -5% → block.
        self.assertTrue(_blocked(out["result"]))
        self.assertEqual(out["result"]["reason"], "risk_envelope_breach")


class TestFailSafeFallback(unittest.TestCase):
    """Scope-fail or realized None → fall back to the legacy broker-true brake
    (errs protective: it still halts on the legacy breach). NEVER pass
    realized=0.0 silently."""

    def test_scope_failure_falls_back_to_legacy_and_halts(self):
        out = _BreakerHarness(
            positions=[_pos("p")],
            scope_raises=True,            # live_routed_portfolio_ids raises
            legacy_daily=-285.0,          # legacy tightened value (breach)
            legacy_equity=1865.0,         # legacy phantom equity → -15.3%
        ).run()
        # Legacy path consulted; corroborated path NOT.
        out["tightened_daily_pnl"].assert_called_once()
        out["get_alpaca_equity"].assert_called_once()
        out["corroborated_unrealized"].assert_not_called()
        out["get_alpaca_last_equity"].assert_not_called()
        self.assertAlmostEqual(out["captured"]["daily_pnl"], -285.0, places=4)
        self.assertAlmostEqual(out["captured"]["equity"], 1865.0, places=4)
        # Still protective: legacy -285/1865 ≈ -15.3% → block.
        self.assertTrue(_blocked(out["result"]))

    def test_realized_none_falls_back_to_legacy_and_halts(self):
        out = _BreakerHarness(
            positions=[_pos("p")],
            realized=None,               # realized_pnl_since query failed
            scope_ids=("port-1",),       # scope itself OK
            legacy_daily=-285.0,
            legacy_equity=1865.0,
        ).run()
        out["tightened_daily_pnl"].assert_called_once()
        out["corroborated_unrealized"].assert_not_called()
        self.assertTrue(_blocked(out["result"]))


class TestUncorroboratedExcludedAndAlerted(unittest.TestCase):
    """A position whose executable side can't be priced is EXCLUDED from the
    brake total + flagged via daily_brake_unrealized_uncorroborated; the
    breaker gates on the corroborated-partial value (less negative → no false
    halt). #1048 per-position stops + the force-close monitor remain the
    real-loss backstop for the excluded leg."""

    def test_excluded_position_alerted_and_gates_on_partial(self):
        out = _BreakerHarness(
            positions=[_pos("a", "MARA"), _pos("b", "NFLX")],
            realized=0.0,
            # 'a' corroborated at -15; 'b' excluded (executable side dark).
            corroborated=(-15.0, [
                {"position_id": "b", "symbol": "NFLX", "reason": "quote_incomplete"},
            ]),
            last_equity=_LAST_EQUITY,
        ).run()

        # Gated on the partial (-15), not on a phantom for 'b'.
        self.assertAlmostEqual(out["captured"]["daily_pnl"], -15.0, places=4)
        self.assertFalse(_blocked(out["result"]))

        # Exactly one daily_brake_unrealized_uncorroborated alert, for 'b'.
        unc_calls = [
            c for c in out["alert"].call_args_list
            if c.kwargs.get("alert_type") == "daily_brake_unrealized_uncorroborated"
        ]
        self.assertEqual(len(unc_calls), 1)
        self.assertEqual(unc_calls[0].kwargs["metadata"]["position_id"], "b")
        self.assertEqual(unc_calls[0].kwargs["metadata"]["reason"], "quote_incomplete")
        self.assertEqual(unc_calls[0].kwargs["severity"], "warning")


if __name__ == "__main__":
    unittest.main()
