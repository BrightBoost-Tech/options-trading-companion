import httpx
from typing import List, Dict, Any

class PolygonClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.polygon.io"
        self._client = httpx.AsyncClient(params={"apiKey": self.api_key}, timeout=10.0)

    async def get_ticker_details(self, ticker: str) -> Dict[str, Any]:
        """Fetches details for a given ticker, like market cap."""
        try:
            url = f"{self.base_url}/v3/reference/tickers/{ticker.upper()}"
            response = await self._client.get(url)
            response.raise_for_status()
            data = response.json()
            return data.get("results", {})
        except httpx.HTTPStatusError as e:
            print(f"Error fetching ticker details for {ticker}: {e}")
            return {}

    async def get_snapshot(self, ticker: str) -> Dict[str, Any]:
        """Fetches the latest market data snapshot for a ticker."""
        try:
            url = f"{self.base_url}/v2/snapshot/locale/us/markets/stocks/tickers/{ticker.upper()}"
            response = await self._client.get(url)
            response.raise_for_status()
            data = response.json()
            return data.get("ticker", {})
        except httpx.HTTPStatusError as e:
            print(f"Error fetching snapshot for {ticker}: {e}")
            return {}

    async def get_last_quote(self, ticker: str) -> Dict[str, Any]:
        """
        Fetches the last quote, primarily for the current price.
        Uses the snapshot and provides a consistent price fallback logic.
        """
        snapshot = await self.get_snapshot(ticker)
        price = (
            snapshot.get("day", {}).get("c") or
            snapshot.get("lastQuote", {}).get("p") or
            snapshot.get("prevDay", {}).get("c", 0.0)
        )
        return {"price": price}

    async def get_aggregates(self, ticker: str, from_: str, to: str, timespan: str = "day") -> List[Dict[str, Any]]:
        """Asynchronous version of get_aggregates."""
        try:
            url = f"{self.base_url}/v2/aggs/ticker/{ticker}/range/1/{timespan}/{from_}/{to}"
            response = await self._client.get(url)
            response.raise_for_status()
            data = response.json()
            return data.get("results", [])
        except httpx.HTTPStatusError as e:
            print(f"Error fetching aggregates for {ticker}: {e}")
            return []

    async def close(self):
        await self._client.aclose()
