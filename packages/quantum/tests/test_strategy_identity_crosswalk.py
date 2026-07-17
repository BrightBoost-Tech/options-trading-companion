# packages/quantum/tests/test_strategy_identity_crosswalk.py
"""Strategy-identity crosswalk: coverage lock + the LossMinimizer consumer.

Falsifiers:
- If StrategySelector.get_candidates ever emits an ID absent from the
  crosswalk, test_every_selector_emitted_id_resolves fails (drift lock —
  the selector route is driven for real, not a mirrored list).
- If LossMinimizer again demotes a debit vertical to a naked long,
  test_debit_spreads_do_not_classify_as_naked_longs fails.
"""

import itertools

from packages.quantum.analytics.loss_minimizer import LossMinimizer
from packages.quantum.analytics.strategy_identity import (
    NO_TRADE_IDS,
    TRADABLE_IDS,
    StructureClass,
    normalize_strategy_id,
    resolve_strategy_identity,
)
from packages.quantum.analytics.strategy_selector import StrategySelector
from packages.quantum.common_enums import StrategyType


# ---------------------------------------------------------------------------
# (a) Coverage lock: every ID the production selector can emit resolves in
#     the crosswalk to exactly one identity. Drives get_candidates itself so
#     the lock cannot drift from the selector (no second registry).
# ---------------------------------------------------------------------------

SENTIMENTS = ["BULLISH", "BEARISH", "NEUTRAL", "EARNINGS"]
IV_RANKS = [10.0, 40.0, 70.0]  # low / normal / high per get_candidates cutoffs
REGIMES = ["suppressed", "normal", "elevated", "shock", "rebound", "chop", None]


def _drive_selector_matrix(monkeypatch):
    """Route-drive get_candidates across the full input matrix; return the
    set of emitted strategy IDs."""
    # micro_live so the phase gate does not hide IRON_CONDOR from the
    # coverage sweep (the gate itself is tested separately).
    monkeypatch.setenv("CURRENT_PROGRESSION_PHASE", "micro_live")
    selector = StrategySelector()
    emitted = set()
    for sentiment, iv_rank, regime in itertools.product(
        SENTIMENTS, IV_RANKS, REGIMES
    ):
        candidates = selector.get_candidates(
            ticker="TEST",
            sentiment=sentiment,
            current_price=100.0,
            iv_rank=iv_rank,
            effective_regime=regime,
        )
        for cand in candidates:
            emitted.add(cand["strategy"])
    return emitted


def test_every_selector_emitted_id_resolves(monkeypatch):
    emitted = _drive_selector_matrix(monkeypatch)
    assert emitted, "matrix drive must emit candidates"

    unresolved = {s for s in emitted if resolve_strategy_identity(s) is None}
    assert not unresolved, (
        f"StrategySelector emitted IDs missing from the crosswalk: "
        f"{sorted(unresolved)} — extend strategy_identity._CROSSWALK"
    )

    # Exactly one identity each, with every canonical field populated.
    for s in emitted:
        ident = resolve_strategy_identity(s)
        assert ident.canonical_id == normalize_strategy_id(s)
        assert ident.strategy_type in StrategyType
        assert ident.structure in StructureClass


def test_selector_pool_matches_documented_tradables(monkeypatch):
    """The full matrix emits exactly the documented five-tradable pool —
    both directions: nothing undocumented appears, nothing documented is
    unreachable."""
    emitted = {normalize_strategy_id(s) for s in _drive_selector_matrix(monkeypatch)}
    assert emitted == set(TRADABLE_IDS)


# ---------------------------------------------------------------------------
# Crosswalk unit behavior
# ---------------------------------------------------------------------------

def test_no_trade_ids_resolve_to_no_trade():
    assert NO_TRADE_IDS == {"hold", "cash"}
    for raw in ("HOLD", "CASH", "hold", "Cash"):
        ident = resolve_strategy_identity(raw)
        assert ident is not None
        assert ident.structure is StructureClass.NO_TRADE
        assert ident.strategy_type is StrategyType.UNKNOWN


def test_normalization_variants_resolve():
    for raw in (
        "LONG_CALL_DEBIT_SPREAD",
        "long call debit spread",
        "Long-Call-Debit-Spread",
        "  long_call_debit_spread  ",
    ):
        ident = resolve_strategy_identity(raw)
        assert ident is not None
        assert ident.canonical_id == "long_call_debit_spread"


def test_unknown_ids_resolve_to_none():
    for raw in ("random_strategy", "", None, "call_debit", "vertical", "covered_call"):
        assert resolve_strategy_identity(raw) is None


# ---------------------------------------------------------------------------
# (b) LossMinimizer: debit verticals are spreads, not naked longs
# ---------------------------------------------------------------------------

def test_debit_spreads_do_not_classify_as_naked_longs():
    naked = {StrategyType.LONG_CALL, StrategyType.LONG_PUT}

    got_call = LossMinimizer.get_strategy_type("LONG_CALL_DEBIT_SPREAD")
    got_put = LossMinimizer.get_strategy_type("LONG_PUT_DEBIT_SPREAD")

    assert got_call is StrategyType.LONG_CALL_DEBIT_SPREAD
    assert got_put is StrategyType.LONG_PUT_DEBIT_SPREAD
    assert got_call not in naked
    assert got_put not in naked


def test_debit_spread_identity_carries_spread_payoff_semantics():
    """The classification LossMinimizer consumers receive must carry SPREAD
    payoff semantics: defined risk with a net-debit max-loss basis, never
    naked-long (uncapped-upside, single-leg) semantics. analyze_position is
    strategy-agnostic today, so the classification itself is the consumed
    observable (workflow_orchestrator deep-loser/adaptive-caps callers)."""
    for raw in ("LONG_CALL_DEBIT_SPREAD", "LONG_PUT_DEBIT_SPREAD"):
        ident = resolve_strategy_identity(raw)
        assert ident.structure is StructureClass.DEBIT_SPREAD
        assert ident.is_spread is True
        assert ident.defined_risk is True
        assert ident.max_loss_basis == "net_debit"


def test_loss_minimizer_legacy_strings_unchanged():
    # Legacy heuristics still apply to non-canonical strings.
    assert (
        LossMinimizer.get_strategy_type("credit_put_spread")
        is StrategyType.SHORT_PUT_CREDIT_SPREAD
    )
    assert LossMinimizer.get_strategy_type("Iron Condor") is StrategyType.IRON_CONDOR
    # A genuine naked long stays a naked long.
    assert LossMinimizer.get_strategy_type("long_call") is StrategyType.LONG_CALL
    assert LossMinimizer.get_strategy_type("long_put") is StrategyType.LONG_PUT
    # Genuinely unknown stays UNKNOWN (conservative behavior preserved).
    assert LossMinimizer.get_strategy_type("random_strategy") is StrategyType.UNKNOWN
    assert LossMinimizer.get_strategy_type("") is StrategyType.UNKNOWN


def test_selector_canonical_credit_ids_classify_correctly():
    assert (
        LossMinimizer.get_strategy_type("SHORT_PUT_CREDIT_SPREAD")
        is StrategyType.SHORT_PUT_CREDIT_SPREAD
    )
    assert (
        LossMinimizer.get_strategy_type("SHORT_CALL_CREDIT_SPREAD")
        is StrategyType.SHORT_CALL_CREDIT_SPREAD
    )
    assert LossMinimizer.get_strategy_type("IRON_CONDOR") is StrategyType.IRON_CONDOR
