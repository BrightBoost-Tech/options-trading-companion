# packages/quantum/tests/test_strategy_selector_get_candidates.py
"""Route-executes StrategySelector.get_candidates — the production
multi-strategy path (options_scanner MULTI_STRATEGY_EVAL=1 default) that
previously had ZERO test coverage (test_strategy_policy.py drives only the
legacy determine_strategy).

Covers: (d) the emitted pool per sentiment x IV tier, (f) the
CURRENT_PROGRESSION_PHASE iron-condor gate, (g) banned-strategy filtering
with no fallback bypass.
"""

import pytest

from packages.quantum.analytics.strategy_selector import StrategySelector


def _emit(selector, sentiment, iv_rank, regime="normal", banned=None):
    return [
        c["strategy"]
        for c in selector.get_candidates(
            ticker="TEST",
            sentiment=sentiment,
            current_price=100.0,
            iv_rank=iv_rank,
            effective_regime=regime,
            banned_strategies=banned,
        )
    ]


@pytest.fixture
def selector():
    return StrategySelector()


@pytest.fixture
def live_phase(monkeypatch):
    """Pin a non-paper phase so the IC gate doesn't mask pool assertions.
    monkeypatch restores the env after each test."""
    monkeypatch.setenv("CURRENT_PROGRESSION_PHASE", "micro_live")


# ---------------------------------------------------------------------------
# (d) Documented pool per sentiment x IV tier (effective_regime pinned to
#     "normal" so the IV rank alone drives the low/normal/high branch;
#     cutoffs in get_candidates: <30 low, >50 high).
# ---------------------------------------------------------------------------

POOL_MATRIX = [
    ("BULLISH", 10.0, ["LONG_CALL_DEBIT_SPREAD"]),
    ("BULLISH", 40.0, ["LONG_CALL_DEBIT_SPREAD", "SHORT_PUT_CREDIT_SPREAD"]),
    ("BULLISH", 70.0, ["SHORT_PUT_CREDIT_SPREAD", "LONG_CALL_DEBIT_SPREAD"]),
    ("BEARISH", 10.0, ["LONG_PUT_DEBIT_SPREAD"]),
    ("BEARISH", 40.0, ["LONG_PUT_DEBIT_SPREAD", "SHORT_CALL_CREDIT_SPREAD"]),
    ("BEARISH", 70.0, ["SHORT_CALL_CREDIT_SPREAD", "LONG_PUT_DEBIT_SPREAD"]),
    ("NEUTRAL", 10.0, []),
    ("NEUTRAL", 40.0, []),
    ("NEUTRAL", 70.0, ["IRON_CONDOR"]),
]


@pytest.mark.parametrize("sentiment,iv_rank,expected", POOL_MATRIX)
def test_candidate_pool_matrix(selector, live_phase, sentiment, iv_rank, expected):
    emitted = _emit(selector, sentiment, iv_rank)
    assert emitted == expected  # order matters: candidates[0] is the primary


def test_shock_regime_emits_no_trades(selector, live_phase):
    for sentiment in ("BULLISH", "BEARISH", "NEUTRAL"):
        assert _emit(selector, sentiment, 70.0, regime="shock") == []


def test_chop_regime_emits_condor_for_neutral(selector, live_phase):
    assert _emit(selector, "NEUTRAL", 40.0, regime="chop") == ["IRON_CONDOR"]


# ---------------------------------------------------------------------------
# (f) Phase gate: identical inputs, only CURRENT_PROGRESSION_PHASE differs.
# ---------------------------------------------------------------------------

def test_phase_gate_excludes_condor_in_alpaca_paper(selector, monkeypatch):
    monkeypatch.setenv("CURRENT_PROGRESSION_PHASE", "alpaca_paper")
    assert "IRON_CONDOR" not in _emit(selector, "NEUTRAL", 70.0)


def test_phase_gate_default_unset_is_alpaca_paper(selector, monkeypatch):
    monkeypatch.delenv("CURRENT_PROGRESSION_PHASE", raising=False)
    assert "IRON_CONDOR" not in _emit(selector, "NEUTRAL", 70.0)


def test_phase_gate_admits_condor_in_micro_live(selector, monkeypatch):
    monkeypatch.setenv("CURRENT_PROGRESSION_PHASE", "micro_live")
    assert "IRON_CONDOR" in _emit(selector, "NEUTRAL", 70.0)


def test_phase_gate_only_affects_iron_condor(selector, monkeypatch):
    """The gate must not touch the directional pool."""
    monkeypatch.setenv("CURRENT_PROGRESSION_PHASE", "alpaca_paper")
    paper = _emit(selector, "BULLISH", 70.0)
    monkeypatch.setenv("CURRENT_PROGRESSION_PHASE", "micro_live")
    live = _emit(selector, "BULLISH", 70.0)
    assert paper == live == ["SHORT_PUT_CREDIT_SPREAD", "LONG_CALL_DEBIT_SPREAD"]


# ---------------------------------------------------------------------------
# (g) Banned-strategy filtering through get_candidates — and no fallback
#     path re-admits a banned ID.
# ---------------------------------------------------------------------------

def test_direct_ban_filters_credit_spread_debit_survives(selector, live_phase):
    emitted = _emit(
        selector, "BULLISH", 70.0, banned=["SHORT_PUT_CREDIT_SPREAD"]
    )
    assert "SHORT_PUT_CREDIT_SPREAD" not in emitted
    # Existing behavior: the debit alternative already in the pool remains.
    assert emitted == ["LONG_CALL_DEBIT_SPREAD"]


def test_category_ban_credit_spreads_filters_all_credit(selector, live_phase):
    for sentiment, survivor in (
        ("BULLISH", "LONG_CALL_DEBIT_SPREAD"),
        ("BEARISH", "LONG_PUT_DEBIT_SPREAD"),
    ):
        emitted = _emit(selector, sentiment, 70.0, banned=["credit_spreads"])
        assert emitted == [survivor]

    # Neutral high-IV pool is condor-only; a category credit ban leaves nothing.
    assert _emit(selector, "NEUTRAL", 70.0, banned=["credit_spreads"]) == []


def test_condor_ban_yields_empty_not_substitute(selector, live_phase):
    assert _emit(selector, "NEUTRAL", 70.0, banned=["IRON_CONDOR"]) == []


def test_no_fallback_bypasses_ban_across_matrix(selector, live_phase):
    """For every sentiment x IV tier, a banned ID never appears in the
    emitted list — including via any fallback ordering."""
    banned_id = "SHORT_CALL_CREDIT_SPREAD"
    for sentiment in ("BULLISH", "BEARISH", "NEUTRAL", "EARNINGS"):
        for iv_rank in (10.0, 40.0, 70.0):
            emitted = _emit(selector, sentiment, iv_rank, banned=[banned_id])
            assert banned_id not in emitted
