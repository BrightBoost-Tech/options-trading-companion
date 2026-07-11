"""Shadow-to-expiry thesis scoring (I5, 2026-07-11) — OBSERVE-ONLY.

Classifies a closed position's structure from its legs and scores the ENTRY
THESIS against the underlying's price at the ORIGINAL expiry — independent of
fills / P&L. Pure functions, no I/O; the daily job wires them to the price
feed and the store.

DEFINITIONS (stated once, applied consistently — strict inequalities: a value
exactly AT a decision strike is MISS, the strike was reached):
  - iron_condor HIT   = underlying strictly INSIDE the SHORT strikes at expiry
    (short_put < U < short_call). The short strikes ARE the range bet;
    breakevens (short ± credit) are a P&L concept and unknown for the legacy
    blank-credit rows, so the structural short-strike range is the definition.
  - credit_vertical HIT = the SHORT strike is NOT breached (U on the OTM side).
  - debit_vertical HIT  = underlying finished ITM through the LONG strike (the
    DIRECTIONAL thesis was correct — this is the direction bet, not the P&L
    breakeven, which would need the debit paid).
  - directional (single leg) HIT = finished ITM for the held direction.
  - unknown = the price source returned nothing (U is None) or the structure /
    strikes can't be resolved. NEVER fabricated (H9).
"""
from typing import Any, Dict, List, Optional, Tuple


def _strike(leg: Dict[str, Any]) -> Optional[float]:
    try:
        return float(leg.get("strike"))
    except (TypeError, ValueError):
        return None


def _is_put(leg: Dict[str, Any]) -> bool:
    return (leg.get("type") or leg.get("right") or "").lower().startswith("p")


def _is_sell(leg: Dict[str, Any]) -> bool:
    return (leg.get("action") or leg.get("side") or "").lower() == "sell"


def classify_structure(legs: List[Dict[str, Any]]) -> str:
    """iron_condor | credit_vertical | debit_vertical | directional | unknown."""
    if not legs:
        return "unknown"
    n = len(legs)
    puts = [l for l in legs if _is_put(l)]
    calls = [l for l in legs if not _is_put(l)]
    if n == 4 and len(puts) == 2 and len(calls) == 2:
        return "iron_condor"
    if n == 2 and (len(puts) == 2 or len(calls) == 2):
        sold = next((l for l in legs if _is_sell(l)), None)
        bought = next((l for l in legs if not _is_sell(l)), None)
        if sold is None or bought is None:
            return "unknown"
        ss, bs = _strike(sold), _strike(bought)
        if ss is None or bs is None:
            return "unknown"
        # PUT: sold strike ABOVE bought = net credit (bull put). CALL: sold
        # BELOW bought = net credit (bear call). Otherwise net debit.
        credit = (ss > bs) if _is_put(sold) else (ss < bs)
        return "credit_vertical" if credit else "debit_vertical"
    if n == 1:
        return "directional"
    return "unknown"


def score_thesis(
    legs: List[Dict[str, Any]],
    underlying_at_expiry: Optional[float],
) -> Tuple[str, str]:
    """Return (outcome, basis). outcome ∈ {hit, miss, unknown}. The caller owns
    'in_progress' (expiry not yet passed) — this function only scores a
    resolvable expiry."""
    U = underlying_at_expiry
    if U is None:
        return "unknown", "no underlying price at expiry"

    structure = classify_structure(legs)

    if structure == "iron_condor":
        short_put = next((l for l in legs if _is_put(l) and _is_sell(l)), None)
        short_call = next((l for l in legs if not _is_put(l) and _is_sell(l)), None)
        sp = _strike(short_put) if short_put else None
        sc = _strike(short_call) if short_call else None
        if sp is None or sc is None:
            return "unknown", "iron_condor missing a short strike"
        hit = sp < U < sc
        return (("hit" if hit else "miss"),
                f"IC: underlying {U:.2f} {'inside' if hit else 'outside'} shorts [{sp:.2f}, {sc:.2f}]")

    if structure in ("credit_vertical", "debit_vertical"):
        sold = next((l for l in legs if _is_sell(l)), None)
        bought = next((l for l in legs if not _is_sell(l)), None)
        if sold is None or bought is None:
            return "unknown", f"{structure} missing a leg"
        is_put = _is_put(sold)
        ss, bs = _strike(sold), _strike(bought)
        if ss is None or bs is None:
            return "unknown", f"{structure} missing a strike"
        if structure == "credit_vertical":
            hit = (U > ss) if is_put else (U < ss)  # short strike NOT breached
            return (("hit" if hit else "miss"),
                    f"credit {'put' if is_put else 'call'} vertical: underlying "
                    f"{U:.2f} vs short {ss:.2f} → {'OTM/kept' if hit else 'breached'}")
        # debit_vertical: HIT = finished ITM through the LONG (bought) strike
        hit = (U < bs) if is_put else (U > bs)
        return (("hit" if hit else "miss"),
                f"debit {'put' if is_put else 'call'} vertical: underlying "
                f"{U:.2f} vs long {bs:.2f} → {'ITM' if hit else 'OTM'}")

    if structure == "directional":
        leg = legs[0]
        strike = _strike(leg)
        if strike is None:
            return "unknown", "directional missing strike"
        is_put = _is_put(leg)
        is_long = not _is_sell(leg)
        itm = (U < strike) if is_put else (U > strike)
        hit = itm if is_long else (not itm)
        return (("hit" if hit else "miss"),
                f"{'long' if is_long else 'short'} {'put' if is_put else 'call'}: "
                f"underlying {U:.2f} vs strike {strike:.2f} → {'ITM' if itm else 'OTM'}")

    return "unknown", f"unrecognized structure ({len(legs)} legs)"
