# Data Providers

## Primary: Alpaca

Alpaca serves as both the broker and primary market-data source.

**Broker client:** `packages/quantum/brokers/alpaca_client.py`
**Env vars:** `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `ALPACA_PAPER` (`true` in paper mode)

### Market data routing

| Data Type | Endpoint | Routing |
|---|---|---|
| Option snapshots (MTM) | `/v1beta1/options/snapshots` | Alpaca primary |
| Option chains | `/v1beta1/options/snapshots/{underlying}` | Alpaca primary |
| Equity snapshots | `/v2/stocks/snapshots` | Alpaca primary |
| Daily bars | `/v2/stocks/bars` | Alpaca primary |
| Equity NBBO quotes | `/v2/stocks/quotes/latest` | Alpaca primary |
| Previous close | `/v2/stocks/snapshots` (prev_daily_bar) | Alpaca primary |
| Account / portfolio history | `get_account`, `get_portfolio_history` | Alpaca only |

## Fallback: Polygon.io

Used only when Alpaca misses a specific ticker or for reference data
Alpaca doesn't offer.

**Client:** `packages/quantum/market_data.py::PolygonService`
**Env var:** `POLYGON_API_KEY`

### Reference-only (Polygon only, no Alpaca equivalent)

- Earnings dates: `/vX/reference/financials`
- Historical option contracts: `/v3/reference/options/contracts`

## Migration history

- 2026-04-08 — Options data migrated from Polygon to Alpaca primary
  (Polygon plan lacked option quotes after plan change)
- 2026-04-10 — Equity data migrated from Polygon to Alpaca primary
- 2026-04-16 — Account equity + portfolio history reads migrated to
  Alpaca-authoritative in intraday_risk_monitor (see
  `packages/quantum/services/equity_state.py` or `intraday_risk_monitor.py`
  per the 83872db fix)

## Caching

`MarketDataTruthLayer` applies TTL caching to provider responses:

| Data Type | TTL | Env var |
|---|---|---|
| Snapshots | 120s (default) | `SNAPSHOT_CACHE_TTL` |
| Option chains | 300s | `OPTION_CHAIN_CACHE_TTL` |
| Daily bars | 12h (hardcoded) | — |

The snapshot TTL was raised from a hardcoded 10s to 60s on 2026-04-16
(env-configurable) and standardized to 120s per audit Phase 3 findings.

## Plaid (deprecated)

Plaid was the original holdings-sync source from an earlier design that
supported connected brokerages for holdings import. The current pipeline
uses Alpaca for both broker and market data; Plaid is not wired into any
scheduled job. The `PLAID_*` env vars on Railway are vestigial.

## SnapTrade (not shipped)

SnapTrade was considered as a fallback broker integration for brokerages
Plaid didn't cover. It was never implemented. The `SNAPTRADE_*` env vars
on the worker service hold placeholder values from `.env.example` and
are scheduled for removal in the Railway env cleanup pre-flight list.
