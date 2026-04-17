# Market Data V3: Truth Layer

The **Market Data Truth Layer** (`MarketDataTruthLayer`) is the centralized source of truth for all market data in the application. It replaces ad-hoc calls to Polygon.io and inconsistent caching strategies.

## Features

- **Unified Fetching**: Single entry point for snapshots, option chains, and daily bars.
- **Auto-Normalization**: Automatically handles `O:` prefixes for options and parses responses into canonical dictionaries.
- **Smart Caching**: In-memory TTL cache with specific durations for different data types (snapshots: `SNAPSHOT_CACHE_TTL`, default 120s; chains: `OPTION_CHAIN_CACHE_TTL`, default 300s; daily bars: 12h).
- **Provider Routing (post-2026-04-10)**: Options primary = Alpaca, fallback = Polygon. Equities primary = Alpaca, fallback = Polygon. See `docs/data_providers_overview.md` for the full routing table.
- **IV Context**: Provides IV Rank and Regime derived from historical volatility proxy (HV Rank) or Implied Volatility (future).
- **Resilience**: Built-in retries, backoff, and robust error handling.

## Usage

### Initialization

```python
from packages.quantum.services.market_data_truth_layer import MarketDataTruthLayer

# Reads POLYGON_API_KEY, ALPACA_API_KEY, ALPACA_SECRET_KEY from env.
layer = MarketDataTruthLayer()
```

### Batch Snapshots (Scanning)

Efficiently fetch data for up to 250 tickers in one call.

```python
tickers = ["AAPL", "SPY", "O:SPY260515C00450000"]
snapshots = layer.snapshot_many(tickers)

for ticker, data in snapshots.items():
    print(f"{ticker}: {data['quote']['mid']} (IV: {data.get('iv')})")
```

### Option Chain

Fetch all options for an underlying.

```python
chain = layer.option_chain("SPY", expiration_date="2026-05-15", right="call")
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
- **Workflow Orchestrator**: Fully migrated. All cycles (morning/midday) use Truth Layer.
- **Internal Tasks**: `/iv/daily-refresh` uses Truth Layer for chain and spot checks.
- **Requirement**: TruthLayer is **REQUIRED** for all workflows and internal analytics. `PolygonService` is allowed ONLY for legacy endpoints until deleted.
- **Legacy**: `PolygonService` in `market_data.py` is kept for backward compatibility but should be deprecated in favor of `MarketDataTruthLayer`.

## Configuration

- `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`: Primary data provider for options
  snapshots, option chains, equity snapshots, daily bars, and NBBO quotes.
- `POLYGON_API_KEY`: Fallback for the above, plus primary for earnings
  dates and historical option contract reference data (no Alpaca equivalent).
- `SNAPSHOT_CACHE_TTL` (default 120): seconds for snapshot cache.
- `OPTION_CHAIN_CACHE_TTL` (default 300): seconds for chain cache.
