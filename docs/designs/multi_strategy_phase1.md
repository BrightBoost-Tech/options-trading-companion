# Multi-strategy emission architecture — Phase 1 design

**Date:** 2026-05-06
**Status:** Phase 1 diagnostic (read-only). Phase 2 implementation prompt drafted after operator review.
**Operator goal:** extend from observed-single-strategy emission to four-strategy regime-aware selection (bear-put, iron condor, 0DTE bull put, cash-secured-put).

---

## Executive summary

**The architecture is already substantially multi-strategy.** What looks like single-strategy emission in production is regime-driven natural selection on a system that has supported multi-strategy emission for months.

| Piece | State |
|-------|-------|
| Multi-strategy selector | ✅ exists — `analytics/strategy_selector.py`, both `determine_strategy()` and `get_candidates()` |
| Strategy ban/fallback | ✅ exists — `analytics/strategy_policy.py:StrategyPolicy` |
| Multi-candidate retry | ✅ exists — `_process_symbol_multi` with primary→fallback chain (audit-instrumented in PR #867) |
| Per-candidate scoring | ✅ exists — `calculate_unified_score` + `expected_value` |
| Cross-candidate ranking | ✅ exists — sorted by `(score, symbol)` at scanner exit |
| Iron condor EV-aware builder | ✅ exists — `_select_best_iron_condor_ev_aware` |
| Bear-put-spread (LONG_PUT_DEBIT_SPREAD) | ✅ in selector; emitted 45 times historically (pre-2026-04-13) |
| Iron condor (IRON_CONDOR) | ✅ in selector; emitted 78 times historically |
| Bull put credit spread (SHORT_PUT_CREDIT_SPREAD) | ✅ in selector |
| Bear call credit spread (SHORT_CALL_CREDIT_SPREAD) | ✅ in selector |
| 0DTE bull put spread | ❌ not in selector; needs intraday lifecycle + polling refactor |
| Cash-secured-put | ❌ not in selector; needs equity-position handling + capital threshold |
| Strategy lifecycle states | ❌ doesn't exist; ad-hoc `banned_strategies` env arg only |
| Per-strategy realized P&L tracking for graduation | ❌ doesn't exist; needs new helper or schema column |

**Reframed Phase 2 scope:**

- **PR-1 (small):** add `strategy_name` filter to `get_alpaca_real_closed_trades` helper; build `is_strategy_eligible_for_full_weight` evaluation. Foundation for lifecycle gating without any UI changes yet.
- **PR-2 (small):** strategy_lifecycle_states table + scheduler entry. Initially seeds all existing strategies as LIVE_FULL (preserves current behavior), bear-put + iron condor EXPERIMENTAL.
- **PR-3 (small):** sizing-engine override that respects EXPERIMENTAL state — minimum-contracts sizing.
- **PR-4 (medium):** 0DTE bull put spread strategy + intraday polling refactor. Architecturally heaviest item; gated on intraday cycle infrastructure.
- **PR-5 (medium):** cash-secured-put strategy + equity-assignment handling. Capital-gated (need ~$5K-$10K equity for retail-relevant strikes).
- **PR-6 (small):** retire #103 backlog item by surfacing per-strategy emission counts in observability dashboard.

**Estimated total effort:** ~1.5-2 weeks across 6 PRs, of which the first 3 are achievable in 2-3 days.

**Recommended implementation order:** PR-1 → PR-2 → PR-3 (3 PRs in ~2 days, no risk to production); then operator-paced ordering of PR-4 vs PR-5 based on capital + 0DTE infrastructure decisions.

---

## STEP 1 — Current scanner emission pipeline

### Entry point
`packages/quantum/options_scanner.py:2415` (multi) and `:2432` (single):

```python
if MULTI_STRATEGY_EVAL:
    candidates = strategy_selector.get_candidates(
        ticker=symbol, sentiment=trend, current_price=current_price,
        iv_rank=iv_rank, effective_regime=effective_regime_state.value,
        banned_strategies=banned_strategies,
    )
    suggestion = candidates[0]
else:
    suggestion = strategy_selector.determine_strategy(...)
    candidates = [suggestion]
```

`MULTI_STRATEGY_EVAL` is per CLAUDE.md "Permanently on" — `MULTI_STRATEGY_EVAL=1`.

### Strategy selector body
`packages/quantum/analytics/strategy_selector.py` already routes by regime + sentiment + IV:

```
CHOP regime (any sentiment)           → IRON_CONDOR
SHOCK regime (non-EARNINGS)           → CASH (no trade)
BULLISH + low/normal IV               → LONG_CALL_DEBIT_SPREAD
BULLISH + elevated IV                 → SHORT_PUT_CREDIT_SPREAD (fallback to LONG_CALL_DEBIT_SPREAD)
BEARISH + low/normal IV               → LONG_PUT_DEBIT_SPREAD     ← bear-put already exists
BEARISH + elevated IV                 → SHORT_CALL_CREDIT_SPREAD
NEUTRAL + elevated IV                 → IRON_CONDOR
NEUTRAL + low/normal IV               → HOLD
EARNINGS + elevated IV                → IRON_CONDOR
EARNINGS + low/normal IV              → HOLD
```

### Sentiment derivation
`options_scanner.py:2398-2407` — SMA crossover:
- `closes[-1] > sma20 > sma50` → BULLISH
- `closes[-1] < sma20 < sma50` → BEARISH
- otherwise → NEUTRAL

EARNINGS comes from `earnings_map` (separate path).

### Multi-strategy retry path
`_process_symbol_multi` (instrumented in PR #867): if primary candidate fails any downstream gate (sizing, EV, spread), it retries with the next candidate from `get_candidates()`'s ordered pool. `all_strategies_rejected` rejection counter fires when all candidates fail.

### Production strategy distribution

```
strategy                 suggestions  first_seen  last_seen
IRON_CONDOR                       78  2026-02-11  2026-04-03
LONG_PUT_DEBIT_SPREAD             45  2026-03-18  2026-04-10
LONG_CALL_DEBIT_SPREAD            36  2026-03-18  2026-05-05
take_profit_limit                 12  2025-12-11  2026-04-08  (exit, not entry)
```

Post-2026-04-13 (post-corruption-floor): only LONG_CALL_DEBIT_SPREAD (29 emissions). This matches CLAUDE.md note: "Recent regimes have been NORMAL with directional sentiment → debit spreads dominate the output stream. This is regime-driven natural selection, not banning."

The "single-strategy" appearance is the regime classifier landing in NORMAL + the trend classifier landing in BULLISH for ~3 weeks of consecutive recent cycles. CHOP regime would emit IRON_CONDOR; BEARISH sentiment would emit LONG_PUT_DEBIT_SPREAD. Both work today.

### Trade-suggestions schema

```sql
SELECT DISTINCT strategy FROM trade_suggestions;
-- IRON_CONDOR, LONG_PUT_DEBIT_SPREAD, LONG_CALL_DEBIT_SPREAD, take_profit_limit
```

`trade_suggestions.strategy` already exists as text. No schema change needed for adding new strategy values.

---

## STEP 2 — Regime classifier

`packages/quantum/analytics/regime_engine_v3.py:RegimeState` enum produces 6 values:

| RegimeState | Trigger | Strategy bias |
|-------------|---------|---------------|
| SUPPRESSED | very low vol | low_vol → debit spreads |
| NORMAL | typical vol | sentiment-routed |
| ELEVATED | high vol | high_vol → credit spreads or IC |
| SHOCK | extreme vol | CASH (no trade) |
| REBOUND | post-shock recovery | high_vol routing |
| CHOP | range-bound, low vol | IRON_CONDOR |

These are **volatility regimes**, separate from **sentiment** (BULLISH/BEARISH/NEUTRAL/EARNINGS). The two-dimensional matrix is what drives selection.

Operator's stated 4-regime mapping (Bullish/Bearish/Range-bound/Uncertain) maps cleanly:
- Bullish → BULLISH sentiment (any non-SHOCK regime)
- Bearish → BEARISH sentiment (any non-SHOCK regime)
- Range-bound → CHOP regime OR NEUTRAL+ELEVATED
- Uncertain → SHOCK regime → no trade

**No regime-classifier changes needed for Phase 2.**

---

## STEP 3 — Pre-trade comparison framework

Already exists, comprehensive:

1. **Per-candidate scoring** — `calculate_unified_score(candidate, regime_snapshot, market_data, execution_drag, num_legs, entry_cost)` produces `UnifiedScore` with `score`, `components`, `badges`. Scanner attaches the score to each candidate.

2. **Per-candidate expected value** — `calculate_ev(premium, strike, current_price, delta, strategy, width)` produces `EVCalculation` with `expected_value`, `win_probability`, `max_profit`, `max_loss`. Scanner stores `total_ev = ev_obj.expected_value`.

3. **Iron condor EV-aware builder** — `_select_best_iron_condor_ev_aware(calls_sorted, puts_sorted, condor_spread_threshold, current_price)` enumerates short-strike combinations and picks highest-EV combo that passes spread threshold. This is a special case of comparison logic for 4-leg structures.

4. **Cross-candidate ranking** — at scanner exit, `candidates.sort(key=lambda x: (x['score'], x['symbol']), reverse=True)`. Top-N picked per tier (1 for micro, 4 for small, 5 for standard).

5. **Per-symbol multi-strategy retry** — `_process_symbol_multi` tries primary candidate; if it fails downstream gates (sizing veto, EV non-positive, spread too wide, etc.), retries with next candidate in `get_candidates()` pool. Already audit-instrumented for "all strategies rejected" path.

**No new comparison framework needed for Phase 2.** The infrastructure is complete; new strategies just need to flow through the same scoring + ranking.

---

## STEP 4 — Per-strategy architectural cost

### 4a. Bear-put-spread (LONG_PUT_DEBIT_SPREAD) — ALREADY EXISTS

**Status:** in production code at `strategy_selector.py:171-196`. Emitted 45 times historically. Won't fire under current NORMAL+BULLISH conditions but will fire on first BEARISH cycle.

**Architectural cost:** ~0 — code change unnecessary. Current "non-emission" is regime-driven natural selection.

**Operator's apparent intent:** force more BEARISH emission. Two options:
- **A. Wait for natural BEARISH conditions** — no code change; emits when sentiment classifier flips
- **B. Loosen sentiment classifier** — change SMA-crossover thresholds to land BEARISH more often. Risk: false bearish signals
- **C. Manual operator override** — `banned_strategies=["LONG_CALL_DEBIT_SPREAD"]` env arg forces selector to fall through to put strategies

Recommended: **A (wait)** + **C as override knob**. Don't loosen the classifier — the existing thresholds are sound. If operator wants to test bear-put NOW, the env-knob exists.

### 4b. Iron condor (IRON_CONDOR) — ALREADY EXISTS

**Status:** in production code at `strategy_selector.py:117-128` (CHOP path) + `:200-217` (NEUTRAL+high-IV path) + `:222-237` (EARNINGS+high-IV path). Emitted 78 times historically. Won't fire under NORMAL regime + directional sentiment.

**Architectural cost:** ~0 — code change unnecessary. Will fire when:
- Regime flips CHOP, OR
- Sentiment is NEUTRAL with iv_rank > 50, OR
- Earnings within 7 days with iv_rank > 50

**Operator's apparent intent:** force more IRON_CONDOR emission. Same options as bear-put: wait for CHOP (rarer than directional), or use ban-knob.

### 4c. 0DTE bull put spread — DOES NOT EXIST + ARCHITECTURAL CONFLICTS

**Status:** not in selector. Building it requires:

1. **New strategy entry in selector** — ~30 lines in `strategy_selector.py`
2. **Strict expiration filter** — scanner currently filters `min_dte=2, max_dte=45`. 0DTE needs same-day expiry; conflicts with current min_dte=2.
3. **Intraday entry timing** — scanner runs at 11 AM CT. 0DTE entry typically wants 30-60 min after open (per notebook example). Either move scanner trigger time or add a 0DTE-specific scanner cycle.
4. **Polling-based exit monitoring** — biggest blocker. 0DTE positions need exit checks every 5-15 min vs current 30-min `intraday_risk_monitor`. Either:
   - Refactor `intraday_risk_monitor` to run more frequently for users with 0DTE positions (conditional cadence)
   - Build parallel `intraday_0dte_monitor` scheduler entry every 5 min
   - Polling loop in a dedicated worker (changes the "everything via APScheduler" architecture)
5. **One-position-at-a-time gate conflict** — micro-tier blocks new entries while CSX is open. 0DTE benefits from multiple intraday round-trips. Either lift the gate for 0DTE specifically (complex) or wait until tier promotes to small (max_trades=4).
6. **Settlement timing** — 0DTE must close by market-close on entry day. Need explicit force-close-by-3:55-PM logic for any 0DTE position not exited by target/stop.

**Architectural cost:** ~3-4 days of work plus a non-trivial scheduler refactor. Capital-gateable: 0DTE wants ≥4 concurrent trades to deploy efficiently, which requires small-tier ($1000+ equity).

**Recommendation:** design the strategy code in PR-4 but flag the polling refactor as architectural prerequisite. Until intraday cadence is solved, 0DTE stays in DESIGNED state (not emitted).

### 4d. Cash-secured-put — DOES NOT EXIST + CAPITAL CONFLICT

**Status:** not in selector. Building it requires:

1. **New strategy entry in selector** — ~20 lines
2. **Single-leg structure support** — current selector emits 2-leg or 4-leg legs lists. CSP is 1 leg + collateral. Sizing engine + paper_orders schema need to handle "sell 1 put, hold $X cash collateral."
3. **Equity-position handling** — if put is assigned at expiry, position becomes 100 shares of underlying. Current scanner has zero equity-position logic. Either:
   - Auto-close before expiry (avoid assignment; but defeats the point of CSP)
   - Build equity-position tracking (adds substantial code)
   - Manual operator handling on assignment (untested)
4. **Strict capital gate** — CSP collateral = strike × 100. AAPL at $180 strike → $18K collateral. Operator's $696 equity supports CSP only on ultra-cheap underlyings (~$5-7 strike). Universe filter would need a CSP-specific subset.

**Architectural cost:** ~3-4 days for selector + scanner integration. Equity-assignment handling is a separate ~1-week project.

**Recommendation:** design strategy in PR-5 but explicitly capital-gate at $5,000 equity minimum. Auto-close-before-expiry semantics (not real CSP — covered call equivalent) until equity-assignment handling lands.

---

## STEP 5 — Strategy lifecycle state machine

Doesn't exist today. The current `banned_strategies` env arg is binary (banned or allowed). Operator's stated lifecycle (DESIGNED → EXPERIMENTAL → LIVE_FULL → DEPRECATED) needs new state.

### Schema design — new table

```sql
CREATE TABLE strategy_lifecycle_states (
  strategy_name TEXT PRIMARY KEY,
  current_state TEXT NOT NULL CHECK (current_state IN
    ('designed', 'experimental', 'live_full', 'deprecated')),
  transitioned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  transition_reason JSONB,
  closed_trade_count INTEGER,
  cumulative_realized_pl NUMERIC,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Initial seed (preserves current behavior — all existing strategies stay LIVE_FULL)
INSERT INTO strategy_lifecycle_states (strategy_name, current_state) VALUES
  ('LONG_CALL_DEBIT_SPREAD', 'live_full'),
  ('LONG_PUT_DEBIT_SPREAD', 'live_full'),
  ('SHORT_PUT_CREDIT_SPREAD', 'live_full'),
  ('SHORT_CALL_CREDIT_SPREAD', 'live_full'),
  ('IRON_CONDOR', 'live_full'),
  -- New strategies start in DESIGNED until manually flipped
  ('BULL_PUT_SPREAD_0DTE', 'designed'),
  ('CASH_SECURED_PUT', 'designed');
```

### Graduation logic — per strategy

```python
def evaluate_strategy_lifecycle(strategy_name, supabase):
    state = get_lifecycle_state(strategy_name)
    if state.current_state != 'experimental':
        return  # only EXPERIMENTAL strategies graduate

    # Reuse get_alpaca_real_closed_trades, filter by strategy_name
    real_trades = get_alpaca_real_closed_trades(
        user_id=user_id, supabase=supabase
    )
    strategy_trades = [
        t for t in real_trades
        if t.get('strategy') == strategy_name
    ]
    cumulative_pl = cumulative_realized_pl(strategy_trades)
    trade_count = len(strategy_trades)

    if cumulative_pl > 0 and trade_count >= 3:
        promote_strategy_to_full(strategy_name, cumulative_pl, trade_count)
        # Writes alert: strategy_graduated_to_full
```

### Helper extension

`get_alpaca_real_closed_trades` (just shipped in PR #883) doesn't carry `strategy` column today. Schema check:

```sql
-- paper_positions has 'strategy' column? check before assuming
SELECT column_name FROM information_schema.columns
WHERE table_name = 'paper_positions' AND column_name LIKE '%strateg%';
```

If `paper_positions.strategy` exists, the helper just needs to add it to the SELECT. If not, the helper joins `trade_suggestions` to recover strategy_name.

### Sizing engine integration

EXPERIMENTAL strategies size at minimum (1 contract regardless of risk-pct math):

```python
# In sizing_engine, after computing risk-pct sizing
strategy_state = get_lifecycle_state(candidate.strategy)
if strategy_state.current_state == 'experimental':
    # Override to minimum sizing
    contracts = max(1, contracts)  # minimum, not floor
    contracts = min(contracts, 1)  # cap to 1
```

When EXPERIMENTAL graduates to LIVE_FULL, the override drops away naturally.

### Scheduler integration

Two options:
- **Piggyback** on `daily_progression_eval` (4 PM CT daily). Each user-loop iteration evaluates lifecycle for all EXPERIMENTAL strategies. Reuses the `get_alpaca_real_closed_trades` call already happening.
- **Separate** `strategy_lifecycle_eval` job at 4:50 PM CT (after post_trade_learning). More observability but adds a scheduler entry.

**Recommendation:** piggyback on `daily_progression_eval` initially. If lifecycle eval grows complex, split out later.

---

## STEP 6 — Pre-trade comparison framework

**Already exists, no design needed.** Per Step 3, the scanner already:
1. Computes per-candidate score (`calculate_unified_score`)
2. Computes per-candidate EV (`calculate_ev`)
3. Sorts by `(score, symbol)` and picks top-N per tier
4. Retries with fallback candidates if primary fails downstream gates

New strategies (0DTE, CSP) just need to flow through the same scoring path. Iron condor already has its own EV-aware combo selection (`_select_best_iron_condor_ev_aware`); 0DTE bull put would have a similar structure.

The operator's stated insight ("calculation should be compared before a trade is executed") is implemented. Phase 2 doesn't need to design comparison logic — just needs to ensure new strategies produce score + EV values that fit the existing scale.

---

## Phase 2 PR sequencing

### PR-1 — Per-strategy realized P&L helper extension (~half day)

- Extend `get_alpaca_real_closed_trades` with optional `strategy_name` filter
- Add `get_strategy_eligibility(strategy_name, user_id, supabase)` returning `{eligible, cumulative_pl, trade_count}` matching the tier-promotion shape
- Tests: 6-8 unit tests on filter behavior

### PR-2 — Strategy lifecycle states table + scheduler hook (~half day)

- Migration: `strategy_lifecycle_states` table + initial seed
- `evaluate_strategy_lifecycle()` function in `progression_service.py` (or new `strategy_lifecycle_service.py`)
- Hook into `daily_progression_eval` to call once per day per EXPERIMENTAL strategy
- Tests: graduation logic + state transition + audit log

### PR-3 — Sizing engine EXPERIMENTAL override (~half day)

- Read lifecycle state in sizing engine
- EXPERIMENTAL → cap sizing at 1 contract
- LIVE_FULL → no override (existing behavior)
- DESIGNED/DEPRECATED → strategy already filtered out by scanner via `banned_strategies` (lifecycle service writes to env or table)
- Tests: 4-6 unit tests on size-override behavior

### PR-4 — 0DTE bull put spread + intraday cadence (~3-4 days)

- New strategy entry in `strategy_selector.py`
- Scanner DTE filter: support same-day expiry under feature flag
- Intraday cadence refactor: existing `intraday_risk_monitor` runs every 15 min; either accelerate during 0DTE-active windows OR add `intraday_0dte_monitor` at every-5-min cadence
- Force-close-by-3:55-PM logic
- Tests: heavy — scanner integration, exit lifecycle, settlement timing

### PR-5 — Cash-secured-put + capital gating (~3-4 days)

- New strategy entry in `strategy_selector.py`
- Single-leg structure: sizing engine accepts 1-leg candidates with `collateral_required` field
- Capital gate: `EQUITY_THRESHOLD_CSP = 5000.0`; below threshold, strategy stays in DESIGNED state regardless of operator flip
- Auto-close-before-expiry semantics initially (no equity-assignment handling)
- Tests: capital gate, sizing math, auto-close timing

### PR-6 — Per-strategy emission counts in observability (~half day)

- Surface emission counts per strategy per day in scanner cycle logs / job_runs result envelope
- Closes #103 backlog item ("Regime → strategy selection breadth audit") by making the breadth empirically observable

---

## Open questions for operator

1. **Bear-put-spread + iron condor are already coded.** Phase 2 ships lifecycle gating, NOT new strategy code for these two. Confirm that matches operator's mental model — the rewrite scope shrinks if so.

2. **Scheduler integration:** piggyback on `daily_progression_eval` (recommended) or add a new `strategy_lifecycle_eval` scheduler entry?

3. **Initial lifecycle seeds:** mark all 5 existing strategies as `live_full` (preserves current behavior) or downgrade `LONG_PUT_DEBIT_SPREAD` and `IRON_CONDOR` to `experimental` (forces re-validation)? Recommended: live_full — they have history.

4. **0DTE polling refactor:** accelerate `intraday_risk_monitor` (touches a load-bearing job) or add parallel `intraday_0dte_monitor` (more code, less risk to existing path)?

5. **CSP capital gate:** $5K threshold (recommended for retail-relevant strikes) or lower for testing-only deployment on cheap underlyings (e.g., < $10 stocks)?

6. **EXPERIMENTAL sizing override location:** sizing_engine (recommended) or a separate decoration step before sizing? Either works; sizing_engine is the natural home.

7. **DEPRECATED state mechanism:** how does a strategy enter DEPRECATED? Manual operator flag (recommended) or auto-detection of repeated failures (more code)?

---

## Doctrine cross-references

- This diagnostic explicitly applied **Anti-pattern 9** ("Syntactic-only verification of dead code paths") from `loud_error_doctrine.md` — verified strategy emission via production data (`SELECT DISTINCT strategy FROM trade_suggestions`) instead of inferring from code paths alone.
- The operator's "calculate before execute" intent is satisfied by **H7 doctrine** ("Operations preserve capital invariants in both directions") + the existing `unified_score` infrastructure. Phase 2 doesn't violate either.
- Strategy lifecycle states reuse the **`get_alpaca_real_closed_trades` shared helper** from PR #883, maintaining the canonical "real trade" lens across all promotion-shaped systems.
