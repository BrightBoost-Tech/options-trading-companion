"""Single shared full-count mark math for BOTH position mark readers (H13).

`paper_mark_to_market_service.refresh_marks` and
`intraday_risk_monitor._refresh_marks` MUST compute `current_mark` and
`unrealized_pl` through this one module so the two cannot diverge again.

Convention (#3, operator-pinned): `legs[].quantity` == the position contract
count (full-count). So the leg sum already spans all contracts, and
`unrealized_pl` is scaled exactly ONCE.

The pre-unification `intraday_risk_monitor` path treated `legs[].quantity` as a
per-spread unit (implicitly 1) and then multiplied the per-spread P&L by
`pos.quantity` a SECOND time — double-counting any multi-contract position
(F bdbe4d04: computed +$2,070 vs the correct +$30; the #987 payoff-bound guard
clamped it to the +$520 max-profit bound). `paper_mark_to_market_service`
already computed F correctly at full-count; this module makes both paths use
that one correct computation.

This module does the MARK MATH only (price aggregation → current_value →
per-contract mark + unrealized P&L). It is deliberately decoupled from the data
SOURCE: each caller supplies a `mid_for(occ_symbol) -> Optional[float]` resolver
(snapshot mids, or broker `current_price`), so the differing fetch paths stay in
their own modules while the arithmetic is shared.

The #987 `payoff_bounds` guard remains layered on top of `finalize_mark`'s
output at each call site and is NOT part of this module — it is the independent
catch; this module removes the cause.
"""

from typing import Any, Callable, Dict, List, Optional

MULTIPLIER = 100.0


def compute_current_value(
    legs: List[Dict[str, Any]],
    mid_for: Callable[[str], Optional[float]],
    pos_quantity: Any,
    multiplier: float = MULTIPLIER,
    failed_legs: Optional[List[str]] = None,
) -> Optional[float]:
    """Signed total current market value across ALL contracts of a multi-leg
    position, or None if any priceable leg lacks a usable mid (all-or-nothing,
    matching the pre-existing readers' contract).

    Full-count: each leg's `quantity` IS the contract count. `pos_quantity` is
    the fallback when a leg omits `quantity` (legacy rows). `side_mult` is +1 for
    buy/long legs and -1 for sell/short legs, so short legs subtract — the sum is
    a signed net market value.

    `failed_legs`, when provided, is appended with the OCC symbols that could not
    be priced (preserves the readers' per-leg failure observability).
    """
    legs = legs or []
    if not legs:
        return None
    leg_values: List[float] = []
    priceable = 0
    for leg in legs:
        if not isinstance(leg, dict):
            continue
        occ = leg.get("occ_symbol") or leg.get("symbol") or ""
        if not occ:
            continue
        priceable += 1
        mid = mid_for(occ)
        if mid is None or mid <= 0:
            if failed_legs is not None:
                failed_legs.append(occ)
            continue
        leg_qty = abs(float(leg.get("quantity") or pos_quantity or 1))
        action = str(leg.get("action") or leg.get("side") or "buy").lower()
        side_mult = 1.0 if action in ("buy", "long") else -1.0
        leg_values.append(mid * multiplier * leg_qty * side_mult)

    if priceable == 0:
        return None
    if failed_legs:
        # At least one priceable leg could not be priced → all-or-nothing None.
        return None
    return sum(leg_values)


def finalize_mark(
    quantity: Any,
    avg_entry_price: Any,
    current_value: float,
    multiplier: float = MULTIPLIER,
):
    """Turn a signed total `current_value` into (per_contract_mark,
    unrealized_pl), scaled exactly ONCE.

    - entry_value = avg_entry_price × |quantity| × multiplier  (total cost/credit)
    - debit (qty > 0):  unrealized = current_value − entry_value
    - credit (qty < 0): unrealized = entry_value − |current_value|
      (avg_entry_price stores the absolute per-spread net premium for both)
    - per_contract_mark = current_value / (|quantity| × multiplier)

    This is the single source of truth for the P&L + mark; both readers call it.
    """
    qty = float(quantity or 0)
    qty_abs = abs(qty)
    # qty == 0 (closed / in-flight close): no contracts → no value, no P&L.
    if qty_abs == 0:
        return 0.0, 0.0
    entry_value = float(avg_entry_price or 0) * qty_abs * multiplier
    if qty < 0:
        unrealized = entry_value - abs(current_value)
    else:
        unrealized = current_value - entry_value
    per_contract_mark = current_value / (qty_abs * multiplier) if qty_abs > 0 else 0.0
    return per_contract_mark, unrealized
