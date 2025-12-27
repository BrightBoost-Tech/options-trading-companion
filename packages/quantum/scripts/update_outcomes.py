import os
import sys
import uuid
from datetime import datetime, timedelta
import asyncio
from dotenv import load_dotenv
from supabase import create_client, Client

# Add package root to path to allow imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from packages.quantum.market_data import PolygonService
from packages.quantum.analytics.outcome_aggregator import OutcomeAggregator

# Load env vars
load_dotenv()

def get_supabase_client() -> Client:
    url = os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("Error: Missing Supabase credentials.")
        sys.exit(1)
    return create_client(url, key)

async def update_outcomes():
    supabase = get_supabase_client()
    polygon_service = PolygonService()
    aggregator = OutcomeAggregator(supabase, polygon_service)

    # Window: logs from 48h to 24h ago
    yesterday = datetime.now() - timedelta(days=1)
    two_days_ago = datetime.now() - timedelta(days=2)

    print(f"[{datetime.now()}] Running Outcome Aggregator for window {two_days_ago} -> {yesterday}")

    await aggregator.run(two_days_ago, yesterday)

if __name__ == "__main__":
    asyncio.run(update_outcomes())
