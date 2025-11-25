import httpx
from typing import List, Dict, Any

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
