"""Structural mark-validity clamp (06-15) — reject IMPOSSIBLE composed marks
before any exit condition evaluates.

WHY (2026-06-15 13:30Z): the QQQ iron condor (5-wide wings, 1.61 net credit,
max structural loss $339) was force-closed on a stop_loss at a composed mark
of −7.305 / implied −$569.50 — physically impossible: a defined-risk spread's
per-contract close value cannot exceed its wing width (5.00), and its loss
cannot exceed max_loss (wing − credit = 3.39 → $339). The per-leg
degenerate-quote rejector (48cf8ec) covers one leg pricing badly, but the
−7.305 reached the stop via a DB-stale fallback mark — a COMPOSED
structure-level impossibility that no per-leg check catches. The broker
rejected the resulting 7.30 close order; that luck is not a control.

This is the stop-side analogue of the #1034 Stage-2 target_profit guard, with
the critical asymmetry preserved: stops are NEVER SUPPRESSED. An impossible
mark is treated as UNPRICEABLE for the cycle (skip the exit eval, loud
[STRUCT_CLAMP] + alert, retry next cycle when a sane mark returns) — exactly
the existing degenerate-quote / stale-fallback fail-closed posture. A real
near-max mark (e.g. −$330 < max $339) is NOT rejected — it is a genuine stop
that MUST fire. The boundary is BEYOND max loss only.

Pure, dependency-free, never raises: any malformed input → (True,
"unvalidatable", {}) so the clamp can only ever *add* a rejection on a clearly
impossible mark, never block a normal one on a parsing edge.
"""

from typing import Any, Dict, List, Optional, Tuple

# Boundary tolerance: reject only marks BEYOND the structural limit, never AT
# or approaching it. 2% headroom so a legitimate at-max stop (−$339 on a $339
# condor) and float noise pass; the impossible cases (−$569, |mark| 7.305 vs
# wing 5.00) clear it by a wide margin.
CLAMP_TOLERANCE = float(0.02)

REASON_OK = "ok"
REASON_NOT_DEFINED_RISK = "not_defined_risk"
REASON_UNVALIDATABLE = "unvalidatable"
REASON_MARK_EXCEEDS_WING = "mark_exceeds_wing_width"
REASON_LOSS_EXCEEDS_MAX = "implied_loss_exceeds_max_loss"

MULTIPLIER = 100.0


def _f(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def structure_wing_width(legs: List[Dict[str, Any]]) -> Optional[float]:
    """Max single-vertical wing width across a defined-risk structure.

    A vertical = two legs of the SAME option type at DIFFERENT strikes; the
    width is |strike_hi − strike_lo|. A condor has two verticals (call side +
    put side); the structural wing width is the max of the two (the binding
    max-loss leg). Returns None when no vertical is present (single-leg,
    straddle, or missing strikes) — the clamp does not apply to those.
    """
    if not isinstance(legs, list):
        return None
    by_type: Dict[str, List[float]] = {}
    for leg in legs:
        if not isinstance(leg, dict):
            continue
        strike = _f(leg.get("strike"))
        if strike is None:
            continue
        ltype = str(leg.get("type") or leg.get("option_type") or "").lower()
        # Normalize common encodings (call/c, put/p).
        if ltype in ("c", "call"):
            ltype = "call"
        elif ltype in ("p", "put"):
            ltype = "put"
        else:
            ltype = "?"
        by_type.setdefault(ltype, []).append(strike)

    widths: List[float] = []
    for _t, strikes in by_type.items():
        uniq = sorted(set(strikes))
        if len(uniq) >= 2:
            widths.append(uniq[-1] - uniq[0])
    if not widths:
        return None
    return max(widths)


def validate_structure_mark(position: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
    """Validate a position's COMPOSED mark against its structural geometry.

    Returns (ok, reason, detail). ok=False ONLY for a defined-risk structure
    whose per-contract |mark| exceeds its wing width, or whose implied dollar
    loss exceeds its max structural loss, by more than CLAMP_TOLERANCE. Every
    other case (not defined-risk, unparseable, sane mark) returns ok=True so
    the clamp can never block a normal evaluation.
    """
    try:
        legs = position.get("legs") or []
        wing = structure_wing_width(legs)
        if wing is None or wing <= 0:
            return True, REASON_NOT_DEFINED_RISK, {}

        mark = _f(position.get("current_mark"))
        upl = _f(position.get("unrealized_pl"))
        qty = _f(position.get("quantity"))
        entry = _f(position.get("avg_entry_price"))
        if mark is None or qty is None or entry is None:
            return True, REASON_UNVALIDATABLE, {}

        abs_qty = abs(qty)
        net_entry = abs(entry)  # #1056-defended: entries are positive, ABS anyway
        # Credit structure (short, qty<0): max loss = wing − net credit.
        # Debit structure (long, qty>0): max loss = net debit paid.
        if qty < 0:
            max_loss_pc = wing - net_entry
        else:
            max_loss_pc = net_entry
        # A degenerate geometry (credit ≥ wing) can't form a sane bound; skip.
        if max_loss_pc <= 0:
            return True, REASON_UNVALIDATABLE, {"wing_width": wing, "net_entry": net_entry}
        max_loss_dollars = max_loss_pc * abs_qty * MULTIPLIER

        detail = {
            "wing_width": round(wing, 4),
            "per_contract_mark": round(mark, 4),
            "implied_pl": round(upl, 2) if upl is not None else None,
            "max_loss_per_contract": round(max_loss_pc, 4),
            "max_loss_dollars": round(max_loss_dollars, 2),
            "tolerance": CLAMP_TOLERANCE,
        }

        # Check 1: |per-contract mark| cannot exceed the wing width.
        if abs(mark) > wing * (1.0 + CLAMP_TOLERANCE):
            return False, REASON_MARK_EXCEEDS_WING, detail

        # Check 2: implied dollar LOSS cannot exceed max structural loss.
        # Only a loss (upl < 0) can be impossible-on-the-downside; a large
        # gain is bounded separately by the wing check above.
        if upl is not None and upl < 0:
            implied_loss = -upl
            if implied_loss > max_loss_dollars * (1.0 + CLAMP_TOLERANCE):
                detail["implied_loss"] = round(implied_loss, 2)
                return False, REASON_LOSS_EXCEEDS_MAX, detail

        return True, REASON_OK, detail
    except Exception:
        # Never raise into the exit path — a clamp bug must not block exits.
        return True, REASON_UNVALIDATABLE, {}
