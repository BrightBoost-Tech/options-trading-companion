import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple
from packages.quantum.market_data import PolygonService
from packages.quantum.cache import get_cached_data, save_to_cache

logger = logging.getLogger(__name__)

class EarningsCalendarService:
    def __init__(self, polygon_service: PolygonService = None):
        self.polygon = polygon_service or PolygonService()
        # Cache TTL is handled by cache.py (24h default)

    def get_earnings_date(self, symbol: str) -> Optional[datetime]:
        """
        Returns the next earnings date for the symbol.
        Uses a cached lookup or fetches from provider.
        """
        # Cache key needs to be a tuple for cache.py
        cache_key = (f"earnings_{symbol}",)

        cached_val = get_cached_data(cache_key)
        if cached_val:
            try:
                # cached_val is the raw data dict saved, which we expect to be {"date": iso_str}
                date_str = cached_val.get("date")
                if date_str:
                    return datetime.fromisoformat(date_str)
                return None # Explicit None cached (e.g. for ETFs)
            except ValueError:
                return None

        # Fetch from Provider
        earnings_date = self._fetch_next_earnings(symbol)

        # Cache Result
        # We store a dict to be extensible
        data_to_cache = {"date": earnings_date.isoformat()} if earnings_date else {"date": None}
        save_to_cache(cache_key, data_to_cache)

        return earnings_date

    def _fetch_next_earnings(self, symbol: str) -> Optional[datetime]:
        """
        Fetches or estimates the next earnings date.
        """
        try:
            # 1. Check for ETF (no earnings risk)
            details = self.polygon.get_ticker_details(symbol)
            # 'type' can be 'ETF', 'ETN', 'CS' (Common Stock), etc.
            # We treat ETFs as having no earnings date.
            type_code = details.get('type')
            if type_code in ('ETF', 'ETN', 'FUND'):
                return None

            # 2. Try to get last financials to estimate next
            # Note: A paid API would give us the exact next date.
            # Without that, we estimate: last_filing + 90 days.
            last_date = self.polygon.get_last_financials_date(symbol)

            if last_date:
                # Estimate next: last + 90 days
                next_est = last_date + timedelta(days=90)

                # If estimated date is in the past, assume we missed one or data is stale,
                # project forward to the next future quarter.
                now = datetime.now()
                # Safety valve: don't project more than 2 year ahead blindly (was 1 year, increased for long-stale data in dev)
                loop_limit = 8
                while next_est < now and loop_limit > 0:
                    next_est += timedelta(days=90)
                    loop_limit -= 1

                # Only return if it's in the future or very recent past (today)
                if next_est >= now - timedelta(days=1):
                    return next_est

        except Exception as e:
            logger.warning(f"Failed to fetch earnings for {symbol}: {e}")

        return None
