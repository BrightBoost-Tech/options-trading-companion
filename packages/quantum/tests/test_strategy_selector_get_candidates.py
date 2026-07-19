# packages/quantum/tests/test_strategy_selector_get_candidates.py
"""Route-executes StrategySelector.get_candidates — the production
multi-strategy path (options_scanner MULTI_STRATEGY_EVAL=1 default).

Covers: (d) the emitted pool per sentiment x IV tier, (f) the
CURRENT_PROGRESSION_PHASE iron-condor gate.

Note: the former (g) banned-strategy filtering tests were removed with the
F-BAN phantom feature (per-strategy bans had no producer and were always fed
`[]`). The pool/phase assertions here double as the get_candidates
decision-equivalence anchor for that removal.
"""

import pytest

from packages.quantum.analytics.strategy_selector import StrategySelector


def _emit(selector, sentiment, iv_rank, regime="normal"):
    return [
        c["strategy"]
        for c in selector.get_candidates(
            ticker="TEST",
            sentiment=sentiment,
            current_price=100.0,
            iv_rank=iv_rank,
            effective_regime=regime,
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
