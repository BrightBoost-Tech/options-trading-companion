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


def _time_from_datetime(dt: datetime) -> time:
    """Reduce a ``datetime`` to its ET wall-clock ``time``.

    A tz-AWARE datetime is converted to America/New_York FIRST, then its
    time-of-day is taken (DST-correct, no offset arithmetic). A NAIVE datetime
    is treated as broker-provided ET session wall-time — its clock fields are
    returned as-is, NEVER reinterpreted as UTC (the alpaca-py Calendar model
    stringifies ``.open``/``.close`` as space-separated NAIVE ET datetimes,
    e.g. ``'2026-07-20 09:30:00'``).
    """
    if dt.tzinfo is not None:
        dt = dt.astimezone(_ET)
    return dt.time()


def _parse_session_time(raw: Any) -> Optional[time]:
    """Coerce an Alpaca calendar open/close bound into a naive ET ``time``.

    This is the SINGLE parsing authority for calendar session bounds (the broker
    wrapper ``AlpacaClient.get_calendar`` normalizes through it too — never a
    copy). Accepted shapes:

    * ``datetime`` — aware → converted to ET then time; naive → ET wall-time
      as-is (see :func:`_time_from_datetime`). NB: ``datetime`` is checked
      before ``date`` because it subclasses ``date``.
    * ``time`` — returned unchanged (naive ET wall time).
    * date-time STRING using a ``'T'`` OR a single space separator (the alpaca-py
      ``str(datetime)`` form) — parsed with :func:`datetime.fromisoformat`
      (Python 3.11 accepts both separators and offsets), then the aware→ET /
      naive→ET rule applies. A date-ONLY string (no time component) returns
      ``None`` — never a fabricated midnight session.
    * bare ``'HH:MM'`` / ``'HH:MM:SS'`` (optional fractional seconds) — parsed
      to a ``time``.
    * a bare ``date`` object or anything malformed/ambiguous → ``None``.

    Returns ``None`` when there is no readable time component — the caller treats
    a trading-day row with ``None`` bounds as unreadable and fails CLOSED
    (H9: never fabricate a session)."""
    if raw is None:
        return None
    if isinstance(raw, datetime):  # must precede the ``date`` check (subclass)
        return _time_from_datetime(raw)
    if isinstance(raw, time):
        return raw
    if isinstance(raw, date):  # a bare date has no time-of-day component
        return None

    s = str(raw).strip()
    if not s:
        return None

    # Date-time string (carries a date component): 'T' or a single space.
    if "T" in s or " " in s:
        try:
            return _time_from_datetime(datetime.fromisoformat(s.replace("Z", "+00:00")))
        except ValueError:
            return None

    # No date component: a date-only token like '2026-07-20' has no ':' — it is
    # NOT a session time, so it must return None (never a midnight session).
    if ":" not in s:
        return None

    # Bare time: '09:30', '09:30:00', optional fractional seconds.
    try:
        return time.fromisoformat(s)
    except ValueError:
        pass
    s = s.split(".", 1)[0]  # drop any fractional seconds for the strptime fallback
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(s, fmt).time()
        except ValueError:
            continue
    return None


def normalize_session_bound(raw: Any) -> Optional[str]:
    """Coerce a calendar open/close bound to a canonical bare ET wall-time
    string — ``'HH:MM'``, or ``'HH:MM:SS'`` only when the seconds are nonzero —
    or ``None`` when there is no readable time component.

    This is the broker wrapper's normalizer; it delegates to the ONE parsing
    authority :func:`_parse_session_time` so the wrapper and the resolver never
    diverge. A ``None`` return signals an unreadable bound; the wrapper keeps raw
    diagnostic context and the resolver still fails CLOSED."""
    t = _parse_session_time(raw)
    if t is None:
        return None
    if t.second or t.microsecond:
        return t.strftime("%H:%M:%S")
    return t.strftime("%H:%M")


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
