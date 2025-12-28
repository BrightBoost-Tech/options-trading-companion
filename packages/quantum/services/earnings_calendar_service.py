import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, date
from typing import Optional, List, Dict, Union

from packages.quantum.market_data import PolygonService
from packages.quantum.cache import get_cached_data, save_to_cache

logger = logging.getLogger(__name__)

class EarningsProvider(ABC):
    @abstractmethod
    def get_next_earnings(self, symbol: str) -> Optional[date]:
        pass

    def get_batch_earnings(self, symbols: List[str]) -> Dict[str, Optional[date]]:
        """Default implementation: loop (subclasses can optimize)."""
        return {sym: self.get_next_earnings(sym) for sym in symbols}

class LocalStubEarningsProvider(EarningsProvider):
    """
    A lightweight local map for development/testing or fallback.
    """
    def __init__(self):
        # Configurable hooks: hardcoded map for now
        self.manual_map = {
            "SPY": None, # ETF
            "QQQ": None,
            "IWM": None,
            "DIA": None,
            "AAPL": date(2025, 5, 2),  # Example future date
            "MSFT": date(2025, 4, 25),
            "NVDA": date(2025, 5, 22),
            "TSLA": date(2025, 4, 23),
            "AMD": date(2025, 5, 1),
            "AMZN": date(2025, 4, 27),
            "GOOG": date(2025, 4, 25),
            "GOOGL": date(2025, 4, 25),
            "META": date(2025, 4, 24),
            "NFLX": date(2025, 4, 18),
        }
        # Explicit TODO hook
        logger.info("Initialized LocalStubEarningsProvider with static map.")

    def get_next_earnings(self, symbol: str) -> Optional[date]:
        # Return mapped date or None
        # In a real app, 'None' for unmapped might mean "Unknown"
        # But for ETFs it means "None".
        # If unknown, we return None and let service decide if it's "Unknown" or "None".
        # Here we just look up.
        val = self.manual_map.get(symbol.upper())
        if val is None:
             # Basic heuristic: if it looks like an ETF (3 chars?), maybe assume None safely?
             # No, that's dangerous. Just return None.
             return None
        return val

class PolygonEarningsProvider(EarningsProvider):
    """
    Fetches earnings from Polygon.io.
    """
    def __init__(self, polygon_service: PolygonService = None):
        self.polygon = polygon_service or PolygonService()

    def get_next_earnings(self, symbol: str) -> Optional[date]:
        try:
            # 1. Check for ETF
            details = self.polygon.get_ticker_details(symbol)
            type_code = details.get('type')
            if type_code in ('ETF', 'ETN', 'FUND'):
                return None

            # 2. Get last financials
            last_date = self.polygon.get_last_financials_date(symbol)
            if last_date:
                # Estimate next: last + 90 days
                next_est = last_date + timedelta(days=90)

                # Project forward if stale
                now = datetime.now()
                loop_limit = 8
                while next_est < now and loop_limit > 0:
                    next_est += timedelta(days=90)
                    loop_limit -= 1

                if next_est >= now - timedelta(days=1):
                    return next_est.date() # Return date object

            return None

        except Exception as e:
            logger.warning(f"[Earnings] Polygon fetch failed for {symbol}: {e}")
            return None

class EarningsCalendarService:
    def __init__(self, market_data: PolygonService = None):
        # Choose provider
        # Requirement: "default provider can be a stub... OR existing DB tables"
        # Constraint: "No paid API requirement."
        # Logic: If POLYGON_API_KEY is set, try Polygon, else Stub.

        if os.getenv("POLYGON_API_KEY"):
            self.provider = PolygonEarningsProvider(market_data)
        else:
            self.provider = LocalStubEarningsProvider()

        logger.info(f"EarningsCalendarService initialized with {self.provider.__class__.__name__}")

    def get_earnings_date(self, symbol: str) -> Optional[date]:
        """
        Returns the next earnings date for the symbol.
        """
        # Cache key tuple for cache.py
        cache_key = (f"earnings_{symbol}",)

        cached_val = get_cached_data(cache_key)
        if cached_val:
            date_str = cached_val.get("date")
            if date_str:
                return date.fromisoformat(date_str)
            return None # Explicit None (ETF or unknown)

        # Fetch
        edate = self.provider.get_next_earnings(symbol)

        # Cache
        data_to_cache = {"date": edate.isoformat()} if edate else {"date": None}
        save_to_cache(cache_key, data_to_cache)

        if edate is None:
             # Log warning for non-ETF symbols if possible, but hard to know if it's an ETF here without checking details.
             # We rely on provider to filter ETFs.
             pass

        return edate

    def get_earnings_map(self, symbols: List[str]) -> Dict[str, Optional[date]]:
        """
        Batch fetches earnings dates for a list of symbols.
        Checks cache first, then delegates missing to provider.
        """
        results = {}
        missing = []

        # 1. Check Cache
        for sym in symbols:
            cache_key = (f"earnings_{sym}",)
            cached_val = get_cached_data(cache_key)
            if cached_val is not None: # Hit (even if None inside)
                 date_str = cached_val.get("date")
                 results[sym] = date.fromisoformat(date_str) if date_str else None
            else:
                missing.append(sym)

        # 2. Fetch Missing
        if missing:
            # Use provider's batch method (default is loop, but specialized providers can batch)
            fetched = self.provider.get_batch_earnings(missing)

            # Update cache and results
            for sym, edate in fetched.items():
                results[sym] = edate
                cache_key = (f"earnings_{sym}",)
                data_to_cache = {"date": edate.isoformat()} if edate else {"date": None}
                save_to_cache(cache_key, data_to_cache)

        return results
