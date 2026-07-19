"""Canonical market-session source — broker/exchange trading calendar.

F-A10-HOLIDAY (v1.6): the legacy ``jobs/handlers/utils.is_market_day()`` was
WEEKDAY-ONLY and its docstring falsely claimed "the scheduler already handles"
holidays. It does not — APScheduler's CronTrigger fires mon–fri regardless of
exchange holidays, so entry-suggestion generation and the live pre-submit
market-hours check ran on Thanksgiving, Labor Day, etc.

This module is the ONE holiday/half-day-aware session source. It is built on
Alpaca's broker trading calendar — the same broker truth the intraday monitor
(``get_market_clock`` is_open) and the reentry cooldown (``next_open``) already
trust — NOT a parallel, hand-maintained holiday list.

Doctrine (§10, empty-vs-failed): an UNREADABLE calendar is NOT an empty
calendar. A successful zero-row query for a single date means that date is a
NON-trading day (weekend/holiday) and returns a typed non-trading session; a
fetch failure raises :class:`MarketCalendarUnavailable` so ENTRY consumers can
fail CLOSED (no entries + typed job truth) — never a silent weekday fallback.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Any, Callable, List, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")

# NYSE regular-session close (ET). A session that closes before this is an
# early close / half-day (e.g. the Friday after Thanksgiving, Christmas Eve).
_REGULAR_CLOSE = time(16, 0)


class MarketCalendarUnavailable(Exception):
    """The broker trading calendar could not be read. ENTRY paths treat this as
    fail-CLOSED (no entries + typed job truth). It MUST NEVER be collapsed with
    a successfully-determined non-trading day (that is a valid, returned
    ``MarketSession`` with ``is_trading_day=False``)."""


@dataclass(frozen=True)
class MarketSession:
    """One ET trading-day session: whether it is a trading day, plus the
    tz-aware ET open/close bounds and the early-close flag. ``open_at`` /
    ``close_at`` are ``None`` on a non-trading day."""

    session_date: date
    is_trading_day: bool
    open_at: Optional[datetime] = None
    close_at: Optional[datetime] = None
    is_early_close: bool = False

    def is_open_at(self, now: Optional[datetime] = None) -> bool:
        """True iff ``now`` falls within ``[open_at, close_at)`` on a trading
        day. Half-day aware: an early close is honored via ``close_at``. A naive
        ``now`` is read as UTC; the comparison is done in ET (DST-correct, no
        offset arithmetic)."""
        if not self.is_trading_day or self.open_at is None or self.close_at is None:
            return False
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        now_et = now.astimezone(_ET)
        return self.open_at <= now_et < self.close_at


def _parse_session_time(raw: Any) -> Optional[time]:
    """Parse an Alpaca calendar open/close ('09:30', '09:30:00', or an ISO
    datetime) into a naive ``time``. Returns ``None`` when unparseable — the
    caller treats a trading-day row with unparseable bounds as unreadable
    (H9: never fabricate a session)."""
    s = str(raw or "").strip()
    if not s:
        return None
    if "T" in s:  # full ISO datetime → take the time-of-day
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).time()
        except ValueError:
            s = s.split("T", 1)[1]
    s = s.split(".", 1)[0]  # drop any fractional seconds
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(s, fmt).time()
        except ValueError:
            continue
    return None


def _default_calendar_fn(start: date, end: date) -> List[Any]:
    """Fetch the broker calendar via the singleton Alpaca client. Raises
    :class:`MarketCalendarUnavailable` when no client is configured (internal
    paper mode / missing creds) so entries fail closed rather than silently
    falling back to weekday logic."""
    from packages.quantum.brokers.alpaca_client import get_alpaca_client

    client = get_alpaca_client()
    if client is None:
        raise MarketCalendarUnavailable("no broker client (ALPACA_API_KEY unset)")
    return client.get_calendar(start=start, end=end)


def get_market_session(
    now: Optional[datetime] = None,
    *,
    calendar_fn: Optional[Callable[[date, date], List[Any]]] = None,
) -> MarketSession:
    """Resolve today's (ET) market session from the broker calendar.

    Args:
        now: the instant to resolve (default: broker/system UTC now). A naive
            value is read as UTC; the ET date is derived DST-correctly.
        calendar_fn: injectable ``(start_date, end_date) -> rows`` fetcher
            (default: the singleton Alpaca client). Rows may be dicts
            (``{date, open, close}``) or SDK objects with those attributes.

    Raises:
        MarketCalendarUnavailable: on ANY read failure (no client, fetch error,
            or a trading-day row with unparseable bounds). This is the
            fail-closed signal for entry paths — distinct from a successful
            non-trading day (returned, not raised).
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    today_et = now.astimezone(_ET).date()

    fn = calendar_fn or _default_calendar_fn
    try:
        rows = fn(today_et, today_et)
    except MarketCalendarUnavailable:
        raise
    except Exception as e:  # noqa: BLE001 — every read failure fails closed
        raise MarketCalendarUnavailable(
            f"broker calendar fetch failed: {type(e).__name__}: {e}"
        ) from e

    row = None
    for r in (rows or []):
        r_date = r.get("date") if isinstance(r, dict) else getattr(r, "date", None)
        if str(r_date) == today_et.isoformat():
            row = r
            break

    if row is None:
        # Successful zero-row (single-date query on a weekend/holiday): a typed
        # NON-trading day, NOT a failure.
        return MarketSession(session_date=today_et, is_trading_day=False)

    o_raw = row.get("open") if isinstance(row, dict) else getattr(row, "open", None)
    c_raw = row.get("close") if isinstance(row, dict) else getattr(row, "close", None)
    o_time = _parse_session_time(o_raw)
    c_time = _parse_session_time(c_raw)

    if o_time is None or c_time is None:
        # A trading-day row whose bounds we cannot price is unreadable — NOT a
        # silent "assume regular session" (H9: never fabricate a quote/session).
        raise MarketCalendarUnavailable(
            f"calendar row for {today_et} has missing/unparseable open/close: "
            f"open={o_raw!r} close={c_raw!r}"
        )

    open_at = datetime.combine(today_et, o_time, tzinfo=_ET)
    close_at = datetime.combine(today_et, c_time, tzinfo=_ET)
    return MarketSession(
        session_date=today_et,
        is_trading_day=True,
        open_at=open_at,
        close_at=close_at,
        is_early_close=c_time < _REGULAR_CLOSE,
    )
