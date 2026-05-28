"""Convention-agnostic payoff-bound guard for debit-spread unrealized P&L.

This is a GUARD, not a mark-computation fix. It bounds an *already-computed*
``unrealized_pl`` to the spread's physical payoff envelope and reports when a
mark is impossible. It deliberately does NOT recompute the mark, does NOT
change any mark math, and does NOT make F read its correct −$45 — that is the
separate #3 work (pin the ``legs.quantity`` convention, fix the disagreeing
writers, normalize the data, then unify the two mark readers).

Why a guard at all: ``legs.quantity`` has no uniform persistence convention
(F bdbe4d04 stores full-count 5; the CSX BUG-A position d077c93d stores
per-spread 1 with pos.quantity 4). No scalar mark formula is correct for both
shapes, and both mark paths (``intraday_risk_monitor._refresh_marks`` and
``paper_mark_to_market_service.refresh_marks``) can therefore emit impossible
values. This guard catches those at finalisation, before any exit decision or
loss/PnL envelope input consumes them.

Convention-independence is the whole point: the bound is computed ONLY from
fields whose meaning does not depend on the leg-quantity convention —
position-level ``quantity`` (the reliable contract count), ``avg_entry_price``
(per-spread net debit) and the leg STRIKES (a strike is a strike regardless of
how leg quantity is stored). It never reads ``legs[].quantity``.

For a long (debit) 2-leg vertical:

    max_loss  = -entry_value
    max_profit = width * contracts * 100 - entry_value
    entry_value = avg_entry_price * contracts * 100

and ``unrealized_pl`` must lie within ``[max_loss, max_profit]``. A value
outside that range cannot be produced by any real spread at any price — it is
a mark-scale corruption. The caller clamps it to the nearest bound (so it can
no longer poison envelope inputs) and emits a loud critical alert carrying the
raw value. Clamping is safe in the payoff sense: the clamped value sits at a
real payoff extreme, so it can never imply an exit *beyond* what the true
payoff allows.

Single shared implementation used by BOTH mark sites, to avoid a
parallel-architecture split (loud-error doctrine H13).
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


ALERT_TYPE = "mark_payoff_bound_violation"


@dataclass
class PayoffBoundResult:
    """Outcome of a payoff-bound evaluation.

    ``applicable`` is False for anything that is not a long 2-leg vertical
    with usable inputs (credit spreads, iron condors, single-leg, calendars,
    straddles, missing strikes, etc.) — those are returned untouched because
    their payoff bounds differ and are out of scope for this guard.
    """

    applicable: bool
    in_bounds: bool
    raw_value: float
    clamped_value: float
    max_loss: Optional[float] = None
    max_profit: Optional[float] = None
    width: Optional[float] = None
    contracts: Optional[float] = None
    entry_value: Optional[float] = None
    violated_side: Optional[str] = None  # "below_max_loss" | "above_max_profit"


def _debit_vertical_strikes(legs: List[Any], qty: float) -> Optional[Tuple[float, float]]:
    """Return the two strikes IFF ``legs`` is a long 2-leg vertical (exactly
    one buy + one sell leg, both with numeric strikes). Otherwise None.

    Note: this inspects leg ``action`` and ``strike`` only — never
    ``quantity`` — so it is convention-agnostic.
    """
    dict_legs = [l for l in legs if isinstance(l, dict)]
    if len(dict_legs) != 2:
        return None
    actions = sorted((str(l.get("action", "")).lower() for l in dict_legs))
    if actions != ["buy", "sell"]:
        return None
    strikes: List[float] = []
    for l in dict_legs:
        s = l.get("strike")
        if s is None:
            return None
        try:
            strikes.append(float(s))
        except (TypeError, ValueError):
            return None
    return (strikes[0], strikes[1])


def evaluate_payoff_bound(pos: Dict[str, Any], unrealized_pl: float) -> PayoffBoundResult:
    """Evaluate ``unrealized_pl`` against the debit-spread payoff bound for
    ``pos``. Pure: no I/O, no mutation, no alert. Returns a
    :class:`PayoffBoundResult`. Convention-agnostic (uses pos.quantity +
    strikes + avg_entry_price; never legs.quantity)."""
    na = PayoffBoundResult(
        applicable=False, in_bounds=True,
        raw_value=unrealized_pl, clamped_value=unrealized_pl,
    )
    try:
        qty = float(pos.get("quantity") or 0)
    except (TypeError, ValueError):
        return na
    # Defined for LONG (debit) spreads only — credit / IC bounds differ.
    if qty <= 0:
        return na

    strikes = _debit_vertical_strikes(pos.get("legs") or [], qty)
    if strikes is None:
        return na
    width = abs(strikes[0] - strikes[1])
    if width <= 0:
        return na

    try:
        avg_entry = float(pos.get("avg_entry_price") or 0)
    except (TypeError, ValueError):
        return na

    contracts = abs(qty)
    entry_value = avg_entry * contracts * 100.0
    if entry_value <= 0:
        return na

    max_loss = -entry_value
    max_profit = width * contracts * 100.0 - entry_value

    common = dict(
        applicable=True, raw_value=unrealized_pl,
        max_loss=max_loss, max_profit=max_profit,
        width=width, contracts=contracts, entry_value=entry_value,
    )
    if unrealized_pl < max_loss:
        return PayoffBoundResult(
            in_bounds=False, clamped_value=max_loss,
            violated_side="below_max_loss", **common,
        )
    if unrealized_pl > max_profit:
        return PayoffBoundResult(
            in_bounds=False, clamped_value=max_profit,
            violated_side="above_max_profit", **common,
        )
    return PayoffBoundResult(in_bounds=True, clamped_value=unrealized_pl, **common)


def payoff_bound_alert_fields(
    pos: Dict[str, Any], result: PayoffBoundResult, source: str
) -> Dict[str, Any]:
    """Build the shared alert payload (alert_type / severity / message /
    metadata) for a bound violation, so both call sites emit an identical
    shape through their own alert primitive. Caller supplies user_id /
    position_id / symbol to its alert function."""
    return {
        "alert_type": ALERT_TYPE,
        "severity": "critical",
        "message": (
            f"unrealized_pl ${result.raw_value:.2f} for "
            f"{pos.get('symbol')} is outside the debit-spread payoff bound "
            f"[${result.max_loss:.2f}, ${result.max_profit:.2f}] "
            f"({result.violated_side}); clamped to "
            f"${result.clamped_value:.2f}. Impossible mark — likely "
            f"mark-scale corruption (legs.quantity convention split, #3). "
            f"Source: {source}."
        ),
        "metadata": {
            "source": source,
            "raw_unrealized_pl": result.raw_value,
            "clamped_unrealized_pl": result.clamped_value,
            "max_loss": result.max_loss,
            "max_profit": result.max_profit,
            "violated_side": result.violated_side,
            "width": result.width,
            "contracts": result.contracts,
            "entry_value": result.entry_value,
            "doctrine_ref": (
                "H-series loud-error; payoff-bound guard; "
                "#3 legs.quantity convention split"
            ),
        },
    }
