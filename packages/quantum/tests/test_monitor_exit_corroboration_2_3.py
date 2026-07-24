"""Per-position exit-trigger corroboration — monitor triggers 2+3 (#1035/#1036).

Extends #1079 (scheduled evaluate_exits) to the intraday_risk_monitor's two
per-position force-close triggers, via the SAME shared helper
(exit_mark_corroboration.corroborated_exit_upl) and the SAME corroborate-with-
raw-fallback design:
  2. loss_per_symbol force-close (risk_envelope.py:461) — THE capital one.
  3. cohort stop (#1048) — secondary, fresh-mid.

IntradayRiskMonitor._corroborate_exit_marks replaces unrealized_pl with the
executable-corroborated value (reusing this cycle's shared snapshot cache, no
extra fetch), and the corroborated positions feed check_all_envelopes (trigger
2) + the cohort-stop collector (trigger 3).

Both directions, on both triggers:
  - phantom false-loss mark + good corroborated mark → no wrong force-close.
  - real loss on an uncorroborable mark → force-close STILL fires.
Plus the hot-path regression: non-mutating, all other fields preserved, the
#1035 _mark_unpriceable skip intact.
"""
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

from packages.quantum.tests._alpaca_stub import ensure_alpaca as _ensure_alpaca

_ensure_alpaca()

from packages.quantum.jobs.handlers import intraday_risk_monitor as irm
from packages.quantum.risk.risk_envelope import check_loss_envelopes, EnvelopeConfig
from packages.quantum.services import paper_exit_evaluator as pxe

_EST = "packages.quantum.analytics.exit_mark_corroboration.executable_close_estimate"


def _est(impl, complete=True):
    return {"achievable_close": None, "achievable_implied_pl": impl,
            "quote_complete": complete, "legs_quotes": []}


def _pos(upl, pid="mara", **extra):
    # entry_cost=|mc|*100*|qty|=100 → cohort stop@sl=2.0 fires at upl<=-200 (credit)
    # / -100 (debit). loss_per_symbol@equity 2000 fires at upl<-60. So upl=-285
    # FIRES both; upl=-15 fires NEITHER.
    p = {"id": pid, "symbol": "MARA", "unrealized_pl": upl, "max_credit": 1.0,
         "quantity": 1, "portfolio_id": "pf1", "cohort_id": "c1",
         "sector": "Tech", "legs": []}
    p.update(extra)
    return p


def _mon():
    m = irm.IntradayRiskMonitor.__new__(irm.IntradayRiskMonitor)
    m.supabase = MagicMock()
    return m


# ── _corroborate_exit_marks: override + hot-path regression ──────────

class TestCorroborateExitMarks(unittest.TestCase):
    def test_overrides_corroborated_preserves_fields_non_mutating(self):
        p = _pos(-285.0, greeks={"delta": 0.3}, _mark_unpriceable=False)
        with patch(_EST, return_value=_est(-15.0)):
            out = _mon()._corroborate_exit_marks([p])
        assert out[0]["unrealized_pl"] == -15.0           # corroborated override
        assert out[0]["greeks"] == {"delta": 0.3}         # other fields preserved
        assert out[0]["portfolio_id"] == "pf1"
        assert out[0]["sector"] == "Tech"
        assert out[0]["cohort_id"] == "c1"
        assert p["unrealized_pl"] == -285.0               # NON-mutating

    def test_raw_fallback_on_error_preserved(self):
        p = _pos(-285.0)
        with patch(_EST, side_effect=RuntimeError("dark")):
            out = _mon()._corroborate_exit_marks([p])
        assert out[0]["unrealized_pl"] == -285.0          # raw fire-if-past

    def test_mark_unpriceable_flag_preserved(self):
        p = _pos(-285.0, _mark_unpriceable=True)
        with patch(_EST, return_value=_est(-15.0)):
            out = _mon()._corroborate_exit_marks([p])
        assert out[0]["_mark_unpriceable"] is True        # #1035 skip flag intact

    def test_empty_list(self):
        assert _mon()._corroborate_exit_marks([]) == []


# ── Trigger 2: loss_per_symbol force-close ──────────────────────────

class TestLossPerSymbolCorroborated(unittest.TestCase):
    def _check(self, positions, degraded_out=None):
        # equity 2000 → per-symbol limit = 2000 * 0.03 = $60; daily/weekly = 0.
        return check_loss_envelopes(
            2000.0, 0.0, 0.0, positions, EnvelopeConfig.from_env(),
            degraded_out=degraded_out,
        )

    def test_phantom_does_not_wrong_force_close(self):
        p = _pos(-285.0)  # raw would breach -60; executable -15 does not
        with patch(_EST, return_value=_est(-15.0)):
            corr = _mon()._corroborate_exit_marks([p])
        viol, fci, _ = self._check(corr)
        assert not any(v.envelope == "loss_per_symbol" for v in viol)
        assert fci == []
        # the wrong force-close we prevented — raw -285 WOULD have fired:
        v2, fci2, _ = self._check([p])
        assert any(v.envelope == "loss_per_symbol" for v in v2) and "mara" in fci2

    def test_real_loss_uncorroborable_still_force_closes(self):
        p = _pos(-285.0)
        with patch(_EST, side_effect=RuntimeError("dark")):
            corr = _mon()._corroborate_exit_marks([p])
        viol, fci, _ = self._check(corr)
        assert any(v.envelope == "loss_per_symbol" for v in viol)
        assert "mara" in fci

    def test_mark_unpriceable_still_skipped_not_force_closed(self):
        p = _pos(-285.0, _mark_unpriceable=True)
        with patch(_EST, return_value=_est(-15.0)):
            corr = _mon()._corroborate_exit_marks([p])
        deg = []
        viol, fci, _ = self._check(corr, degraded_out=deg)
        assert fci == []          # skipped (existing #1035 policy), not force-closed
        assert len(deg) == 1      # and loudly flagged degraded


# ── Trigger 3: cohort stop (lighter, fresh-mid) ─────────────────────

class TestCohortStopCorroborated(unittest.TestCase):
    def test_phantom_does_not_wrong_fire(self):
        p = _pos(-285.0)
        with patch(_EST, return_value=_est(-15.0)):
            corr = _mon()._corroborate_exit_marks([p])
        assert pxe._check_stop_loss(corr[0], sl_pct=2.0) is False
        assert pxe._check_stop_loss(p, sl_pct=2.0) is True   # prevented wrong-fire

    def test_real_loss_uncorroborable_still_fires(self):
        p = _pos(-285.0)
        with patch(_EST, side_effect=RuntimeError("dark")):
            corr = _mon()._corroborate_exit_marks([p])
        assert pxe._check_stop_loss(corr[0], sl_pct=2.0) is True


if __name__ == "__main__":
    unittest.main()
