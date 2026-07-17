# packages/quantum/services/risk_cap_routing.py
"""Canonical strategy identity -> risk-cap family routing (2026-07-16).

Owns the ONE mapping from a selector-emitted strategy identity to the
``RiskBudgetEngine.calculate_strategy_cap`` regime-table family key.
Stacked on the strategy-identity PR: identity (what a strategy IS) lives in
``analytics/strategy_identity.py``; cap routing (which regime-table family
its capital cap comes from) lives here, because rerouting changes live cap
outcomes in both directions (NORMAL debit 0.05 -> 0.15 looser, SHOCK
credit_put 0.05 -> 0.02 tighter) and is separately owner-reviewed.

Root cause this module fixes: ``calculate_strategy_cap`` matched family
keys exact-then-substring against the raw strategy string, but the
persisted selector IDs never contain the family keys as substrings
("long_call_debit_spread" contains "call_debit", not the family key
"debit_call"; "short_put_credit_spread" contains "put_credit", not
"credit_put"), so every selector-emitted vertical fell to the 0.05 base
cap instead of the regime table's intended family cap. Only IRON_CONDOR
exact-matched.

Contract:
- The mapping's domain is EXACTLY ``strategy_identity.TRADABLE_IDS`` —
  enforced at import time (fail-loud, never a silently-lagging second
  registry) and by the drift-lock test in ``test_risk_cap_routing.py``.
- ``resolve_risk_cap_family`` resolves through
  ``resolve_strategy_identity`` (exact-normalized match only): unknown or
  no-trade identifiers (HOLD/CASH) return ``None`` and the caller MUST
  keep its legacy conservative fallback (substring match, then base cap).
  This module never guesses and never invents a cap.
- A family key absent from a given regime's table (e.g. iron_condor in
  REBOUND) is the CALLER's fallthrough decision — this module only names
  the family, it does not know the tables.
"""

from typing import Dict, Optional

from packages.quantum.analytics.strategy_identity import (
    TRADABLE_IDS,
    resolve_strategy_identity,
)

# Canonical identity -> calculate_strategy_cap family key. Keyed on the
# crosswalk's canonical_id values; domain integrity against TRADABLE_IDS is
# enforced immediately below, so this table cannot drift from the identity
# registry without failing the import.
_FAMILY_BY_CANONICAL_ID: Dict[str, str] = {
    "long_call_debit_spread": "debit_call",
    "long_put_debit_spread": "debit_put",
    "short_put_credit_spread": "credit_put",
    "short_call_credit_spread": "credit_call",
    "iron_condor": "iron_condor",
}

# Import-time drift lock (H9: a mapping we cannot complete must fail loud,
# never partially route). One family per tradable identity, no extras.
_missing = set(TRADABLE_IDS) - set(_FAMILY_BY_CANONICAL_ID)
_extra = set(_FAMILY_BY_CANONICAL_ID) - set(TRADABLE_IDS)
if _missing or _extra:
    raise RuntimeError(
        "risk_cap_routing family map drifted from strategy_identity "
        f"TRADABLE_IDS: missing={sorted(_missing)} extra={sorted(_extra)} — "
        "extend _FAMILY_BY_CANONICAL_ID in lockstep with the crosswalk"
    )


def resolve_risk_cap_family(raw: str) -> Optional[str]:
    """Resolve a raw strategy identifier to its risk-cap family key.

    Exact-normalized identity resolution first (via strategy_identity);
    tradable identities map to exactly one family key. Returns None for
    unknown strings AND for no-trade verdicts (HOLD/CASH) — callers keep
    their legacy conservative fallback in both cases.
    """
    ident = resolve_strategy_identity(raw)
    if ident is None:
        return None
    return _FAMILY_BY_CANONICAL_ID.get(ident.canonical_id)
