"""
Trade economics — compute-on-read derivation of operator-facing display values.

D1 surfacing (2026-05-28). These are values the operator wants to see but that the
pipeline never formed or persisted: reward:risk, breakeven, and an expiration
payoff grid. They are PURELY INFORMATIONAL — nothing in the decision/sizing/exit/
ranking path consumes them. Computed on-read from the persisted suggestion row so
they never drift from the order.

Design choices (see docs/backlog.md D1, docs/loud_error_doctrine.md H15):

- Derived from PER-CONTRACT honest geometry (strikes parsed from the leg OCC
  symbols + net debit/credit from limit_price), NOT from the `max_loss_total` /
  `max_profit_total` totals. The totals are contracts-scaled and `max_loss_total`
  is convention-ambiguous on cohort clones (#3 territory) — per-contract geometry
  is contracts-independent and sidesteps that entirely. This is the H15
  "don't repurpose a value calibrated for another context" discipline applied.
- Only 2-leg vertical spreads (the structures the system emits) are computed.
  Anything else returns None and the caller simply renders nothing — never a
  wrong number.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# OCC option symbol: optional "O:" prefix, root, YYMMDD, C|P, 8-digit strike×1000.
_OCC_RE = re.compile(r"^(?:O:)?([A-Z]+)(\d{6})([CP])(\d{8})$")


def _parse_occ(symbol: Optional[str]) -> Optional[Dict[str, Any]]:
    """Parse an OCC option symbol into {root, expiry, type, strike}, or None."""
    if not symbol or not isinstance(symbol, str):
        return None
    m = _OCC_RE.match(symbol.strip())
    if not m:
        return None
    root, ymd, cp, strike8 = m.groups()
    return {
        "root": root,
        "expiry": ymd,
        "type": "call" if cp == "C" else "put",
        "strike": int(strike8) / 1000.0,
    }


def _round(x: Optional[float], n: int = 2) -> Optional[float]:
    return None if x is None else round(float(x), n)


def compute_trade_economics(suggestion: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Compute reward:risk, breakeven, and an expiration payoff grid for a
    2-leg vertical-spread suggestion. Returns None when not computable
    (non-vertical structure, missing strikes/price) — the caller renders nothing.

    All dollar values are PER CONTRACT (×100). Multiply by contracts for totals.
    """
    order_json = suggestion.get("order_json") or {}
    legs_raw = order_json.get("legs") or []

    parsed: List[Dict[str, Any]] = []
    for leg in legs_raw:
        info = _parse_occ(leg.get("symbol"))
        if info is None:
            continue
        info["side"] = str(leg.get("side") or "").lower()
        parsed.append(info)

    # Only 2-leg verticals are supported here. Iron condors (4-leg), single legs,
    # and anything we can't parse fall through to None.
    if len(parsed) != 2:
        return None

    long_leg = next((l for l in parsed if l["side"] == "buy"), None)
    short_leg = next((l for l in parsed if l["side"] == "sell"), None)
    if long_leg is None or short_leg is None:
        return None

    # A vertical has both legs the same option type.
    if long_leg["type"] != short_leg["type"]:
        return None
    opt_type = long_leg["type"]

    width = abs(long_leg["strike"] - short_leg["strike"])
    net = abs(float(order_json.get("limit_price") or 0.0))  # per-share net debit/credit
    if width <= 0 or net <= 0:
        return None

    strategy = str(suggestion.get("strategy") or "").upper()
    is_credit = "CREDIT" in strategy

    if is_credit:
        # Credit spread: collect `net`; risk is the rest of the width.
        max_profit = net * 100.0
        max_loss = (width - net) * 100.0
        # Breakeven sits at the short strike ± credit (short call: +, short put: −).
        if opt_type == "call":
            breakeven = short_leg["strike"] + net
        else:
            breakeven = short_leg["strike"] - net
        entry_cash = -net  # we received credit
    else:
        # Debit spread: pay `net`; max profit is the rest of the width.
        max_profit = (width - net) * 100.0
        max_loss = net * 100.0
        # Breakeven sits at the long strike ± debit (call: +, put: −).
        if opt_type == "call":
            breakeven = long_leg["strike"] + net
        else:
            breakeven = long_leg["strike"] - net
        entry_cash = net  # we paid debit

    reward_risk_ratio = (max_profit / max_loss) if max_loss > 0 else None

    # ── Expiration payoff grid (per contract) ───────────────────────────────
    # Generic intrinsic-value payoff so the same code serves debit & credit,
    # call & put: P/L = Σ(sign · intrinsic) − entry_cash, ×100.
    def _payoff_per_contract(spot: float) -> float:
        total = 0.0
        for leg in parsed:
            sign = 1.0 if leg["side"] == "buy" else -1.0
            if leg["type"] == "call":
                intrinsic = max(0.0, spot - leg["strike"])
            else:
                intrinsic = max(0.0, leg["strike"] - spot)
            total += sign * intrinsic
        return (total - entry_cash) * 100.0

    lo_strike = min(long_leg["strike"], short_leg["strike"])
    hi_strike = max(long_leg["strike"], short_leg["strike"])
    pad = max(width * 0.5, 0.01)
    price_points = sorted(
        {
            round(lo_strike - pad, 2),
            round(lo_strike, 2),
            round(breakeven, 2),
            round(hi_strike, 2),
            round(hi_strike + pad, 2),
        }
    )
    payoff_table = [
        {"underlying": p, "pl_per_contract": _round(_payoff_per_contract(p))}
        for p in price_points
        if p > 0
    ]

    return {
        "reward_risk_ratio": _round(reward_risk_ratio, 3),
        "breakeven": _round(breakeven),
        "max_profit_per_contract": _round(max_profit),
        "max_loss_per_contract": _round(max_loss),
        "width": _round(width),
        "net_entry": _round(net),
        "structure": "credit_spread" if is_credit else "debit_spread",
        "option_type": opt_type,
        "payoff_table": payoff_table,
    }
