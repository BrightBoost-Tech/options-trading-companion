# Risk per trade math — extended notes

Reference document for CLAUDE.md "Risk per trade math". The CLAUDE.md section keeps the tier table, multiplier behavior, allocation summary, concurrency policy, and per-symbol envelope. Worked examples, the per-tier global-allocation breakdown, the universe-price-filter rationale, and the history block live here.

## Worked examples ($500 capital, micro tier, NORMAL regime)

Micro tier examples (unchanged):

| Score | Regime | risk_budget |
|---:|---|---:|
| any | normal | $450 |
| any | suppressed | $405 |
| any | elevated | $360 |
| any | shock | $225 |

For $500 capital + score 85 + normal regime + `COMPOUNDING_MODE=true`:
`risk_pct = 0.90 × 1.0 = 0.90`, `risk_budget = $500 × 0.90 = $450`.

## Worked examples (small tier, post-2026-05-18 allocator)

Full math + 3 more examples in `docs/small_tier_allocation.md`. Summaries:

- **$1,500, 4 candidates [95/88/82/76], normal:** allocator emits ~$280/$263/$255/$255 (total ~$1,053 = 70% of equity)
- **$1,500, 1 candidate [88], normal:** 36% ceiling binds → $540 (single-candidate concentration defended by the ceiling)
- **$1,500, $450 open, 3 new candidates [90/82/74], normal:** envelope $825; allocator emits $367/$340/$118 (Cand 3 truncated by remaining envelope after open-position subtraction)

## Global allocation (per tier)

**Micro tier:** `global_alloc.max = deployable_capital × 0.90 × regime_mult_for_micro`. Mirrors per-trade for one-at-a-time tiers.

**Small tier (post-2026-05-18):** `global_alloc.max = total_equity × 0.85 × regime_mult`. Per-cycle availability after subtracting current open-position cost basis. See `docs/small_tier_allocation.md` §2.

**Standard tier:** `global_alloc.max = total_equity × global_cap_pct` (regime-based 5–50%, unchanged).

## Universe price filter (micro tier)

For micro-tier accounts, the scanner pre-filters the 62-symbol universe at `options_scanner._apply_tier_price_filter` (called immediately after the batch quote fetch, before per-symbol Polygon option-chain calls) to drop symbols whose underlying price exceeds $50 (configurable via `MICRO_TIER_MAX_UNDERLYING` env var).

The threshold aligns with existing scanner spread-width logic at `options_scanner.py:~1084`: spreads default to 2.5-wide for sub-$50 underlyings and 5-wide above. Sub-threshold names produce ~$200–$250 max_loss/contract that fits the micro $450 budget; above-threshold names produce ~$300–$500+ that often exceeds it.

Without this filter, ~80% of the universe (FAANG + high-priced ETFs) produces uneconomic candidates that pass scanner gates only to be vetoed at sizing — wasting Polygon API calls and producing zero suggestions. The 2026-04-27 19:16 UTC manual cycle was the forcing example: 30 symbols → scanner → 1 candidate (AMZN $1247 underlying, $1223 max_loss) → 0 suggestions.

For small/standard tiers, no filter is applied; the full universe is scanned per existing behavior. Hard cutoff matches the sizing fix's tier transition.

## History

- **Pre-2026-04-27:** `RiskBudgetEngine` used flat 3% balanced default, silently overriding `SmallAccountCompounder`'s tier math via `min()` at `workflow_orchestrator.py:2347`. The compounder layer was documented but never wired through to per-trade sizing.
- **2026-04-27:** tier-aware engine landed. Both layers now agree. Discovered during PR #827 fix validation when all 3 candidates (BAC at $286, AMZN at $1248, AAPL at $1274 single-contract risk) were vetoed at sizing because `max_risk_per_trade=$15` (3% of $500).
- **2026-05-18:** allocation-aware sizing policy landed for small tier. Replaces per-trade-independent `3% × multipliers` math with `PortfolioAllocator` cycle-aware distribution. Motivated by α's full-universe IV pipeline (Phase 3 v3 completed 2026-05-17) unlocking IV-sensitive strategies, expected to produce richer candidate sets per cycle as the operator transitions from micro tier ($681) to small tier ($1500+). Spec at `docs/small_tier_allocation.md`; implementation in `packages/quantum/services/portfolio_allocator.py`; integration via additive `allocation_hint` parameter on `RiskBudgetEngine` and `SmallAccountCompounder` for backward-compat.
