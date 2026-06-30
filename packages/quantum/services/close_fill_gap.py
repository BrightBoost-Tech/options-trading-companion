"""
Close-fill-gap instrumentation (ADDITIVE, observe-only).

Phase-3 PRECURSOR. This module RECORDS — it never decides. It exists so the
deferred Phase-3 work (exit-trigger basis calibration) can be made data-driven
instead of guessed: on every close we capture the gap between

  * ``cross`` — the full-cross executable estimate computed at STAGE time
    (``paper_exit_evaluator._corroborate_close_stage`` -> ``achievable_close``);
    this is the basis the envelope/close trigger fires on, and
  * ``mid``  — the triggering mark (the spread mid that the decision used), and
  * ``fill`` — the marketable-limit fill actually obtained at the broker (or the
    executable internal fill for shadow/internal closes).

The slippage location is reported as

    gap_fraction = (fill - cross) / (mid - cross)

so 0.0 means the close filled right at the conservative full-cross estimate and
1.0 means it filled all the way out at the optimistic mid. (SOFI 06-30:
cross 1.31 / mid 1.525 / fill 1.36 -> ~0.23.)

NOTHING in this module changes a close decision, the envelope, the trigger
basis, force-close logic, or sizing. Every public function is pure or
best-effort and never raises into the close path. There is no flag (pure
observability); the call sites invoke it unconditionally for force-close AND
normal closes alike.

Threading: ``cross`` + ``mid`` are stamped onto the close order's EXISTING
``order_json`` JSONB (no schema migration) at stage time and read back at the
fill/reconcile point together with the fill price. Older orders without the
stamp simply log fill-only (``gap_fraction=NA``).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# order_json keys used to thread/persist the triple. Namespaced so they never
# collide with the existing fill_quality / fill_mid_reference keys.
CROSS_KEY = "close_fill_gap_cross"
MID_KEY = "close_fill_gap_mid"
FILL_KEY = "close_fill_gap_fill"
GAP_KEY = "close_fill_gap_fraction"

LOG_PREFIX = "[CLOSE_FILL_GAP]"


def _coerce(value: Any) -> Optional[float]:
    """float() or None — never raises. Empty/None/garbage -> None."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def compute_gap_fraction(
    cross: Any, mid: Any, fill: Any
) -> Optional[float]:
    """gap_fraction = (fill - cross) / (mid - cross).

    Returns None when any of cross/mid/fill is missing/uncoercible, OR when
    mid == cross (degenerate — would divide by zero). Never raises.
    """
    c = _coerce(cross)
    m = _coerce(mid)
    f = _coerce(fill)
    if c is None or m is None or f is None:
        return None
    denom = m - c
    if denom == 0:
        return None
    return (f - c) / denom


def read_stamp(order_json: Optional[Dict[str, Any]]) -> Tuple[Optional[float], Optional[float]]:
    """Read the stage-stamped (cross, mid) back off a close order's order_json.

    Missing keys / non-dict input -> (None, None). Never raises.
    """
    oj = order_json if isinstance(order_json, dict) else {}
    return _coerce(oj.get(CROSS_KEY)), _coerce(oj.get(MID_KEY))


def stamp_payload(
    cross: Any = None, mid: Any = None, fill: Any = None
) -> Dict[str, Any]:
    """Build the order_json persistence payload {cross, mid, fill, gap_fraction}.

    Values are coerced to float (or None). gap_fraction is computed from the
    triple. Intended to be merged into an EXISTING order_json dict (no schema
    migration). Never raises.
    """
    c = _coerce(cross)
    m = _coerce(mid)
    f = _coerce(fill)
    return {
        CROSS_KEY: c,
        MID_KEY: m,
        FILL_KEY: f,
        GAP_KEY: compute_gap_fraction(c, m, f),
    }


def _gap_display(cross: Any, mid: Any, gap_fraction: Optional[float]) -> str:
    """Render gap_fraction for the log line.

    - cross or mid missing       -> "NA"   (fill-only line; older/unstamped order)
    - mid == cross (degenerate)  -> "None" (computed gap is None but stamp present)
    - otherwise                  -> rounded float
    """
    if _coerce(cross) is None or _coerce(mid) is None:
        return "NA"
    if gap_fraction is None:
        return "None"
    return f"{round(gap_fraction, 4)}"


def format_close_fill_gap_line(
    symbol: Any,
    position_id: Any,
    cross: Any,
    mid: Any,
    fill: Any,
    reason: Any = None,
) -> str:
    """Build the single structured ``[CLOSE_FILL_GAP] ...`` line. Never raises.

    reason is appended (additive superset of the spec format) so the Phase-3
    analysis can split the distribution by trigger type (stop / force-close vs
    target-profit) — the exact decision the REOPEN gate must make.
    """
    gap = compute_gap_fraction(cross, mid, fill)
    pid = str(position_id) if position_id is not None else "None"
    return (
        f"{LOG_PREFIX} symbol={symbol} position_id={pid} "
        f"reason={reason} cross={_coerce(cross)} mid={_coerce(mid)} "
        f"fill={_coerce(fill)} gap_fraction={_gap_display(cross, mid, gap)}"
    )


def log_close_fill_gap(
    symbol: Any,
    position_id: Any,
    cross: Any,
    mid: Any,
    fill: Any,
    reason: Any = None,
    log: Optional[logging.Logger] = None,
) -> str:
    """Emit the structured line at INFO and return it. NEVER raises — a logging
    failure must not break a close."""
    line = format_close_fill_gap_line(symbol, position_id, cross, mid, fill, reason)
    try:
        (log or logger).info(line)
    except Exception:  # pragma: no cover - logging must never break a close
        pass
    return line


def stamp_order_json(supabase: Any, order_id: Any, cross: Any, mid: Any) -> None:
    """Best-effort: merge the stage-time (cross, mid) onto the close order's
    EXISTING order_json (no schema migration) so the fill/reconcile point can
    read them back. Swallows ALL exceptions — never affects the close.
    """
    try:
        row = (
            supabase.table("paper_orders")
            .select("order_json")
            .eq("id", order_id)
            .single()
            .execute()
            .data
        ) or {}
        oj = dict(row.get("order_json") or {})
        oj[CROSS_KEY] = _coerce(cross)
        oj[MID_KEY] = _coerce(mid)
        supabase.table("paper_orders").update({"order_json": oj}).eq(
            "id", order_id
        ).execute()
    except Exception as exc:  # pragma: no cover - best-effort persistence
        logger.warning(f"{LOG_PREFIX} stage stamp failed for order={order_id}: {exc}")
