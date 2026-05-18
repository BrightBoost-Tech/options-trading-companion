# Polygon dependency status (2026-04-27)

## Current state

- 63 production Polygon API calls across 23 files.
- 11 services with direct Polygon dependency: `options_scanner`,
  `paper_mark_to_market_service`, `paper_endpoints`,
  `dashboard_endpoints`, `option_contract_resolver`,
  `outcome_aggregator`, `universe_service`,
  `earnings_calendar_service`, `iv_daily_refresh`, `event_engine`,
  `nested/backbone`.
- `MarketDataTruthLayer` provides Alpaca-first failover for snapshot
  paths only. Most heavy callers bypass it. Alpaca paper accounts
  lack SIP entitlement, so equity-bars fallback fails today; this
  may resolve under the live Alpaca account (#88 verification
  pending).
- **Failure observability:** PR #823's H3 doctrine alerts wrap
  `@guardrail`-protected callers — Polygon failures now write
  `polygon_circuit_open` and `polygon_retries_exhausted` rows to
  `risk_alerts`. The previous "silent degradation" framing is
  obsolete (alerts surfaced #87 within hours of deploy).

## 2026-04-27 plan upgrade

Stocks Basic ($0) → Stocks Starter ($29/mo); Options Basic ($0) →
Options Developer ($79/mo). Total $108/mo recurring. Resolved #87
(chronic 429 + entitlement gap). Polygon is now a durable paid
provider for the foreseeable future.

## Phase-out status (post-upgrade)

The original Tier 1/2/3 phase-out plan was motivated by treating
429s as a structural Polygon problem. With #87 resolved at the
plan-tier level, the phase-out is no longer urgent. Items below
remain in the backlog as **provider redundancy / lock-in
mitigation**, not safety:

- **Tier 1 (LOW, P3): #66 dead-code deletion** — independent of
  plan tier; pure hygiene.
- **Tier 2 (LOW, P4 deferred): #68 / #69 Alpaca migrations** —
  reactivate if Polygon billing changes materially, if a future
  Polygon outage proves prolonged, or if live Alpaca account
  unlocks SIP making the fallback path actually work.
- **Tier 3 (P4 deferred): #70 HARD_TO_REPLACE** — Polygon-only
  forever for `get_ticker_details`, `get_last_financials_date`,
  `I:VIX` bars. The plan upgrade reinforces this — these calls
  are correctly classified.

## Cost contingency

$108/mo is the new monthly recurring cost. If Polygon raises
Starter or Options Developer pricing materially, or if the live
Alpaca account unlocks options + SIP entitlements making redundancy
free, revisit #68/#69 as the cost-driven fallback path. Track
Polygon billing changes as a soft signal (no automated trigger).

## Backlog tracking

Items #65–#70, #87a/b, #88, #91 in `docs/backlog.md`.
