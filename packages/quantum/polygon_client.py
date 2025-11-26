import httpx
from typing import List, Dict, Any
from datetime import datetime, timedelta

class PolygonClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.polygon.io"

    async def get_aggregates(self, ticker: str, from_: str, to: str, timespan: str = "day") -> List[Dict[str, Any]]:
        async with httpx.AsyncClient() as client:
            url = f"{self.base_url}/v2/aggs/ticker/{ticker}/range/1/{timespan}/{from_}/{to}"
            params = {"apiKey": self.api_key}
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            return data.get("results", [])

    def get_historical_data(self, symbol: str, days: int = 30):
        # --- FIX: Ignore Cash / Currency placeholders ---
        if "CUR:" in symbol or symbol == "USD":
            # Return a flat line for cash (value is always $1.00)
            return [{"c": 1.00} for _ in range(days)]

        # Existing logic...
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        # This part is a placeholder for the actual API call
        # In a real implementation, you would use get_aggregates_async or similar
        print(f"Fetching data for {symbol} from {start_date} to {end_date}")
        # Mock data for demonstration
        return [{"c": 100 + i*0.5} for i in range(days)]
