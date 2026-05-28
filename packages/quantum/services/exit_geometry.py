"""D6 Phase 1 — spread exit GEOMETRY + candidate exit rules (pure, log-only).

This module computes the geometry of a debit vertical (strikes, width,
breakeven, and the underlying's distance to each) and evaluates a set of
candidate GEOMETRY exit rules (R1-R4). It is OBSERVATION-ONLY: the shadow
harness logs what these rules WOULD decide alongside the premium-% champion's
ACTUAL decision. **Nothing here acts on a real exit.** Promotion of any rule to
the champion is a separate, data-gated decision.

Framing: "geometry-aware exit" is a HYPOTHESIS, not a known improvement.
Premium-% measures realized P/L directly; geometry measures underlying-vs-strikes
(correlated, not identical — time/IV diverge them far from expiry). Phase 1
gathers the evidence; it does not change behavior.

Scope: debit verticals (call or put). Credit spreads / iron condors / single
legs return ``applicable=False`` (recorded as N/A by the harness, never an
error) — their geometry differs and is out of Phase-1 scope.
"""

from typing import Any, Dict, List, Optional

# R1 fractional-proximity default: take profit once the underlying has travelled
# this fraction of the width from the long strike toward the short strike.
DEFAULT_PROFIT_FRACTION = 0.8
# R4 DTE band: below LOW_DTE the profit-take tightens (captures sooner); at/above
# HIGH_DTE it equals R1's DEFAULT_PROFIT_FRACTION.
R4_LOW_DTE = 2
R4_HIGH_DTE = 7
R4_MIN_FRACTION = 0.5


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return f if f == f else None  # reject NaN
    except (TypeError, ValueError):
        return None


def compute_spread_geometry(
    position: Dict[str, Any],
    underlying_spot: Optional[float],
    dte: Optional[int],
) -> Dict[str, Any]:
    """Compute debit-vertical geometry. Returns a dict with ``applicable``:
    False for any non-debit-vertical or missing-input case (recorded N/A).

    Uses leg STRIKES + ACTIONS (convention-agnostic; never legs.quantity) and
    avg_entry_price (the per-spread net debit) — same reliable fields the #987
    payoff guard uses.
    """
    na = {"applicable": False, "reason": "not_a_debit_vertical_or_missing_inputs"}

    legs = [l for l in (position.get("legs") or []) if isinstance(l, dict)]
    if len(legs) != 2:
        return na

    long_leg = next((l for l in legs if str(l.get("action", "")).lower() in ("buy", "long")), None)
    short_leg = next((l for l in legs if str(l.get("action", "")).lower() in ("sell", "short")), None)
    if long_leg is None or short_leg is None:
        return na

    # Same option type both legs (a vertical); call or put.
    lt = str(long_leg.get("type", "")).lower()
    st = str(short_leg.get("type", "")).lower()
    if lt != st or lt not in ("call", "put"):
        return na

    long_strike = _num(long_leg.get("strike"))
    short_strike = _num(short_leg.get("strike"))
    if long_strike is None or short_strike is None:
        return na

    # Debit vertical only: a debit CALL spread buys the lower strike (long<short);
    # a debit PUT spread buys the higher strike (long>short). The opposite
    # orderings are credit spreads — out of Phase-1 scope.
    opt_type = lt
    if opt_type == "call" and not (long_strike < short_strike):
        return na
    if opt_type == "put" and not (long_strike > short_strike):
        return na

    net_debit = _num(position.get("avg_entry_price"))
    if net_debit is None or net_debit <= 0:
        return na

    width = abs(short_strike - long_strike)
    if width <= 0:
        return na

    # direction sign: +1 call (profit as spot rises), -1 put (profit as spot falls)
    sign = 1.0 if opt_type == "call" else -1.0
    breakeven = long_strike + sign * net_debit

    geom = {
        "applicable": True,
        "structure": f"debit_{opt_type}_spread",
        "opt_type": opt_type,
        "sign": sign,
        "long_strike": long_strike,
        "short_strike": short_strike,
        "width": width,
        "net_debit": net_debit,
        "breakeven": round(breakeven, 4),
        "underlying_spot": underlying_spot,
        "dte": dte,
    }
    spot = _num(underlying_spot)
    if spot is not None:
        # distances in profit direction; positive = favorable progress.
        geom["dist_to_short_strike"] = round(sign * (spot - short_strike), 4)
        geom["dist_to_breakeven"] = round(sign * (spot - breakeven), 4)
        geom["frac_of_width_traveled"] = round(sign * (spot - long_strike) / width, 4)
    return geom


def _beyond(spot: float, level: float, sign: float) -> bool:
    """True if spot has moved in the PROFIT direction at/through level."""
    return (spot >= level) if sign > 0 else (spot <= level)


def _adverse(spot: float, level: float, sign: float) -> bool:
    """True if spot has moved in the ADVERSE direction through level."""
    return (spot < level) if sign > 0 else (spot > level)


def _r4_fraction(dte: Optional[int]) -> float:
    """R1 fraction tightened by DTE: shrinks from DEFAULT_PROFIT_FRACTION (DTE ≥
    R4_HIGH_DTE) down to R4_MIN_FRACTION (DTE ≤ R4_LOW_DTE), linear between."""
    if dte is None:
        return DEFAULT_PROFIT_FRACTION
    if dte >= R4_HIGH_DTE:
        return DEFAULT_PROFIT_FRACTION
    if dte <= R4_LOW_DTE:
        return R4_MIN_FRACTION
    span = R4_HIGH_DTE - R4_LOW_DTE
    t = (dte - R4_LOW_DTE) / span
    return R4_MIN_FRACTION + t * (DEFAULT_PROFIT_FRACTION - R4_MIN_FRACTION)


def _decision(kind: str, reason: str) -> Dict[str, str]:
    return {"decision": kind, "reason": reason}


def evaluate_geometry_rules(geometry: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    """Evaluate candidate geometry exit rules R1-R4 (+ R1_frac variant).

    Returns {rule_name: {decision: hold|take_profit|stop|n/a, reason: str}}.
    PURE: no I/O, no side effects, never acts on a real exit. Returns n/a for
    every rule when geometry is not applicable or spot is unavailable.
    """
    if not geometry.get("applicable"):
        na = _decision("n/a", "geometry_not_applicable")
        return {k: na for k in ("R1", "R1_frac", "R2", "R3", "R4")}

    spot = _num(geometry.get("underlying_spot"))
    if spot is None:
        na = _decision("n/a", "no_underlying_spot")
        return {k: na for k in ("R1", "R1_frac", "R2", "R3", "R4")}

    sign = geometry["sign"]
    long_strike = geometry["long_strike"]
    short_strike = geometry["short_strike"]
    width = geometry["width"]
    breakeven = geometry["breakeven"]
    dte = geometry.get("dte")

    out: Dict[str, Dict[str, str]] = {}

    # R1 — take profit once the underlying reaches the short strike (max-profit zone).
    if _beyond(spot, short_strike, sign):
        out["R1"] = _decision("take_profit", f"spot {spot} at/through short strike {short_strike}")
    else:
        out["R1"] = _decision("hold", f"spot {spot} short of short strike {short_strike}")

    # R1_frac — take profit at a configurable fraction of the width toward short.
    frac_level = long_strike + sign * DEFAULT_PROFIT_FRACTION * width
    if _beyond(spot, frac_level, sign):
        out["R1_frac"] = _decision(
            "take_profit",
            f"spot {spot} at/through {DEFAULT_PROFIT_FRACTION:.0%} level {round(frac_level,4)}",
        )
    else:
        out["R1_frac"] = _decision("hold", f"spot {spot} short of {round(frac_level,4)}")

    # R2 — stop on breakeven breach (adverse).
    if _adverse(spot, breakeven, sign):
        out["R2"] = _decision("stop", f"spot {spot} breached breakeven {breakeven}")
    else:
        out["R2"] = _decision("hold", f"spot {spot} on profit side of breakeven {breakeven}")

    # R3 — stop on long-strike breach (more conservative than R2).
    if _adverse(spot, long_strike, sign):
        out["R3"] = _decision("stop", f"spot {spot} breached long strike {long_strike}")
    else:
        out["R3"] = _decision("hold", f"spot {spot} above long strike {long_strike}")

    # R4 — DTE-scaled tighten of the R1 profit-take toward the short strike.
    r4_frac = _r4_fraction(dte)
    r4_level = long_strike + sign * r4_frac * width
    if _beyond(spot, r4_level, sign):
        out["R4"] = _decision(
            "take_profit",
            f"spot {spot} at/through DTE-scaled level {round(r4_level,4)} (frac {r4_frac:.2f}, dte {dte})",
        )
    else:
        out["R4"] = _decision("hold", f"spot {spot} short of DTE-scaled level {round(r4_level,4)} (dte {dte})")

    return out
