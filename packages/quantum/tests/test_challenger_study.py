"""Tests for the ⑤ offline challenger-vs-baseline study runner
(``scripts/analytics/challenger_study.py``).

The runner is OBSERVE-ONLY glue over the merged terminal-distribution
foundation. These tests pin, with SYNTHETIC fixtures only (NO live DB):

1. OCC-symbol parsing (call/put, strike scaling, expiry) + explicit raise.
2. DTE bucketing boundaries.
3. db-row -> foundation-row transform (strategy map, leg orientation, DTE
   derivation, spot intentionally None, win := pnl>0, corrected pass-through,
   exact geometry bounds).
4. COHORT SEPARATION: live and shadow are split by is_paper and shadow
   magnitudes NEVER leak into the live metrics.
5. Metric computation: hand-computed Brier / EV-RMSE / realized-net through the
   real foundation evaluator.
6. The frozen adapter and the lognormal challenger ABSTAIN on the
   IV/spot/delta-less historical shape (missing_delta / missing_spot),
   coverage 0, head-to-head joint set empty (charter falsifier unadjudicable).
7. Baseline abstains (H9) when a stored prediction is missing — never invents.
8. Determinism: identical inputs -> identical study.
9. render_markdown smoke: both cohorts present, no crash.
"""

import math

import pytest

from scripts.analytics.challenger_study import (
    build_study,
    dte_bucket,
    parse_occ,
    render_markdown,
    to_foundation_row,
    _geometry_bounds,
)


# --- fixtures ---------------------------------------------------------------
def _debit_row(record_id, is_paper, pop, ev, pnl, known_at="2026-03-19T15:19:13Z",
               regime="normal", corrected=False, strat="LONG_CALL_DEBIT_SPREAD",
               legs=None, net_premium=4.55, contracts=1):
    return {
        "record_id": record_id,
        "is_paper": is_paper,
        "strategy": strat,
        "regime": regime,
        "known_at": known_at,
        "realized_pnl": pnl,
        "pop_pred": pop,
        "ev_pred": ev,
        "net_premium": net_premium,
        "contracts": contracts,
        "corrected": corrected,
        "legs": legs or [
            {"side": "buy", "symbol": "O:XYZ260417C00090000", "quantity": contracts},
            {"side": "sell", "symbol": "O:XYZ260417C00100000", "quantity": contracts},
        ],
    }


def _condor_row(record_id, is_paper, pop, ev, pnl):
    return {
        "record_id": record_id, "is_paper": is_paper, "strategy": "IRON_CONDOR",
        "regime": "chop", "known_at": "2026-02-11T15:53:47Z",
        "realized_pnl": pnl, "pop_pred": pop, "ev_pred": ev,
        "net_premium": 1.52, "contracts": 5, "corrected": False,
        "legs": [
            {"side": "sell", "symbol": "O:AMD260313P00180000", "quantity": 5},
            {"side": "buy", "symbol": "O:AMD260313P00175000", "quantity": 5},
            {"side": "sell", "symbol": "O:AMD260313C00255000", "quantity": 5},
            {"side": "buy", "symbol": "O:AMD260313C00260000", "quantity": 5},
        ],
    }


# 2 live + 2 shadow; shadow s1 carries a huge (fictional) win, s2 has no stored pop.
MINI_PAYLOAD = {
    "generated_at": "2026-07-18",
    "source": "synthetic",
    "census_fingerprint": "deadbeef",
    "rows": [
        _debit_row("r1", False, 0.6, 50.0, 40.0),
        _debit_row("r2", False, 0.4, 30.0, -60.0, known_at="2026-03-20T15:19:13Z"),
        _condor_row("s1", True, 0.7, 100.0, 5000.0),  # fictional shadow magnitude
        _debit_row("s2", True, None, 80.0, 200.0, corrected=True),  # no stored pop
    ],
}


# --- 1. OCC parsing ---------------------------------------------------------
class TestParseOcc:
    def test_call_and_put(self):
        assert parse_occ("O:AMD260313C00255000") == ("call", 255.0, __import__("datetime").date(2026, 3, 13))
        assert parse_occ("O:AMD260313P00180000")[0] == "put"

    def test_fractional_strike(self):
        assert parse_occ("O:PYPL260515C00047500")[1] == 47.5

    def test_no_prefix_ok(self):
        assert parse_occ("SOFI260821C00018000")[1] == 18.0

    def test_malformed_raises(self):
        with pytest.raises(ValueError):
            parse_occ("O:BADSYM")
        with pytest.raises(ValueError):
            parse_occ("O:AMD260313X00255000")  # X is not C/P


# --- 2. DTE bucket ----------------------------------------------------------
class TestDteBucket:
    @pytest.mark.parametrize("dte,bucket", [
        (0, "0-14"), (14, "0-14"), (15, "15-30"), (30, "15-30"),
        (31, "31-45"), (45, "31-45"), (46, "46+"), (200, "46+"), (None, "unknown"),
    ])
    def test_edges(self, dte, bucket):
        assert dte_bucket(dte) == bucket


# --- 3. transform -----------------------------------------------------------
class TestToFoundationRow:
    def test_debit_mapping_and_geometry(self):
        frow, preds = to_foundation_row(_debit_row("r1", False, 0.6, 50.0, 40.0))
        assert frow["strategy"] == "debit_vertical"
        assert frow["spot"] is None                       # NOT persisted (H9)
        assert frow["dte_days"] == 29.0                    # 2026-04-17 - 2026-03-19
        assert frow["dte_bucket"] == "15-30"
        assert frow["realized_win"] is True                # 40 > 0
        assert {l["option_type"] for l in frow["legs"]} == {"call"}
        assert sorted(l["strike"] for l in frow["legs"]) == [90.0, 100.0]
        pop, ev, mg, ml = preds
        assert (pop, ev) == (0.6, 50.0)
        # debit: max_loss = premium*100*contracts; max_gain=(width-premium)*100
        assert ml == pytest.approx(455.0)
        assert mg == pytest.approx((10 - 4.55) * 100.0)

    def test_condor_geometry_and_win_rule(self):
        frow, preds = to_foundation_row(_condor_row("s1", True, 0.7, 100.0, -1.0))
        assert frow["strategy"] == "iron_condor"
        assert frow["realized_win"] is False               # -1 not > 0
        _, _, mg, ml = preds
        # credit 1.52, min side width 5 -> max_gain=1.52*100*5; max_loss=(5-1.52)*100*5
        assert mg == pytest.approx(1.52 * 100 * 5)
        assert ml == pytest.approx((5 - 1.52) * 100 * 5)

    def test_unmapped_strategy_raises(self):
        with pytest.raises(ValueError):
            to_foundation_row(_debit_row("x", False, 0.5, 1.0, 1.0, strat="CALENDAR"))

    def test_geometry_helper_direct(self):
        assert _geometry_bounds("debit_vertical", [90.0, 100.0], 4.55, 1) == pytest.approx((545.0, 455.0))


# --- 4/5. cohort separation + hand-computed metrics -------------------------
class TestCohortSeparationAndMetrics:
    def _study(self):
        return build_study(MINI_PAYLOAD)

    def test_split_counts(self):
        study = self._study()
        assert study.total_rows == 4
        live = next(c for c in study.cohorts if c.cohort == "live")
        shadow = next(c for c in study.cohorts if c.cohort == "shadow")
        assert live.n_rows == 2 and shadow.n_rows == 2
        assert live.n_corrected == 0 and shadow.n_corrected == 1

    def test_live_baseline_metrics_hand_computed(self):
        live = next(c for c in self._study().cohorts if c.cohort == "live")
        b = live.baseline
        assert b.scored == 2 and b.abstained == 0
        # Brier = ((0.6-1)^2 + (0.4-0)^2)/2 = 0.16
        assert b.brier == pytest.approx(0.16, abs=1e-12)
        # EV-RMSE = sqrt(((50-40)^2 + (30-(-60))^2)/2) = sqrt(4100)
        assert b.ev_rmse == pytest.approx(math.sqrt(4100.0), abs=1e-9)
        assert b.realized_net == pytest.approx(-20.0)

    def test_shadow_magnitude_never_leaks_into_live(self):
        study = self._study()
        live = next(c for c in study.cohorts if c.cohort == "live")
        shadow = next(c for c in study.cohorts if c.cohort == "shadow")
        assert live.baseline.realized_net == pytest.approx(-20.0)   # not 5000
        assert shadow.baseline.realized_net == pytest.approx(5000.0)  # s1 only; s2 abstained

    def test_shadow_baseline_abstains_on_missing_pop(self):
        shadow = next(c for c in self._study().cohorts if c.cohort == "shadow")
        assert shadow.baseline.scored == 1
        assert shadow.baseline.abstained == 1
        reasons = [p.abstain_reason for p in shadow.baseline.predictions if not p.scored]
        assert reasons == ["missing_stored_prediction"]


# --- 6. adapter + challenger abstain (the core data-gap finding) ------------
class TestAdapterAndChallengerAbstain:
    def test_both_abstain_everywhere_and_h2h_empty(self):
        study = build_study(MINI_PAYLOAD)
        for c in study.cohorts:
            assert c.adapter.scored == 0 and c.adapter.coverage == 0.0
            assert c.challenger.scored == 0 and c.challenger.coverage == 0.0
            adapter_reasons = {p.abstain_reason for p in c.adapter.predictions}
            challenger_reasons = {p.abstain_reason for p in c.challenger.predictions}
            assert adapter_reasons == {"missing_delta"}
            assert challenger_reasons == {"missing_spot"}
            # charter falsifier cannot be adjudicated: no joint scored set
            assert c.h2h_baseline_challenger.n_joint == 0
            assert c.h2h_adapter_challenger.n_joint == 0


# --- 7/8. skips + determinism -----------------------------------------------
class TestSkipsAndDeterminism:
    def test_bad_occ_symbol_is_explicit_skip(self):
        payload = {
            "generated_at": "2026-07-18", "source": "synthetic",
            "rows": [_debit_row("bad", False, 0.5, 1.0, 1.0,
                                 legs=[{"side": "buy", "symbol": "O:BADSYM", "quantity": 1},
                                       {"side": "sell", "symbol": "O:XYZ260417C00100000", "quantity": 1}])],
        }
        live = next(c for c in build_study(payload).cohorts if c.cohort == "live")
        assert len(live.skipped) == 1
        assert live.baseline.scored == 0

    def test_determinism(self):
        assert build_study(MINI_PAYLOAD) == build_study(MINI_PAYLOAD)


# --- 9. render smoke --------------------------------------------------------
class TestRender:
    def test_markdown_has_both_cohorts(self):
        md = render_markdown(build_study(MINI_PAYLOAD))
        assert "Cohort: LIVE" in md and "Cohort: SHADOW" in md
        assert "missing_delta" in md and "missing_spot" in md
        assert "UNADJUDICABLE" in md
