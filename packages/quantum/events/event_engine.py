"""
Unified event detection engine.

Detects upcoming catalysts that materially affect options pricing:
- Earnings dates (pre/post market, estimated from last filing)
- Ex-dividend dates
- Sector-specific events (FDA for biotech)
- Options expiration clustering (monthly/weekly/quarterly)

Data sources: Polygon ticker details + financials API, with caching.
No external NLP APIs — purely rule-based from market data.
"""

import logging
import math
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from packages.quantum.cache import get_cached_data, save_to_cache

logger = logging.getLogger(__name__)

# Monthly opex: third Friday of each month
# Quarterly opex: third Friday of March, June, September, December
QUARTERLY_MONTHS = {3, 6, 9, 12}
BIOTECH_KEYWORDS = {"biotech", "pharmaceutical", "drug", "therapeutics", "biopharma"}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CatalystEvent:
    """A single detected catalyst event."""
    event_type: str          # earnings, ex_dividend, fda_decision, opex, index_rebalance
    event_date: date
    days_until: int
    confidence: float        # 0-1 (1 = confirmed date, <1 = estimated)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EventSignal:
    """Aggregated event signal for a symbol."""
    symbol: str
    events: List[CatalystEvent] = field(default_factory=list)
    nearest_event: Optional[CatalystEvent] = None
    nearest_days: int = 999
    is_earnings_week: bool = False
    is_ex_div_week: bool = False
    is_opex_week: bool = False
    sector: str = ""
    is_biotech: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "nearest_days": self.nearest_days,
            "nearest_event_type": self.nearest_event.event_type if self.nearest_event else None,
            "is_earnings_week": self.is_earnings_week,
            "is_ex_div_week": self.is_ex_div_week,
            "is_opex_week": self.is_opex_week,
            "is_biotech": self.is_biotech,
            "sector": self.sector,
            "event_count": len(self.events),
            "events": [
                {
                    "type": e.event_type,
                    "date": e.event_date.isoformat(),
                    "days_until": e.days_until,
                    "confidence": e.confidence,
                }
                for e in self.events
            ],
        }


# ---------------------------------------------------------------------------
# Event detection
# ---------------------------------------------------------------------------

def detect_events(
    symbol: str,
    polygon_service=None,
    as_of: Optional[date] = None,
    lookahead_days: int = 30,
) -> EventSignal:
    """
    Detect all upcoming catalyst events for a symbol.

    Checks cached data first, fetches from Polygon if needed.
    Returns an EventSignal with all detected events sorted by date.
    """
    today = as_of or date.today()
    signal = EventSignal(symbol=symbol)

    # 1. Ticker details (sector, type) — cached weekly
    details = _get_ticker_details_cached(symbol, polygon_service)
    ticker_type = details.get("type", "")
    sic_desc = (details.get("sic_description") or "").lower()
    sector = details.get("sector") or sic_desc or ""
    signal.sector = sector
    signal.is_biotech = _is_biotech_sector(sector, sic_desc)

    # Skip event detection for ETFs (no earnings/dividends in the same sense)
    if ticker_type in ("ETF", "ETN", "FUND"):
        # Still check opex
        opex_events = _detect_opex_events(today, lookahead_days)
        signal.events.extend(opex_events)
        _finalize_signal(signal, today)
        return signal

    # 2. Earnings
    earnings_events = _detect_earnings(symbol, today, lookahead_days, polygon_service)
    signal.events.extend(earnings_events)

    # 3. Ex-dividend
    div_events = _detect_ex_dividend(symbol, details, today, lookahead_days)
    signal.events.extend(div_events)

    # 4. Options expiration clustering
    opex_events = _detect_opex_events(today, lookahead_days)
    signal.events.extend(opex_events)

    # 5. Sector-specific (biotech FDA)
    if signal.is_biotech:
        # FDA detection is placeholder — would need an FDA calendar API
        # For now, flag the sector for the scoring engine
        pass

    _finalize_signal(signal, today)
    return signal


def detect_events_batch(
    symbols: List[str],
    polygon_service=None,
    as_of: Optional[date] = None,
    lookahead_days: int = 30,
) -> Dict[str, EventSignal]:
    """Batch event detection for multiple symbols."""
    return {
        sym: detect_events(sym, polygon_service, as_of, lookahead_days)
        for sym in symbols
    }


# ---------------------------------------------------------------------------
# Internal detectors
# ---------------------------------------------------------------------------

def _detect_earnings(
    symbol: str,
    today: date,
    lookahead_days: int,
    polygon_service=None,
) -> List[CatalystEvent]:
    """Detect upcoming earnings from Polygon financials."""
    events = []

    # Check daily cache
    cache_key = (f"event_earnings_{symbol}_{today.isoformat()}",)
    cached = get_cached_data(cache_key)
    if cached and cached.get("checked"):
        if cached.get("date"):
            edate = date.fromisoformat(cached["date"])
            days = (edate - today).days
            if 0 <= days <= lookahead_days:
                events.append(CatalystEvent(
                    event_type="earnings",
                    event_date=edate,
                    days_until=days,
                    confidence=cached.get("confidence", 0.6),
                    metadata=cached.get("metadata", {}),
                ))
        return events

    # Fetch from Polygon
    earnings_date = None
    confidence = 0.6  # estimated from last filing + 90d

    if polygon_service:
        try:
            last_filing = polygon_service.get_last_financials_date(symbol)
            if last_filing:
                # Estimate next earnings: last filing + ~90 days
                if isinstance(last_filing, datetime):
                    last_filing = last_filing.date()
                next_est = last_filing + timedelta(days=90)

                # Roll forward if stale
                for _ in range(8):
                    if next_est >= today - timedelta(days=1):
                        break
                    next_est += timedelta(days=90)

                if next_est >= today:
                    earnings_date = next_est
        except Exception as e:
            logger.debug(f"event_earnings_fetch_error: {symbol} {e}")

    # Cache result
    cache_data = {"checked": True, "date": earnings_date.isoformat() if earnings_date else None,
                  "confidence": confidence}
    save_to_cache(cache_key, cache_data)

    if earnings_date:
        days = (earnings_date - today).days
        if 0 <= days <= lookahead_days:
            events.append(CatalystEvent(
                event_type="earnings",
                event_date=earnings_date,
                days_until=days,
                confidence=confidence,
            ))

    return events


def _detect_ex_dividend(
    symbol: str,
    details: Dict[str, Any],
    today: date,
    lookahead_days: int,
) -> List[CatalystEvent]:
    """Estimate next ex-dividend date from ticker details."""
    events = []

    # Polygon ticker details includes dividend_yield and sometimes last ex-div
    div_yield = details.get("dividend_yield")
    if not div_yield or float(div_yield or 0) <= 0:
        return events

    # Estimate quarterly ex-div dates (most US stocks pay quarterly)
    # Approximate: mid-month of Mar/Jun/Sep/Dec
    for month in [3, 6, 9, 12]:
        approx_date = date(today.year, month, 15)
        if approx_date < today:
            approx_date = date(today.year + 1, month, 15)
        days = (approx_date - today).days
        if 0 <= days <= lookahead_days:
            events.append(CatalystEvent(
                event_type="ex_dividend",
                event_date=approx_date,
                days_until=days,
                confidence=0.4,  # Low confidence — estimated
                metadata={"dividend_yield": float(div_yield)},
            ))
            break  # Only show nearest

    return events


def _detect_opex_events(today: date, lookahead_days: int) -> List[CatalystEvent]:
    """Detect upcoming options expiration dates."""
    events = []

    # Find next monthly opex (third Friday)
    for month_offset in range(3):
        year = today.year
        month = today.month + month_offset
        if month > 12:
            month -= 12
            year += 1

        opex = _third_friday(year, month)
        days = (opex - today).days

        if 0 <= days <= lookahead_days:
            is_quarterly = month in QUARTERLY_MONTHS
            events.append(CatalystEvent(
                event_type="opex",
                event_date=opex,
                days_until=days,
                confidence=1.0,
                metadata={
                    "is_quarterly": is_quarterly,
                    "is_monthly": True,
                },
            ))
            break  # Only nearest

    return events


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_ticker_details_cached(symbol: str, polygon_service=None) -> Dict[str, Any]:
    """Get ticker details with weekly cache."""
    cache_key = (f"event_details_{symbol}",)
    cached = get_cached_data(cache_key)
    if cached:
        return cached

    details = {}
    if polygon_service:
        try:
            details = polygon_service.get_ticker_details(symbol) or {}
        except Exception as e:
            logger.debug(f"event_details_fetch_error: {symbol} {e}")

    save_to_cache(cache_key, details)
    return details


def _is_biotech_sector(sector: str, sic_desc: str) -> bool:
    """Check if the sector/SIC description indicates biotech."""
    combined = f"{sector} {sic_desc}".lower()
    return any(kw in combined for kw in BIOTECH_KEYWORDS)


def _third_friday(year: int, month: int) -> date:
    """Compute the third Friday of a given month."""
    first_day = date(year, month, 1)
    # Find first Friday: weekday 4 = Friday
    days_until_friday = (4 - first_day.weekday()) % 7
    first_friday = first_day + timedelta(days=days_until_friday)
    return first_friday + timedelta(weeks=2)  # Third Friday


def _finalize_signal(signal: EventSignal, today: date) -> None:
    """Set summary fields on the EventSignal."""
    signal.events.sort(key=lambda e: e.event_date)

    if signal.events:
        signal.nearest_event = signal.events[0]
        signal.nearest_days = signal.events[0].days_until

    for e in signal.events:
        if e.event_type == "earnings" and e.days_until <= 7:
            signal.is_earnings_week = True
        if e.event_type == "ex_dividend" and e.days_until <= 7:
            signal.is_ex_div_week = True
        if e.event_type == "opex" and e.days_until <= 5:
            signal.is_opex_week = True
