"""
Shared outcome normalization for learning feedback loops.

Provides a consistent classification of trade outcomes (win/loss/breakeven)
that works identically for both paper and live trades. This replaces ad hoc
outcome_type checks scattered across autotune and analytics code.
"""

from typing import Any, Dict, Optional


def classify_outcome(record: Dict[str, Any]) -> str:
    """
    Derive a normalized win/loss/breakeven classification from a
    learning_feedback_loops record.

    Resolution order:
      1. details_json.pnl_outcome  (explicitly set during ingest)
      2. pnl_realized sign         (fallback derivation)

    Returns one of: "win", "loss", "breakeven"
    """
    # Prefer the explicit classification stored at ingest time
    details = record.get("details_json") or {}
    pnl_outcome = details.get("pnl_outcome")
    if pnl_outcome in ("win", "loss", "breakeven"):
        return pnl_outcome

    # Fallback: derive from pnl_realized
    pnl = record.get("pnl_realized")
    if pnl is None:
        return "breakeven"
    pnl = float(pnl)
    if pnl > 0:
        return "win"
    elif pnl < 0:
        return "loss"
    return "breakeven"
