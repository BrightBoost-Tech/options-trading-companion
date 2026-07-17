# packages/quantum/analytics/strategy_identity.py
"""Canonical strategy-identity crosswalk (2026-07-16).

Single source of truth mapping every StrategySelector-emitted strategy
identifier to:
  (a) its LossMinimizer classification (``StrategyType``), and
  (b) its payoff-structure class (``StructureClass``) with defined-risk /
      max-loss-basis payoff semantics.

Root cause this module fixes: consumers re-derived identity from the raw
strategy string with their own substring heuristics and misread the
selector IDs:

- ``LossMinimizer.get_strategy_type``: "LONG_CALL_DEBIT_SPREAD" matched the
  '"long" and "call"' heuristic -> ``StrategyType.LONG_CALL`` (a
  defined-risk SPREAD classified as a naked long: wrong payoff identity —
  a debit vertical's loss is capped at the net debit and its upside is
  capped at width minus debit; a naked long has uncapped upside and
  single-leg close semantics).

Contract:
- Exact-NORMALIZED match only (lower/strip; spaces and hyphens ->
  underscores). Unknown identifiers resolve to ``None`` and callers MUST
  preserve their existing conservative fallback (LossMinimizer -> legacy
  heuristics / UNKNOWN). This module never guesses.
- Drift lock: ``test_strategy_identity_crosswalk.py`` route-drives
  ``StrategySelector.get_candidates`` across sentiment x IV x regime and
  FAILS if the selector ever emits an ID absent from this table — the
  selector's emitted pool is the registry; this table may not silently
  lag it.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional

from packages.quantum.common_enums import StrategyType


class StructureClass(str, Enum):
    """Payoff-structure classification of a strategy identifier."""

    DEBIT_SPREAD = "debit_spread"
    CREDIT_SPREAD = "credit_spread"
    IRON_CONDOR = "iron_condor"
    NO_TRADE = "no_trade"


@dataclass(frozen=True)
class StrategyIdentity:
    """One strategy identifier's canonical identity across consumers.

    max_loss_basis encodes the DEFINED-RISK payoff semantics:
    - "net_debit": debit vertical — max loss = net debit paid; upside is
      capped at (strike width - net debit). NOT a naked long.
    - "width_minus_credit": credit vertical / condor — max loss =
      strike width - net credit received.
    - None: no position exists (HOLD/CASH).
    """

    canonical_id: str
    strategy_type: StrategyType
    structure: StructureClass
    is_spread: bool
    defined_risk: bool
    max_loss_basis: Optional[str]


def normalize_strategy_id(raw: str) -> str:
    """Normalize a raw strategy identifier for exact-match lookup.

    Mirrors LossMinimizer.get_strategy_type's normalization:
    lower + strip, spaces and hyphens -> underscores.
    """
    return str(raw or "").lower().strip().replace(" ", "_").replace("-", "_")


# The complete selector-emitted vocabulary. get_candidates (the production
# multi-strategy path) emits only the five tradables; determine_strategy
# (legacy single-pick path) additionally emits HOLD and CASH.
_CROSSWALK: Dict[str, StrategyIdentity] = {
    ident.canonical_id: ident
    for ident in (
        StrategyIdentity(
            canonical_id="long_call_debit_spread",
            strategy_type=StrategyType.LONG_CALL_DEBIT_SPREAD,
            structure=StructureClass.DEBIT_SPREAD,
            is_spread=True,
            defined_risk=True,
            max_loss_basis="net_debit",
        ),
        StrategyIdentity(
            canonical_id="long_put_debit_spread",
            strategy_type=StrategyType.LONG_PUT_DEBIT_SPREAD,
            structure=StructureClass.DEBIT_SPREAD,
            is_spread=True,
            defined_risk=True,
            max_loss_basis="net_debit",
        ),
        StrategyIdentity(
            canonical_id="short_put_credit_spread",
            strategy_type=StrategyType.SHORT_PUT_CREDIT_SPREAD,
            structure=StructureClass.CREDIT_SPREAD,
            is_spread=True,
            defined_risk=True,
            max_loss_basis="width_minus_credit",
        ),
        StrategyIdentity(
            canonical_id="short_call_credit_spread",
            strategy_type=StrategyType.SHORT_CALL_CREDIT_SPREAD,
            structure=StructureClass.CREDIT_SPREAD,
            is_spread=True,
            defined_risk=True,
            max_loss_basis="width_minus_credit",
        ),
        StrategyIdentity(
            canonical_id="iron_condor",
            strategy_type=StrategyType.IRON_CONDOR,
            structure=StructureClass.IRON_CONDOR,
            is_spread=True,
            defined_risk=True,
            max_loss_basis="width_minus_credit",
        ),
        # No-trade verdicts (determine_strategy only). StrategyType.UNKNOWN
        # preserves LossMinimizer's existing conservative handling — there
        # is no position to classify.
        StrategyIdentity(
            canonical_id="hold",
            strategy_type=StrategyType.UNKNOWN,
            structure=StructureClass.NO_TRADE,
            is_spread=False,
            defined_risk=True,
            max_loss_basis=None,
        ),
        StrategyIdentity(
            canonical_id="cash",
            strategy_type=StrategyType.UNKNOWN,
            structure=StructureClass.NO_TRADE,
            is_spread=False,
            defined_risk=True,
            max_loss_basis=None,
        ),
    )
}

# Test/consumer conveniences (frozen views of the table, not a second
# registry — both derive from _CROSSWALK).
TRADABLE_IDS = frozenset(
    k for k, v in _CROSSWALK.items() if v.structure is not StructureClass.NO_TRADE
)
NO_TRADE_IDS = frozenset(
    k for k, v in _CROSSWALK.items() if v.structure is StructureClass.NO_TRADE
)


def resolve_strategy_identity(raw: str) -> Optional[StrategyIdentity]:
    """Resolve a raw strategy identifier to its canonical identity.

    Exact-normalized match only. Returns None for anything not in the
    selector-emitted vocabulary — callers must fall back to their own
    conservative legacy handling (never fabricate an identity here).
    """
    if not raw:
        return None
    return _CROSSWALK.get(normalize_strategy_id(raw))
