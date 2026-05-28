"""Full-count `legs.quantity` invariant enforcement at the persisted-write seam (#3).

Convention (operator-pinned): for every leg of a vertical / iron-condor /
single-leg position, ``leg.quantity == abs(pos.quantity)``. Verified Step 1d:
there are NO by-design unequal-leg structures in the strategy registry
(debit/credit verticals, iron condors and single legs all assign a uniform leg
quantity equal to the contract count; there are no ratio spreads). The invariant
is therefore universal — no structure needs exempting.

``coerce_legs_to_full_count`` enforces it at the authoritative persisted-legs
writer (the paper_endpoints fill-commit seams, which fire on ANY fill — champion
or cohort clone). On mismatch it returns the offending legs as ``violations`` (so
the caller can alert LOUDLY — an upstream emitter regressed) AND returns the legs
coerced to ``abs(pos.quantity)`` so the stored position is always
full-count-correct regardless of what the upstream writer emitted.

Coerce-and-alert is preferred over rejecting the fill: a legitimate trade must
not be blocked. For legitimate current fills (build_midday_order_json /
_suggestion_to_ticket already emit full-count) coercion is a NO-OP and
``violations`` is empty.

This is the CAUSE-side prevention. The #987 ``payoff_bounds`` guard remains the
independent CATCH at the mark readers.
"""

from typing import Any, Dict, List, Tuple

ALERT_TYPE = "legs_quantity_convention_violation"


def _abs_int(value: Any) -> int:
    """abs(round(float(value))) or 0 on any non-numeric/None."""
    try:
        return abs(int(round(float(value))))
    except (TypeError, ValueError):
        return 0


def coerce_legs_to_full_count(
    legs: List[Dict[str, Any]],
    pos_quantity: Any,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Return ``(coerced_legs, violations)``.

    Each dict leg's ``quantity`` is set to ``abs(pos_quantity)`` (the reliable
    contract count). ``violations`` lists the legs whose stored quantity differed
    (each: ``{symbol, stored_quantity, expected}``) — non-empty means an upstream
    writer emitted a non-full-count value and the caller should alert.

    NO-OP when every leg already equals ``abs(pos_quantity)`` (violations empty,
    leg values unchanged). When ``pos_quantity`` is 0/None/unparseable, returns
    the legs untouched with no violations (nothing reliable to coerce toward —
    e.g. a closed position; the live invariant only applies to open fills).
    """
    full = _abs_int(pos_quantity)
    if full <= 0:
        return list(legs or []), []

    coerced: List[Dict[str, Any]] = []
    violations: List[Dict[str, Any]] = []
    for leg in legs or []:
        if not isinstance(leg, dict):
            coerced.append(leg)
            continue
        stored = leg.get("quantity")
        if _abs_int(stored) != full:
            violations.append({
                "symbol": leg.get("symbol") or leg.get("occ_symbol"),
                "stored_quantity": stored,
                "expected": full,
            })
            coerced.append({**leg, "quantity": full})
        else:
            coerced.append(leg)
    return coerced, violations
