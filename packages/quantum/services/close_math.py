"""
Canonical realized-P&L computation for closing option positions.

PR #6 (close-path consolidation) lifts the sign-convention logic that
post-PR #790 lives inline in `alpaca_order_handler._close_position_on_fill`
into a pure, leg-level function so all 4 close handlers can produce
identical realized_pl values.

Design notes
    - Leg-level, not parent-level. This function derives realized_pl
      from the summed signed cash flows of the close legs. It does
      NOT depend on Alpaca's multi-leg parent `filled_avg_price`
      sign convention — which was the mechanism behind the 2026-04-17
      PYPL cfe69b28 −$3,324 bug that PR #790 fixed inline in the
      reconciler. Leg-level derivation is robust to upstream
      convention changes.

    - Pure. No I/O, no Alpaca client calls, no Supabase. Given the
      same inputs it always produces the same output. That's the
      whole point — tests can pin it forever.

    - Scope. Handles all-or-nothing closes only. Partial fills
      (leg qtys mismatched, or filled_qty ≠ position qty) raise
      PartialFillDetected. Callers handle partial-fill recovery
      out of band (create severity=critical risk_alert, no close
      action). See Gap E of the PR #6 scope discussion.

    - Canonical formula. Per our account's cash perspective:
          entry_cash_flow  = ±(entry_price × qty × multiplier)
              sign is negative for 'debit' (we paid),
              positive for 'credit' (we received).
          close_cash_flow  = Σ over close_legs of
              (+1 if action/side == 'sell' else −1)
              × filled_avg_price × filled_qty × multiplier.
          realized_pl = entry_cash_flow + close_cash_flow.
      Works symmetrically for long debit and short credit spreads.
"""

from decimal import Decimal
from typing import Any, Dict, Iterable, Literal


class PartialFillDetected(Exception):
    """Raised when close_legs indicate a partial fill.

    PR #6 scope is all-or-nothing close reconciliation. Partial fills
    require their own recovery flow (typically: critical risk_alert,
    no helper invocation, operator review) and are explicitly out of
    scope. Callers that catch this exception must NOT invoke
    close_position_shared — attempting to close a position on a
    partial fill would lose the in-flight unfilled quantity.
    """


class MalformedFillData(Exception):
    """Raised when fill data has neither populated legs nor usable
    parent-level fill fields.

    Expected to fire only on historical / edge-case inputs: e.g.
    internal-paper-era paper_orders rows with `broker_response=NULL`
    routing through orphan_fill_repair. Callers MUST catch this and
    write a severity='critical' risk_alert for operator review;
    silent fall-through would compute realized_pl on garbage input.

    On 2026-04-22 the production count of such rows was zero; this
    exception is defensive, not active-code-path protection. If it
    ever fires in production, that's a signal that something stale
    crossed the orphan-repair boundary.
    """


_SELL_ACTIONS = frozenset({"sell", "sell_to_open", "sell_to_close", "short"})
_BUY_ACTIONS = frozenset({"buy", "buy_to_open", "buy_to_close", "long"})


def _leg_action(leg: Dict[str, Any]) -> str:
    """Accept either `action` (position.legs convention) or `side`
    (Alpaca order leg convention). Normalize to lowercase."""
    raw = leg.get("action") or leg.get("side") or ""
    return str(raw).strip().lower()


def _leg_sign(leg: Dict[str, Any]) -> Decimal:
    """+1 for sell legs (cash IN), −1 for buy legs (cash OUT).

    Partial-fill note: action semantics here are independent of
    whether the leg fully filled. Partial-fill detection happens
    separately via the qty equality check.
    """
    action = _leg_action(leg)
    if action in _SELL_ACTIONS:
        return Decimal("1")
    if action in _BUY_ACTIONS:
        return Decimal("-1")
    raise ValueError(
        f"compute_realized_pl: unrecognized leg action/side "
        f"{action!r}. Accepted: 'buy', 'sell', 'buy_to_open', "
        f"'buy_to_close', 'sell_to_open', 'sell_to_close'."
    )


def _as_decimal(value: Any, field: str) -> Decimal:
    """Convert numeric input (int, float, str, Decimal) to Decimal
    via string to avoid float imprecision."""
    if value is None:
        raise ValueError(f"compute_realized_pl: {field} is None")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def compute_realized_pl(
    close_legs: Iterable[Dict[str, Any]],
    entry_price: Decimal,
    qty: int,
    spread_type: Literal["debit", "credit"],
    multiplier: int = 100,
) -> Decimal:
    """Compute realized P&L for an all-or-nothing option close.

    Args:
        close_legs: Iterable of leg-fill dicts. Each leg must have:
            - 'action' (or 'side'): 'buy'|'sell' or 'buy_to_close'/
              'sell_to_close' etc.
            - 'filled_avg_price': per-contract fill price (Decimal
              or numeric coercible).
            - 'filled_qty': contracts filled on this leg; MUST equal
              `qty` for all legs or PartialFillDetected is raised.
        entry_price: Unsigned per-spread/contract entry price. For
            a long debit spread, the debit amount paid. For a short
            credit spread, the credit amount received. NEVER signed.
        qty: Number of spreads/contracts at the position level.
            Always positive. Signed `quantity` in paper_positions
            (negative for shorts) should be abs()'d before passing.
        spread_type: 'debit' for long positions (we paid to enter),
            'credit' for short positions (we received on entry).
        multiplier: Contract multiplier (default 100 for equity
            options).

    Returns:
        Realized P&L as Decimal. Negative = loss, positive = gain.

    Raises:
        PartialFillDetected: If any leg's filled_qty differs from
            the others or from the `qty` argument.
        ValueError: If a leg has an unrecognized action/side string
            or if entry_price is None.

    Canonical reference case — PYPL cfe69b28 (2026-04-17):
        close_legs = [
            {'action': 'sell', 'filled_qty': 6, 'filled_avg_price': 5.05},
            {'action': 'buy',  'filled_qty': 6, 'filled_avg_price': 2.45},
        ]
        compute_realized_pl(close_legs, Decimal('2.94'), 6, 'debit')
        == Decimal('-204.00')

        Pre-PR #790 math produced Decimal('-3324') for the same
        inputs by failing to handle Alpaca's mleg parent
        filled_avg_price sign convention. The leg-level derivation
        here structurally prevents that class of bug.
    """
    legs = list(close_legs)
    if not legs:
        raise ValueError(
            "compute_realized_pl: close_legs is empty. A close with "
            "no legs cannot produce realized_pl; callers should not "
            "invoke this function in that case."
        )

    # Partial-fill detection. All leg filled_qty values must equal
    # `qty` for an all-or-nothing close.
    expected_qty = Decimal(qty)
    if expected_qty <= 0:
        raise ValueError(
            f"compute_realized_pl: qty must be positive, got {qty}. "
            f"Signed position quantity should be abs()'d before passing."
        )
    for leg in legs:
        leg_qty = _as_decimal(leg.get("filled_qty"), "leg.filled_qty")
        if leg_qty != expected_qty:
            raise PartialFillDetected(
                f"Partial fill detected on close_legs: leg "
                f"{leg.get('symbol', '?')} filled_qty={leg_qty} but "
                f"position qty={qty}. PR #6 close helper handles "
                f"all-or-nothing closes only. Caller must create a "
                f"severity=critical risk_alert and skip close."
            )

    entry = _as_decimal(entry_price, "entry_price")
    mult = Decimal(multiplier)

    # Entry cash flow (signed by our account's perspective).
    entry_cash = entry * expected_qty * mult
    if spread_type == "debit":
        entry_cash = -entry_cash
    elif spread_type == "credit":
        pass  # already positive; we received on entry
    else:
        raise ValueError(
            f"compute_realized_pl: spread_type must be 'debit' or "
            f"'credit', got {spread_type!r}."
        )

    # Close cash flow (signed via leg action/side).
    close_cash = Decimal("0")
    for leg in legs:
        sign = _leg_sign(leg)
        price = _as_decimal(leg.get("filled_avg_price"), "leg.filled_avg_price")
        leg_qty = _as_decimal(leg.get("filled_qty"), "leg.filled_qty")
        close_cash += sign * price * leg_qty * mult

    return (entry_cash + close_cash).quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# extract_close_legs — shared utility for all 4 close handlers
# ---------------------------------------------------------------------------


def extract_close_legs(source: Dict[str, Any]) -> list:
    """Normalize Alpaca-shape fill data into a LegFill list that
    compute_realized_pl() can consume.

    Accepts input from either:
      - AlpacaClient.get_order() response (live reconciler fetch)
      - paper_orders.broker_response jsonb (stored fill data)
    Both have identical shape — verified 2026-04-22: broker_response
    stores the output of AlpacaClient._serialize_order verbatim.

    Routing rule is STRUCTURAL, not string-based:
      - len(source['legs']) >= 1  →  use legs directly. Each leg
        already carries the fields compute_realized_pl needs
        (symbol, side, filled_qty, filled_avg_price). No mleg/
        order_class string check needed — the count IS the signal.
      - len(source['legs']) == 0  →  synthesize a single-leg list
        from parent-level `symbol`, `side`, `filled_qty`,
        `filled_avg_price`. Covers simple (non-mleg) option orders
        where Alpaca emits the fill data at the parent level.

    Trust invariants (callers enforce upstream):
      - `source` represents a filled close order for an option
        position. Stock/crypto/equity orders are filtered out before
        reaching here.
      - Single-leg orders that ARE option orders have enough
        parent-level metadata to synthesize a valid LegFill.

    Output shape — list of dicts with canonical keys:
      {
        'symbol':          str (O:-prefixed, passed through from source;
                                no re-normalization),
        'action':          str ('buy'|'sell'|'buy_to_close'|etc.),
        'filled_qty':      numeric,
        'filled_avg_price': numeric,
      }

    Raises:
      PartialFillDetected — leg filled_qty values mismatched, OR any
        leg's filled_qty differs from the parent filled_qty, OR
        parent filled_qty < parent qty for the single-leg synthesis
        path, OR any leg has filled_qty == 0, OR leg has filled_qty
        > 0 but filled_avg_price is None.
      MalformedFillData — no legs AND no usable parent fill data.
        Historical edge case; defensive. See class docstring.

    This function does NOT modify symbol normalization (no
    alpaca_to_polygon call, no lstrip). The upstream serializer
    (_serialize_order in alpaca_client.py) emits O:-prefixed option
    symbols; we pass them through unchanged. Duplicating
    normalization here risks the double-prefix class of bug that
    PR #792 surfaced in ghost_position_sweep (O: asymmetry).
    """
    if not isinstance(source, dict):
        raise MalformedFillData(
            f"extract_close_legs: expected dict, got "
            f"{type(source).__name__}."
        )

    legs = source.get("legs") or []

    if legs:
        return _extract_from_legs(source, legs)
    return _synthesize_single_leg(source)


def _extract_from_legs(source: Dict[str, Any], legs: list) -> list:
    """Multi-leg path. Validate + return canonical LegFill list.

    Validates:
      - No leg has filled_qty=0 (partial)
      - All legs have the same filled_qty (they fill as a package)
      - If parent filled_qty is provided, leg filled_qty == parent
      - Every filled leg has filled_avg_price (cannot be None)
    """
    if not legs:
        raise MalformedFillData(
            "extract_close_legs._extract_from_legs called with empty "
            "legs list — upstream routing bug."
        )

    leg_qtys = [leg.get("filled_qty") for leg in legs]
    # A leg with filled_qty=None means no fill data → treat as partial.
    if any(q is None for q in leg_qtys):
        raise PartialFillDetected(
            f"extract_close_legs: leg filled_qty is None on at least "
            f"one leg: {leg_qtys}. Order not fully resolved."
        )
    if any(Decimal(str(q)) == 0 for q in leg_qtys):
        raise PartialFillDetected(
            f"extract_close_legs: leg filled_qty=0 detected on at "
            f"least one leg: {leg_qtys}. Order not fully filled."
        )
    qty_set = {Decimal(str(q)) for q in leg_qtys}
    if len(qty_set) > 1:
        raise PartialFillDetected(
            f"extract_close_legs: leg filled_qtys differ: {leg_qtys}. "
            f"Multi-leg orders fill as a package — mismatched qtys "
            f"indicate a partial leg fill."
        )

    # Parent filled_qty consistency (if provided).
    parent_filled_qty = source.get("filled_qty")
    if parent_filled_qty is not None:
        leg_qty_val = Decimal(str(leg_qtys[0]))
        parent_qty_val = Decimal(str(parent_filled_qty))
        if parent_qty_val > 0 and leg_qty_val != parent_qty_val:
            raise PartialFillDetected(
                f"extract_close_legs: parent filled_qty="
                f"{parent_filled_qty} differs from leg filled_qty="
                f"{leg_qtys[0]}. Alpaca shape inconsistency."
            )

    # Build canonical LegFill list. Pass symbol through verbatim —
    # no re-normalization (see PR #792 prefix asymmetry lesson).
    result = []
    for leg in legs:
        filled_avg_price = leg.get("filled_avg_price")
        if filled_avg_price is None:
            raise PartialFillDetected(
                f"extract_close_legs: leg {leg.get('symbol', '?')} has "
                f"filled_qty={leg.get('filled_qty')} but "
                f"filled_avg_price is None. Inconsistent fill data."
            )
        action = leg.get("action") or leg.get("side")
        if not action:
            raise MalformedFillData(
                f"extract_close_legs: leg {leg.get('symbol', '?')} has "
                f"neither 'action' nor 'side' field."
            )
        result.append({
            "symbol": leg.get("symbol"),
            "action": action,
            "filled_qty": leg["filled_qty"],
            "filled_avg_price": filled_avg_price,
        })
    return result


def _synthesize_single_leg(source: Dict[str, Any]) -> list:
    """Single-leg synthesis. Parent-level fields become the LegFill.

    Validates:
      - Parent has symbol + side
      - Parent has filled_qty > 0 (not unfilled)
      - Parent has filled_avg_price (not None)
      - If parent qty is provided, filled_qty >= qty (not partial)
    """
    parent_symbol = source.get("symbol")
    parent_side = source.get("side") or source.get("action")
    parent_filled_qty = source.get("filled_qty")
    parent_filled_avg = source.get("filled_avg_price")
    parent_qty = source.get("qty")

    if not parent_symbol or not parent_side:
        raise MalformedFillData(
            f"extract_close_legs: no legs, and parent missing "
            f"symbol/side. symbol={parent_symbol!r}, "
            f"side={parent_side!r}. Cannot synthesize single-leg."
        )
    if parent_filled_qty is None or Decimal(str(parent_filled_qty)) == 0:
        raise PartialFillDetected(
            f"extract_close_legs: single-leg order has filled_qty="
            f"{parent_filled_qty}. Not filled."
        )
    if parent_filled_avg is None:
        raise PartialFillDetected(
            f"extract_close_legs: single-leg order has "
            f"filled_qty={parent_filled_qty} but "
            f"filled_avg_price is None. Inconsistent fill data."
        )
    if parent_qty is not None:
        filled_val = Decimal(str(parent_filled_qty))
        qty_val = Decimal(str(parent_qty))
        if filled_val < qty_val:
            raise PartialFillDetected(
                f"extract_close_legs: single-leg partial fill. "
                f"qty={parent_qty}, filled_qty={parent_filled_qty}."
            )

    return [{
        "symbol": parent_symbol,
        "action": parent_side,
        "filled_qty": parent_filled_qty,
        "filled_avg_price": parent_filled_avg,
    }]
