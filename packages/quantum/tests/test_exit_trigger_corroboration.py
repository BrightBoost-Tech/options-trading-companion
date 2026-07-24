"""Per-position exit-trigger corroboration (#1035/#1036).

#1071 (force-close brake) and #1075 (entry breaker) moved to the executable-
corroborated basis, but the per-position EXIT triggers — the ones that actually
fire the close — still read the raw persisted `unrealized_pl`, which on an
incomplete-leg-quote window is a leg-skew phantom (06-17 MARA: raw −285 vs
executable −15). This wires the scheduled `evaluate_exits` stop/TP onto the
corroborated mark, with a RAW fail-safe.

THE FAIL-SAFE (both directions, explicitly):
  - Phantom false-loss mark + a good corroborated mark → the stop does NOT
    wrong-fire (we'd have wrong-closed on the −285 phantom).
  - Real loss on an UNCORROBORABLE mark → the stop STILL fires (the fallback
    is raw + fire-if-past, NEVER a suppressor; worst case = today's behavior).
"""
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# Stub alpaca-py per the repo convention (paper_exit_evaluator pulls market-data
# deps transitively).
from packages.quantum.tests._alpaca_stub import ensure_alpaca as _ensure_alpaca

_ensure_alpaca()

from packages.quantum.analytics import exit_mark_corroboration as emc
from packages.quantum.services import paper_exit_evaluator as pxe

_EST = "packages.quantum.analytics.exit_mark_corroboration.executable_close_estimate"
_MTL = "packages.quantum.services.market_data_truth_layer.MarketDataTruthLayer"


def _pos(upl, mc=1.0, qty=1, pid="mara"):
    # entry_cost = |mc|*100*|qty| = 100 → credit stop@sl=2.0 trips at upl<=-200;
    # debit stop@min(2.0,1.0) trips at upl<=-100. So upl=-285 FIRES either way,
    # upl=-15 fires NEITHER — robust to _is_debit_spread.
    return {"id": pid, "symbol": "MARA", "max_credit": mc, "quantity": qty,
            "unrealized_pl": upl, "legs": []}


def _est(impl, complete=True):
    return {"achievable_close": None, "achievable_implied_pl": impl,
            "quote_complete": complete, "legs_quotes": []}


# ── corroborated_exit_upl: basis selection + raw preservation ────────

class TestCorroboratedExitUpl(unittest.TestCase):
    def test_corroborated_uses_executable_value(self):
        with patch(_EST, return_value=_est(-15.0)):
            assert emc.corroborated_exit_upl({"unrealized_pl": -285.0}) == (-15.0, "corroborated")

    def test_incomplete_quote_falls_back_to_raw(self):
        with patch(_EST, return_value=_est(None, complete=False)):
            assert emc.corroborated_exit_upl({"unrealized_pl": -285.0}) == (-285.0, "raw_fallback")

    def test_fetch_error_falls_back_to_raw(self):
        with patch(_EST, side_effect=RuntimeError("dark quotes")):
            assert emc.corroborated_exit_upl({"unrealized_pl": -285.0}) == (-285.0, "raw_fallback_error")

    def test_none_unrealized_pl_is_zero_not_crash(self):
        with patch(_EST, side_effect=RuntimeError):
            assert emc.corroborated_exit_upl({"unrealized_pl": None}) == (0.0, "raw_fallback_error")

    def test_never_raises_even_on_garbage(self):
        with patch(_EST, side_effect=RuntimeError):
            upl, basis = emc.corroborated_exit_upl({"unrealized_pl": "not-a-number"})
        assert upl == 0.0 and basis == "raw_fallback_error"


# ── The fail-safe, both directions, at the stop decision ────────────

class TestStopDecisionFailSafe(unittest.TestCase):
    def test_phantom_mark_does_not_wrong_fire_the_stop(self):
        """Raw −285 phantom WOULD fire; executable −15 → corroborated → no fire."""
        pos = _pos(upl=-285.0)
        with patch(_EST, return_value=_est(-15.0)):
            upl, basis = emc.corroborated_exit_upl(pos)
        assert basis == "corroborated" and upl == -15.0
        # Decision on the corroborated value: stop does NOT fire.
        assert pxe._check_stop_loss({**pos, "unrealized_pl": upl}, sl_pct=2.0) is False
        # The wrong-fire we prevented — the raw −285 would have fired.
        assert pxe._check_stop_loss(pos, sl_pct=2.0) is True

    def test_real_loss_on_uncorroborable_mark_still_fires(self):
        """The test that proves the fallback didn't become a stop-suppressor."""
        pos = _pos(upl=-285.0)
        with patch(_EST, side_effect=RuntimeError("dark quotes")):
            upl, basis = emc.corroborated_exit_upl(pos)
        assert basis == "raw_fallback_error" and upl == -285.0
        assert pxe._check_stop_loss({**pos, "unrealized_pl": upl}, sl_pct=2.0) is True

    def test_incomplete_quote_real_loss_still_fires(self):
        pos = _pos(upl=-285.0)
        with patch(_EST, return_value=_est(None, complete=False)):
            upl, basis = emc.corroborated_exit_upl(pos)
        assert basis == "raw_fallback" and upl == -285.0
        assert pxe._check_stop_loss({**pos, "unrealized_pl": upl}, sl_pct=2.0) is True


# ── The evaluate_exits batch wiring (non-mutating override) ──────────

class TestCorroboratePositionsForExit(unittest.TestCase):
    def _svc(self):
        svc = pxe.PaperExitEvaluator.__new__(pxe.PaperExitEvaluator)
        svc.client = MagicMock()
        return svc

    def test_overrides_corroborated_and_falls_back_per_position(self):
        a = _pos(upl=-285.0, pid="a")  # corroborates to -15
        b = _pos(upl=-50.0, pid="b")   # uncorroborable -> raw -50

        def _side(p, snapshot_fn=None):
            if p.get("id") == "a":
                return _est(-15.0)
            raise RuntimeError("dark")

        with patch(_MTL) as M, patch(_EST, side_effect=_side):
            M.return_value.snapshot_many = MagicMock()
            out = self._svc()._corroborate_positions_for_exit([a, b])

        assert out[0]["unrealized_pl"] == -15.0   # corroborated
        assert out[1]["unrealized_pl"] == -50.0   # raw fallback (fire-if-past)
        # Inputs not mutated (decision uses copies).
        assert a["unrealized_pl"] == -285.0 and b["unrealized_pl"] == -50.0

    def test_empty_list(self):
        assert self._svc()._corroborate_positions_for_exit([]) == []


if __name__ == "__main__":
    unittest.main()
