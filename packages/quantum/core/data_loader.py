import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Mocking the Polygon client for the structure - replace with your real client
async def fetch_market_data(tickers, polygon_client, lookback_days=365):
    """
    Fetches historical closes and calculates daily percentage returns.
    """
    # 1. Define date range
    end_date = datetime.now()
    start_date = end_date - timedelta(days=lookback_days)

    data_frames = []

    # 2. Fetch data (Sequential for now, use asyncio.gather in prod)
    for ticker in tickers:
        # This calls your existing Polygon integration
        bars = await polygon_client.get_aggregates(
            ticker,
            from_=start_date.strftime('%Y-%m-%d'),
            to=end_date.strftime('%Y-%m-%d'),
            timespan='day'
        )

        # Create minimal DF: Date | Ticker
        df = pd.DataFrame(bars)
        df['date'] = pd.to_datetime(df['t'], unit='ms')
        df.set_index('date', inplace=True)
        data_frames.append(df['c'].rename(ticker)) # 'c' is close price

    # 3. Merge and Clean
    price_matrix = pd.concat(data_frames, axis=1)

    # Forward fill gaps (don't drop data just because one asset had a holiday)
    price_matrix.ffill(inplace=True)
    price_matrix.dropna(inplace=True) # Drop leading NaNs

    # 4. Calculate Log Returns (Better for optimization than simple % change)
    returns_matrix = np.log(price_matrix / price_matrix.shift(1)).dropna()

    return returns_matrix
