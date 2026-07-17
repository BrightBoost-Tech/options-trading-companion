# packages/quantum/tests/test_risk_cap_routing.py
"""Risk-cap family routing: drift lock + calculate_strategy_cap outcomes.

Stacked-PR twin of test_strategy_identity_crosswalk.py (identity PR): the
cap-directed tests removed from that file live here, adapted to the
risk_cap_routing module.

Falsifiers:
- If strategy_identity gains a tradable ID the family map lacks (or vice
  versa), the import-time lock raises and test_drift_lock fails.
- If calculate_strategy_cap stops routing a selector ID to its intended
  family (or someone changes a cap value), the family-equality tests fail.
- If the routing ever LOOSENS-only (misses the SHOCK tightening direction)
  or invents caps for unknown/no-trade/REBOUND-condor inputs, the
  direction/fallthrough tests fail.
"""

import itertools

import pytest

from packages.quantum.analytics.strategy_identity import (
    NO_TRADE_IDS,
    TRADABLE_IDS,
)
from packages.quantum.analytics.strategy_selector import StrategySelector
from packages.quantum.common_enums import RegimeState
from packages.quantum.services.risk_budget_engine import RiskBudgetEngine
from packages.quantum.services.risk_cap_routing import resolve_risk_cap_family


# ---------------------------------------------------------------------------
# Drift lock: every tradable identity has exactly one family; no-trade and
# unknown identifiers have none. Domain equality is enforced at import time
# by the module itself — these tests are the executable statement of it.
# ---------------------------------------------------------------------------

def test_drift_lock_every_tradable_identity_has_exactly_one_family():
    families = {}
    for canonical_id in sorted(TRADABLE_IDS):
        family = resolve_risk_cap_family(canonical_id)
        assert family is not None, f"{canonical_id} has no risk-cap family"
        assert isinstance(family, str) and family
        families[canonical_id] = family
    # Exactly one family per identity, and the five tradables cover the
    # five distinct vertical/condor families (no accidental collapse).
    assert len(families) == len(TRADABLE_IDS)
    assert set(families.values()) == {
        "debit_call", "debit_put", "credit_put", "credit_call", "iron_condor"
    }


def test_drift_lock_selector_route_emits_only_family_mapped_ids(monkeypatch):
    """Route-drive the REAL StrategySelector.get_candidates across the input
    matrix: every emitted ID must resolve to a family (the selector's pool
    is the registry — this map may not silently lag it)."""
    monkeypatch.setenv("CURRENT_PROGRESSION_PHASE", "micro_live")
    selector = StrategySelector()
    emitted = set()
    for sentiment, iv_rank, regime in itertools.product(
        ["BULLISH", "BEARISH", "NEUTRAL", "EARNINGS"],
        [10.0, 40.0, 70.0],
        ["suppressed", "normal", "elevated", "shock", "rebound", "chop", None],
    ):
        for cand in selector.get_candidates(
            ticker="TEST",
            sentiment=sentiment,
            current_price=100.0,
            iv_rank=iv_rank,
            effective_regime=regime,
        ):
            emitted.add(cand["strategy"])
    assert emitted, "matrix drive must emit candidates"
    unmapped = {s for s in emitted if resolve_risk_cap_family(s) is None}
    assert not unmapped, (
        f"selector emitted IDs with no risk-cap family: {sorted(unmapped)}"
    )


def test_no_trade_and_unknown_have_no_family():
    for raw in sorted(NO_TRADE_IDS) + ["HOLD", "CASH"]:
        assert resolve_risk_cap_family(raw) is None
    for raw in ("random_strategy", "", None, "call_debit", "vertical", "covered_call"):
        assert resolve_risk_cap_family(raw) is None


# ---------------------------------------------------------------------------
# RiskBudgetEngine: selector IDs hit the intended family cap.
# Values are asserted by EQUALITY with the module's own family-key path
# (calculate_strategy_cap(family_key, regime) is a pre-existing exact
# match) — no cap value is pinned or changed by this suite.
# ---------------------------------------------------------------------------

SELECTOR_TO_FAMILY = {
    "LONG_CALL_DEBIT_SPREAD": "debit_call",
    "LONG_PUT_DEBIT_SPREAD": "debit_put",
    "SHORT_PUT_CREDIT_SPREAD": "credit_put",
    "SHORT_CALL_CREDIT_SPREAD": "credit_call",
    "IRON_CONDOR": "iron_condor",
}

# Regimes whose tables define all five families (REBOUND deliberately
# excluded here: it defines no iron_condor key — covered below).
FULL_FAMILY_REGIMES = [
    RegimeState.SUPPRESSED,
    RegimeState.NORMAL,
    RegimeState.ELEVATED,
    RegimeState.SHOCK,
    RegimeState.CHOP,
]


@pytest.mark.parametrize("selector_id,family", sorted(SELECTOR_TO_FAMILY.items()))
@pytest.mark.parametrize("regime", FULL_FAMILY_REGIMES)
def test_selector_ids_hit_intended_family_cap(selector_id, family, regime):
    got = RiskBudgetEngine.calculate_strategy_cap(selector_id, regime)
    intended = RiskBudgetEngine.calculate_strategy_cap(family, regime)
    assert got == intended, (
        f"{selector_id} in {regime}: got {got}, family {family} cap is {intended}"
    )


def test_debit_fix_is_observable_in_normal_regime():
    """Pre-fix falsifier: 'long_call_debit_spread' fell to the 0.05 base cap
    because no family key is a substring of it. Post-fix it must equal the
    debit_call family cap, which differs from the base cap in NORMAL
    (0.05 -> 0.15: the LOOSENING direction of this reroute)."""
    base = RiskBudgetEngine.calculate_strategy_cap(
        "definitely_unknown_strategy", RegimeState.NORMAL
    )
    fixed = RiskBudgetEngine.calculate_strategy_cap(
        "LONG_CALL_DEBIT_SPREAD", RegimeState.NORMAL
    )
    family = RiskBudgetEngine.calculate_strategy_cap("debit_call", RegimeState.NORMAL)
    assert fixed == family
    assert fixed > base  # the routing visibly loosened this cell
    assert base == 0.05 and fixed == 0.15  # the exact 0.05 -> 0.15 move


def test_routing_also_applies_in_tightening_direction():
    """SHOCK credit_put cap is BELOW the base cap (0.05 -> 0.02) — the fix
    must route there too (identity repair, not a loosening)."""
    base = RiskBudgetEngine.calculate_strategy_cap(
        "definitely_unknown_strategy", RegimeState.SHOCK
    )
    got = RiskBudgetEngine.calculate_strategy_cap(
        "SHORT_PUT_CREDIT_SPREAD", RegimeState.SHOCK
    )
    intended = RiskBudgetEngine.calculate_strategy_cap("credit_put", RegimeState.SHOCK)
    assert got == intended
    assert got < base
    assert base == 0.05 and got == 0.02  # the exact 0.05 -> 0.02 move


def test_rebound_condor_falls_through_to_base_cap():
    """REBOUND defines no iron_condor family key: the routing must NOT
    invent a cap — legacy fallthrough to base applies."""
    got = RiskBudgetEngine.calculate_strategy_cap("IRON_CONDOR", RegimeState.REBOUND)
    base = RiskBudgetEngine.calculate_strategy_cap(
        "definitely_unknown_strategy", RegimeState.REBOUND
    )
    assert got == base


def test_unknown_string_still_gets_base_cap():
    assert (
        RiskBudgetEngine.calculate_strategy_cap("no_such_thing", RegimeState.NORMAL)
        == 0.05
    )


def test_legacy_substring_strings_unchanged():
    """Legacy persisted strings that already substring-matched keep their
    pre-fix resolution (the fallback path is untouched)."""
    for legacy, family in (
        ("credit_put_spread", "credit_put"),
        ("credit_call_spread", "credit_call"),
        ("my_iron_condor_variant", "iron_condor"),
    ):
        got = RiskBudgetEngine.calculate_strategy_cap(legacy, RegimeState.NORMAL)
        intended = RiskBudgetEngine.calculate_strategy_cap(family, RegimeState.NORMAL)
        assert got == intended


def test_family_keys_and_spread_position_literals_unaffected():
    """The optimizer path passes SpreadPosition.spread_type values (family
    keys + structural literals). Family keys exact-match BEFORE the routing;
    non-canonical literals resolve to no family and keep legacy behavior."""
    # Structural literals from the SpreadPosition Literal that are not
    # canonical selector IDs: no family; legacy exact/substring semantics.
    assert RiskBudgetEngine.calculate_strategy_cap("vertical", RegimeState.NORMAL) == 0.10
    assert RiskBudgetEngine.calculate_strategy_cap("single", RegimeState.SUPPRESSED) == 0.15
    for literal in ("other", "custom", "credit_spread", "debit_spread"):
        assert resolve_risk_cap_family(literal) is None
        assert (
            RiskBudgetEngine.calculate_strategy_cap(literal, RegimeState.NORMAL) == 0.05
        )


def test_hold_cash_get_base_cap():
    for verdict in ("HOLD", "CASH"):
        assert (
            RiskBudgetEngine.calculate_strategy_cap(verdict, RegimeState.NORMAL)
            == 0.05
        )
