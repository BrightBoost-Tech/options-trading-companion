"""Authoritative Policy-Lab capital parsing.

Capital is evidence, not a default. A missing or invalid portfolio read cannot
be reinterpreted as a nominal $100,000 account (or as zero deployed capital).
"""

import math
from typing import Any, Dict, Optional, Tuple


class PolicyCapitalUnavailable(RuntimeError):
    """A cohort's actual capital could not be established."""


def normalize_capital(
    portfolio_row: Optional[Dict[str, Any]],
) -> Tuple[Optional[float], Optional[str]]:
    """Return positive finite cohort capital or a typed refusal reason.

    net_liq is authoritative whenever it is present and non-null. An invalid
    zero/non-finite/non-numeric net_liq does not fall through to cash.
    cash_balance is allowed only when net_liq is absent or null.
    """
    if not isinstance(portfolio_row, dict):
        return None, "portfolio_row_missing"
    if "net_liq" in portfolio_row and portfolio_row.get("net_liq") is not None:
        chosen = portfolio_row.get("net_liq")
    elif portfolio_row.get("cash_balance") is not None:
        chosen = portfolio_row.get("cash_balance")
    else:
        return None, "capital_absent"
    try:
        value = float(chosen)
    except (TypeError, ValueError):
        return None, "capital_non_numeric"
    if not math.isfinite(value):
        return None, "capital_non_finite"
    if value <= 0:
        return None, "capital_not_positive"
    return value, None


def require_capital(portfolio_row: Optional[Dict[str, Any]]) -> float:
    """Raise a typed error unless authoritative capital is usable."""
    value, reason = normalize_capital(portfolio_row)
    if reason is not None or value is None:
        raise PolicyCapitalUnavailable(reason or "capital_unavailable")
    return value


def require_cash_balance(portfolio_row: Optional[Dict[str, Any]]) -> float:
    """Return finite non-negative cash; never invent a missing cash balance."""
    if not isinstance(portfolio_row, dict):
        raise PolicyCapitalUnavailable("portfolio_row_missing")
    raw = portfolio_row.get("cash_balance")
    if raw is None:
        raise PolicyCapitalUnavailable("cash_balance_absent")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise PolicyCapitalUnavailable("cash_balance_non_numeric") from exc
    if not math.isfinite(value):
        raise PolicyCapitalUnavailable("cash_balance_non_finite")
    if value < 0:
        raise PolicyCapitalUnavailable("cash_balance_negative")
    return value
