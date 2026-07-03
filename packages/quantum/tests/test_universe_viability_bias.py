"""Owner decision (b), 2026-07-03 — universe-viability ranking bias.

Pins: sort-key-only (stored risk_adjusted_ev byte-identical flag-on vs
flag-off — the allocator's split skew reads it); reorders candidacy toward
the recon-viable set among POSITIVE scores only; never a filter (below-floor
candidates stay -999 regardless); strict '=1' behavioral opt-in with a
WARNING on non-'1' values; flag-off ordering byte-identical to legacy.
"""

import copy
import logging
from unittest.mock import patch

from packages.quantum.analytics import canonical_ranker as cr


def _sugg(ticker, ev=40.0, cost_basis=200.0):
    return {
        "ticker": ticker, "ev": ev,
        "sizing_metadata": {"cost_basis": cost_basis},
        "probability_of_profit": 0.6,
    }


def _rank(suggs):
    return cr.rank_suggestions_canonical(
        suggs, existing_positions=[], portfolio_budget=800.0
    )


class TestBiasOrdering:
    def test_viable_outranks_equal_score_nonviable(self, monkeypatch):
        monkeypatch.setenv("UNIVERSE_VIABILITY_BIAS_ENABLED", "1")
        suggs = _rank([_sugg("BAC"), _sugg("SPY")])  # identical inputs
        assert suggs[0]["ticker"] == "SPY"

    def test_marginal_tier_between_clears_and_rest(self, monkeypatch):
        monkeypatch.setenv("UNIVERSE_VIABILITY_BIAS_ENABLED", "1")
        suggs = _rank([_sugg("BAC"), _sugg("QQQ"), _sugg("SPY")])
        assert [s["ticker"] for s in suggs] == ["SPY", "QQQ", "BAC"]

    def test_bias_cannot_resurrect_below_floor(self, monkeypatch):
        # A viable-set candidate below MIN_EDGE_AFTER_COSTS keeps -999 and
        # ranks LAST — the bias is not a filter and not a rescue.
        monkeypatch.setenv("UNIVERSE_VIABILITY_BIAS_ENABLED", "1")
        suggs = _rank([_sugg("SPY", ev=5.0), _sugg("BAC", ev=40.0)])
        assert suggs[0]["ticker"] == "BAC"
        assert suggs[1]["risk_adjusted_ev"] == -999

    def test_negative_scores_not_boosted(self, monkeypatch):
        monkeypatch.setenv("UNIVERSE_VIABILITY_BIAS_ENABLED", "1")
        # Both below floor → both -999 → stable order preserved (no bias
        # applied to non-positive keys; a boost would flip nothing anyway,
        # pinned via the key function directly).
        assert cr._viability_rank_key({"ticker": "SPY", "risk_adjusted_ev": -10.0}) == -10.0


class TestSortKeyOnlyNeverMutates:
    def test_stored_scores_byte_identical_flag_on_vs_off(self, monkeypatch):
        base = [_sugg("SPY"), _sugg("QQQ"), _sugg("BAC")]

        monkeypatch.delenv("UNIVERSE_VIABILITY_BIAS_ENABLED", raising=False)
        off = _rank(copy.deepcopy(base))
        monkeypatch.setenv("UNIVERSE_VIABILITY_BIAS_ENABLED", "1")
        on = _rank(copy.deepcopy(base))

        off_scores = {s["ticker"]: s["risk_adjusted_ev"] for s in off}
        on_scores = {s["ticker"]: s["risk_adjusted_ev"] for s in on}
        assert off_scores == on_scores  # allocator sees identical inputs

    def test_ev_field_untouched_gate_inputs_preserved(self, monkeypatch):
        # The stage-seam round-trip gate reads suggestion EV — ranking must
        # never rewrite it (a biased candidate still dies there on merit).
        monkeypatch.setenv("UNIVERSE_VIABILITY_BIAS_ENABLED", "1")
        suggs = _rank([_sugg("SPY", ev=30.25)])
        assert suggs[0]["ev"] == 30.25


class TestFlagPolarity:
    def test_absent_is_legacy(self, monkeypatch):
        monkeypatch.delenv("UNIVERSE_VIABILITY_BIAS_ENABLED", raising=False)
        assert cr._viability_bias_enabled() is False

    def test_exactly_one_enables(self, monkeypatch):
        monkeypatch.setenv("UNIVERSE_VIABILITY_BIAS_ENABLED", "1")
        assert cr._viability_bias_enabled() is True

    def test_lenient_truthy_stays_off_with_warning(self, monkeypatch, caplog):
        monkeypatch.setenv("UNIVERSE_VIABILITY_BIAS_ENABLED", "true")
        cr._viability_flag_warned = False
        with caplog.at_level(logging.WARNING):
            assert cr._viability_bias_enabled() is False
        assert any("not '1'" in r.getMessage() for r in caplog.records)

    def test_flag_off_ordering_byte_identical_to_legacy(self, monkeypatch):
        monkeypatch.delenv("UNIVERSE_VIABILITY_BIAS_ENABLED", raising=False)
        # A mix the bias WOULD reorder: equal scores, viable listed second.
        suggs = _rank([_sugg("BAC"), _sugg("SPY")])
        # Legacy: equal keys → stable sort → insertion order preserved.
        assert [s["ticker"] for s in suggs] == ["BAC", "SPY"]
