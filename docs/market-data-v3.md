# Market Data V3: Truth Layer

The **Market Data Truth Layer** (`MarketDataTruthLayer`) is the centralized source of truth for all market data in the application. It replaces ad-hoc calls to Polygon.io and inconsistent caching strategies.

## Features

- **Unified Fetching**: Single entry point for snapshots, option chains, and daily bars.
- **Auto-Normalization**: Automatically handles `O:` prefixes for options and parses responses into canonical dictionaries.
- **Smart Caching**: In-memory TTL cache with specific durations for different data types (snapshots: 10s, chains: 60s, history: 12h).
- **IV Context**: Provides IV Rank and Regime derived from historical volatility proxy (HV Rank) or Implied Volatility (future).
- **Resilience**: Built-in retries, backoff, and robust error handling.

## Usage

### Initialization

```python
from packages.quantum.services.market_data_truth_layer import MarketDataTruthLayer

# Automatically reads MARKETDATA_API_KEY or POLYGON_API_KEY from env
layer = MarketDataTruthLayer()
```

### Batch Snapshots (Scanning)

Efficiently fetch data for up to 250 tickers in one call.

```python
tickers = ["AAPL", "SPY", "O:SPY231215C00450000"]
snapshots = layer.snapshot_many(tickers)

for ticker, data in snapshots.items():
    print(f"{ticker}: {data['quote']['mid']} (IV: {data.get('iv')})")
```

### Option Chain

Fetch all options for an underlying.

```python
chain = layer.option_chain("SPY", expiration_date="2023-12-15", right="call")
for contract in chain:
    print(f"{contract['strike']} Call: {contract['quote']['mid']}")
```

### IV Context & Trend

Get regime context for strategy selection.

```python
ctx = layer.iv_context("SPY")
# {'iv_rank': 45.2, 'iv_regime': 'normal', 'iv_rank_source': 'hv_proxy'}

trend = layer.get_trend("SPY") # "UP", "DOWN", or "NEUTRAL"
```

## Migration Status

- **Options Scanner**: Fully migrated to use `snapshot_many`.
- **Workflow Orchestrator**: Migrated morning cycle to use Truth Layer and fixed IV Rank bug.
- **Legacy**: `PolygonService` in `market_data.py` is kept for backward compatibility but should be deprecated in favor of `MarketDataTruthLayer`.

## Configuration

- `MARKETDATA_API_KEY`: Primary API key (Polygon.io).
- `POLYGON_API_KEY`: Fallback API key.
