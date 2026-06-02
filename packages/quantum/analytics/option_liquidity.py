"""Option-liquidity scoring — OBSERVATION-FIRST universe weighting.

The 2026-06-02 post-#1012 re-derivation found that the *option* spread gate
(liquidity), not capital (H7/36% ceiling) or EV, is the DOMINANT wall (33 of 91
rejections). The universe's existing `scanner_universe.liquidity_score` is an
EQUITY-liquidity proxy (market cap + share volume) — it ranks SNAP/NIO/AAL/LYFT
HIGH (liquid stock) even though their OPTION markets are persistently too wide
to pass the gate, diluting scan effort away from the liquid-affordable middle
(BAC/CSX/KO/KMI/NFLX/CMCSA).

This module computes a per-symbol OPTION-liquidity score from the ATM bid-ask
RELATIVE spread (the chain we already fetch at scan time post-#1012). A low
score predicts spread-gate FAILURE — and the OBSERVATION record (logged
regardless of the flag) is what validates that prediction before the score ever
weights live selection.

FLAGGED ASSUMPTIONS: every threshold/weight below is a GUESSED magnitude (like
the D2 tempers / D4 regime_filter), surfaced for calibration against the
observation record — NOT asserted correct. Weighting is graduation-gated on the
observation showing the score predicts the gate.

Default OFF: with LIQUIDITY_WEIGHTING_ENABLED unset, selection is byte-identical;
the score is computed + logged (observe-first), nothing is weighted.
"""

import os
from typing import Any, Dict, List, Optional, Tuple

FLAG_ENV = "LIQUIDITY_WEIGHTING_ENABLED"

# ── FLAGGED ASSUMPTIONS (guessed magnitudes — to calibrate, not asserted) ──
FLAGGED_ASSUMPTIONS: Dict[str, Any] = {
    # ATM relative bid-ask spread → score anchors. The scanner's combo spread
    # gate fires at ~10% combo width / cost; a single-leg ATM rel spread of
    # ~5% already implies a combo near/over the gate, so:
    "tight_rel_spread": 0.03,   # <=3% ATM rel spread → fully liquid (score 100)
    "wide_rel_spread": 0.20,    # >=20% ATM rel spread → fully illiquid (score 0)
    # would-be weight (ranking de-prioritization) per score; never a hard drop.
    "min_weight": 0.5,          # lowest-liquidity names keep 0.5× priority (reversible)
    "max_weight": 1.0,          # liquid names unchanged
    # the equity-liquidity blend when weighting is ON (universe ordering):
    # effective = equity_liquidity_score * weight(option_liquidity_score)
    "blend": "multiplicative_priority_weight",
}


def is_weighting_enabled() -> bool:
    return os.environ.get(FLAG_ENV, "0").strip().lower() in ("1", "true", "yes", "on")


def _bid_ask(contract: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    """Schema-agnostic (nested TruthLayer quote dict OR flat top-level)."""
    q = contract.get("quote")
    if isinstance(q, dict):
        return q.get("bid"), q.get("ask")
    return contract.get("bid"), contract.get("ask")


def _rel_spread(contract: Dict[str, Any]) -> Optional[float]:
    bid, ask = _bid_ask(contract)
    try:
        bid = float(bid); ask = float(ask)
    except (TypeError, ValueError):
        return None
    if bid <= 0 or ask <= 0 or ask < bid:
        return None
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return None
    return (ask - bid) / mid


def _nearest_atm(contracts: List[Dict[str, Any]], spot: float, right: str) -> Optional[Dict[str, Any]]:
    cands = [c for c in contracts if (c.get("right") or c.get("type")) == right and c.get("strike") is not None]
    if not cands:
        return None
    return min(cands, key=lambda c: abs(float(c["strike"]) - spot))


def atm_relative_spread(chain: List[Dict[str, Any]], spot: float) -> Optional[float]:
    """Mean ATM call+put bid-ask relative spread for the underlying.

    The direct predictor of the combo spread gate (which measures leg bid-ask
    width / cost). None when neither ATM leg has a usable NBBO (caller logs N/A,
    never errors). Strategy-independent — one number per symbol per cycle.
    """
    if not chain or not spot or spot <= 0:
        return None
    reads: List[float] = []
    for right in ("call", "put"):
        c = _nearest_atm(chain, spot, right)
        if c is not None:
            rs = _rel_spread(c)
            if rs is not None:
                reads.append(rs)
    if not reads:
        return None
    return sum(reads) / len(reads)


def liquidity_score(rel_spread: Optional[float]) -> Optional[float]:
    """Map ATM relative spread → 0-100 (high = tight = liquid). None passthrough.

    Linear between the tight (→100) and wide (→0) anchors; clamped. FLAGGED."""
    if rel_spread is None:
        return None
    A = FLAGGED_ASSUMPTIONS
    tight, wide = A["tight_rel_spread"], A["wide_rel_spread"]
    if rel_spread <= tight:
        return 100.0
    if rel_spread >= wide:
        return 0.0
    return round(100.0 * (wide - rel_spread) / (wide - tight), 2)


def would_be_weight(score: Optional[float]) -> float:
    """Ranking priority multiplier from the score. WEIGHT, never a hard drop:
    the lowest-liquidity names keep `min_weight` priority (reversible — a name
    that tightens climbs back). Unknown score → 1.0 (no de-prioritization)."""
    A = FLAGGED_ASSUMPTIONS
    if score is None:
        return A["max_weight"]
    s = max(0.0, min(100.0, float(score)))
    return round(A["min_weight"] + (A["max_weight"] - A["min_weight"]) * (s / 100.0), 4)
