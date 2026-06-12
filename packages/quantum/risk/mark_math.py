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

import logging
import os
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

MULTIPLIER = 100.0


def usable_mid(bid: Any, ask: Any, fallback: float = 0.0) -> Optional[float]:
    """Mid of a two-sided quote — or ``None`` when the quote is DEGENERATE.

    06-12 QQQ phantom: at the 13:30Z bell C750 quoted **0.76 × 14.09** (true
    value ~8.8). Its arithmetic 'mid' 7.425 understated the leg by ~$1.37,
    summed the condor to a fabricated −0.65 mark (true ~−1.9), and
    target_profit fired on a phantom +$96. A quote that wide isn't a price —
    treating its midpoint as one is fabrication, the same never-fabricate
    class as the dead-leg partial sum (#1035).

    Degenerate iff BOTH: width > MARK_DEGENERATE_ABS_WIDTH (default $1.00)
    AND width/mid > MARK_DEGENERATE_REL_SPREAD (default 1.0 = 100%). The
    AND keeps legitimately-wide cheap options (0.05×0.15: 200% rel but 10¢
    wide) and tight expensive ones (6.14×7.23: $1.09 wide but 16% rel)
    priceable. Returns None → the leg counts as FAILED in
    compute_current_value → all-or-nothing unpriceable handling (TP never
    fires; stop alerts degraded).

    One-sided / empty quotes keep the caller's legacy ``fallback`` behavior
    (typically the snapshot's own mid field, or 0 → failed leg).
    """
    try:
        b = float(bid or 0)
        a = float(ask or 0)
    except (TypeError, ValueError):
        return float(fallback or 0)
    if b > 0 and a > 0:
        width = a - b
        mid = (a + b) / 2.0
        try:
            abs_floor = float(os.environ.get("MARK_DEGENERATE_ABS_WIDTH", "1.0"))
            rel_max = float(os.environ.get("MARK_DEGENERATE_REL_SPREAD", "1.0"))
        except ValueError:
            abs_floor, rel_max = 1.0, 1.0
        if mid > 0 and width > abs_floor and (width / mid) > rel_max:
            logger.warning(
                "[MARK_MATH] degenerate quote refused: bid=%.2f ask=%.2f "
                "(width=%.2f, %.0f%% of mid) — not a price, leg treated as "
                "unpriceable", b, a, width, 100.0 * width / mid,
            )
            return None
        return mid
    return float(fallback or 0)


def compute_current_value(
    legs: List[Dict[str, Any]],
    mid_for: Callable[[str], Optional[float]],
    pos_quantity: Any,
    multiplier: float = MULTIPLIER,
    failed_legs: Optional[List[str]] = None,
    allow_partial: bool = False,
) -> Optional[float]:
    """Signed total current market value across ALL contracts of a multi-leg
    position, or None if any priceable leg lacks a usable mid.

    Full-count: each leg's `quantity` IS the contract count. `pos_quantity` is
    the fallback when a leg omits `quantity` (legacy rows). `side_mult` is +1 for
    buy/long legs and -1 for sell/short legs, so short legs subtract — the sum is
    a signed net market value.

    `failed_legs`, when provided, is appended with the OCC symbols that could not
    be priced (preserves the readers' per-leg failure observability).

    FAIL-CLOSED BY DEFAULT (2026-06-08, the never-fabricate bug-class fix): if
    ANY priceable leg lacks a usable mid, returns None — never a silent partial
    sum over only the legs that quoted. The old default silently partial-summed
    unless the caller passed `failed_legs` AND checked it; the one caller that
    forgot (intraday_risk_monitor._refresh_marks) produced the 2026-06-08
    phantom-mark fire (a dropped leg inflated a spread to a fabricated +$325).
    Making the safe behavior the DEFAULT closes the footgun for every future
    caller. A caller that genuinely wants best-effort must opt in explicitly
    with `allow_partial=True`. (All current callers already pass `failed_legs`
    and treat its non-emptiness as None — this flip is byte-identical for them.)
    """
    legs = legs or []
    if not legs:
        return None
    leg_values: List[float] = []
    priceable = 0
    any_failed = False
    for leg in legs:
        if not isinstance(leg, dict):
            continue
        occ = leg.get("occ_symbol") or leg.get("symbol") or ""
        if not occ:
            continue
        priceable += 1
        mid = mid_for(occ)
        if mid is None or mid <= 0:
            any_failed = True
            if failed_legs is not None:
                failed_legs.append(occ)
            continue
        leg_qty = abs(float(leg.get("quantity") or pos_quantity or 1))
        action = str(leg.get("action") or leg.get("side") or "buy").lower()
        side_mult = 1.0 if action in ("buy", "long") else -1.0
        leg_values.append(mid * multiplier * leg_qty * side_mult)

    if priceable == 0:
        return None
    if any_failed and not allow_partial:
        # At least one priceable leg could not be priced → fail-closed None
        # (never a fabricated partial). Opt into best-effort via allow_partial.
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
