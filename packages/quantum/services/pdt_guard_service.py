"""
PDT (Pattern Day Trader) Guard Service

Enforces the SEC Pattern Day Trading rule for accounts under $25K:
- Max 3 day trades per rolling 5 business days
- A day trade = opening AND closing the same position on the same calendar day
- Business days = Mon-Fri (no holiday calendar yet)

Uses America/Chicago timezone for "same day" determination since that's
the primary trading timezone for this platform.

Feature flag: PDT_PROTECTION_ENABLED (default: "0" / disabled)
"""

import os
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PDT_MAX_DAY_TRADES = int(os.environ.get("PDT_MAX_DAY_TRADES", "3"))
PDT_ROLLING_BUSINESS_DAYS = 5
PDT_EMERGENCY_STOP_PCT = float(os.environ.get("PDT_EMERGENCY_STOP_PCT", "-80"))
CHICAGO_TZ = ZoneInfo("America/Chicago")


def is_pdt_enabled() -> bool:
    """Check if PDT protection is enabled via feature flag."""
    return os.environ.get("PDT_PROTECTION_ENABLED", "0") == "1"


# ---------------------------------------------------------------------------
# Business day helpers
# ---------------------------------------------------------------------------

def _get_rolling_business_days(as_of: date, count: int = PDT_ROLLING_BUSINESS_DAYS) -> List[date]:
    """
    Get the last N business days ending on as_of (inclusive).

    Business days = Mon-Fri. Does not account for market holidays.
    """
    days = []
    current = as_of
    while len(days) < count:
        if current.weekday() < 5:  # Mon=0 .. Fri=4
            days.append(current)
        current -= timedelta(days=1)
    days.reverse()  # oldest first
    return days


def _chicago_today() -> date:
    """Current calendar date in Chicago timezone."""
    return datetime.now(CHICAGO_TZ).date()


def _to_chicago_date(dt: Any) -> Optional[date]:
    """
    Convert a datetime (or ISO string) to a Chicago-timezone calendar date.

    Returns None if parsing fails.
    """
    if dt is None:
        return None
    if isinstance(dt, date) and not isinstance(dt, datetime):
        return dt
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(CHICAGO_TZ).date()
    return None


# ---------------------------------------------------------------------------
# Core PDT logic
# ---------------------------------------------------------------------------

def get_pdt_status(supabase, user_id: str) -> Dict[str, Any]:
    """
    Get current PDT day trade status for a user.

    Returns dict with:
        - day_trades_used: count in rolling window
        - day_trades_remaining: how many more allowed
        - max_day_trades: the limit (3)
        - window_dates: the 5 business days in the window
        - at_limit: True if no day trades remaining
        - trades: list of day trade records in window
    """
    today = _chicago_today()
    window_dates = _get_rolling_business_days(today, PDT_ROLLING_BUSINESS_DAYS)
    window_start = window_dates[0]

    # Query day trade log for this window
    try:
        res = supabase.table("pdt_day_trade_log") \
            .select("*") \
            .eq("user_id", user_id) \
            .gte("trade_date", window_start.isoformat()) \
            .lte("trade_date", today.isoformat()) \
            .execute()
        trades = res.data or []
    except Exception as e:
        logger.error(f"pdt_status_query_error: user_id={user_id} error={e}")
        trades = []

    # Only count trades on business days in the window
    window_date_set = set(d.isoformat() for d in window_dates)
    valid_trades = [
        t for t in trades
        if str(t.get("trade_date", ""))[:10] in window_date_set
    ]

    used = len(valid_trades)
    remaining = max(0, PDT_MAX_DAY_TRADES - used)

    return {
        "day_trades_used": used,
        "day_trades_remaining": remaining,
        "max_day_trades": PDT_MAX_DAY_TRADES,
        "window_dates": [d.isoformat() for d in window_dates],
        "at_limit": remaining == 0,
        "trades": valid_trades,
    }


def is_same_day_close(position: Dict[str, Any], now_chicago_date: Optional[date] = None) -> bool:
    """
    Check if closing this position NOW would be a same-day (day) trade.

    A day trade occurs when a position is opened and closed on the same
    Chicago-timezone calendar date.
    """
    if now_chicago_date is None:
        now_chicago_date = _chicago_today()

    opened_at = position.get("created_at")
    opened_date = _to_chicago_date(opened_at)

    if opened_date is None:
        # Can't determine — assume NOT same day (safe: allows the close)
        logger.warning(
            f"pdt_cannot_determine_open_date: position_id={position.get('id')} "
            f"created_at={opened_at} — assuming not same-day"
        )
        return False

    return opened_date == now_chicago_date


def can_day_trade(supabase, user_id: str) -> bool:
    """Return True if the user has day trades remaining in the PDT window."""
    status = get_pdt_status(supabase, user_id)
    return status["day_trades_remaining"] > 0


def record_day_trade(
    supabase,
    user_id: str,
    position_id: str,
    symbol: str,
    opened_at: str,
    closed_at: str,
    trade_date: date,
    realized_pl: float = 0.0,
    close_reason: str = "",
) -> None:
    """
    Record a completed day trade in the PDT log.

    Called AFTER the position is successfully closed.
    Idempotent — unique constraint on position_id prevents duplicates.
    """
    try:
        supabase.table("pdt_day_trade_log").upsert({
            "user_id": user_id,
            "position_id": position_id,
            "symbol": symbol,
            "opened_at": opened_at,
            "closed_at": closed_at,
            "trade_date": trade_date.isoformat(),
            "realized_pl": realized_pl,
            "close_reason": close_reason,
        }, on_conflict="position_id").execute()

        logger.info(
            f"pdt_day_trade_recorded: user_id={user_id} position_id={position_id} "
            f"symbol={symbol} trade_date={trade_date} realized_pl={realized_pl}"
        )
    except Exception as e:
        # Non-fatal: don't block the close if logging fails
        logger.error(
            f"pdt_day_trade_record_error: user_id={user_id} "
            f"position_id={position_id} error={e}"
        )


def is_emergency_stop(position: Dict[str, Any]) -> bool:
    """
    Check if a position has catastrophic unrealized loss requiring emergency close.

    Returns True if unrealized_pl / max_risk exceeds PDT_EMERGENCY_STOP_PCT.
    Capital protection overrides PDT compliance.
    """
    unrealized_pl = float(position.get("unrealized_pl") or 0)
    max_credit = float(position.get("max_credit") or 0)

    if max_credit <= 0:
        return False

    max_risk = max_credit * 100  # per-contract risk in dollars
    if max_risk <= 0:
        return False

    loss_pct = (unrealized_pl / max_risk) * 100

    return loss_pct <= PDT_EMERGENCY_STOP_PCT
