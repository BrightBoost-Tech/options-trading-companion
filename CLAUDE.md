# Options Trading Companion — Project Context
# Loaded by Claude Code on EVERY turn. Keep this current.

For new-contributor onboarding, see README.md.
For AI session context, this file is loaded every turn.

---

## Identity & Repo

- **Repo:** BrightBoost-Tech/options-trading-companion
- **Owner User ID:** 75ee12ad-b119-4f32-aeea-19b4ef55d587
- **Stack:** Python 3.11 / FastAPI backend (`packages/quantum`) · Next.js
  frontend (`apps/web`) · Supabase Postgres · Railway deploy · APScheduler
  (primary) · GitHub Actions (fallback) · Alpaca broker + market data (primary) ·
  Polygon.io (Stocks Starter + Options Developer, $108/mo, primary path for snapshots/bars where Alpaca paper account lacks SIP entitlement)

---

## Current Phase

- **Phase:** `micro_live` (sizing tier indicator; flipped 2026-04-25 17:10:36Z). Phase name is operator-set documentation; affects sizing tier resolution but is **NOT a valid EXECUTION_MODE value**.
- **EXECUTION_MODE env:** must be one of `internal_paper`, `alpaca_paper`, `alpaca_live`, `shadow`. Routes broker submissions accordingly. For live trading, also requires `LIVE_ENABLED=true` (second-stage safety check at `execution_router.py:88-94` falls back to `alpaca_paper` otherwise).
- **Promotion type:** manual operator-initiated. Green-day gate (1/4) bypassed; continuous-growth model adopted. Audit `risk_alerts.id = 82f1c294-19a4-4c66-8a68-0b0811ef5b24`.
- **Account:** live Alpaca `211900084`, options Level 3
- **Starting capital:** $500 on `v3_go_live_state.paper_baseline_capital` (set 2026-04-25 15:38:04Z, audit `c9d87caf-24db-4f7f-842a-748620a5c84f`)
- **Open positions:** 0
- **Settlement:** `options_buying_power = $501.61` as of 2026-05-10 (ACH settled; equity $801.61, position_market_value $265 across the open CSX 43/47 debit spread)
- **Universe:** 62 symbols. PR #804 added F, BAC, SOFI, T, KO, VZ; sync triggered 2026-04-25 17:17Z (job_run `25eec261-d3e3-4b4a-aefe-2865770b001d`).
- **Pipeline status:** Full end-to-end pipeline validated 2026-04-10
- **daily_progression_eval:** Running at 16:00 CT. The alpaca_paper → micro_live promotion gate has been bypassed (operator-initiated promotion). Future phase transitions are a deferred decision under the continuous-growth model.
- **Auto-promotion gates (micro_live → full_auto):** `promotion_check` handler auto-promotes when ALL pass — (1) broker equity ≥ $1500, (2) cumulative_realized_pl > 0 across Alpaca-real closed trades, (3) alpaca_real_trade_count ≥ 3. Manual override (`ProgressionService.promote(...)`) preserved as bypass.
- **Iron condors:** Enabled. Triggered by strategy_selector when regime is CHOP, or sentiment is NEUTRAL/EARNINGS with high IV (iv_rank>50 or ELEVATED/SHOCK/REBOUND regime). Recent regimes have been NORMAL with directional sentiment → debit spreads dominate the output stream. This is regime-driven natural selection, not banning. No tier-aware or phase-aware disable mechanism exists in code (verified 2026-04-30).
- **Calibration job:** Running daily at 05:00 CT; writes to `calibration_adjustments`.
- **Risk profile:** micro-tier — 90% per trade × regime_mult, one position at a time (see "Risk per trade math"). Hard cutoff at $1000 (standard tier behavior above). Operator spec 2026-04-27.
- **Phase 2 contract:** enforced — `check_close_reason_enum` (9 values), `check_fill_source_enum`, `close_path_required` constraints intact

---

## Infrastructure

| Service | URL / Location |
|---|---|
| Backend (Railway) | https://be-production-48b1.up.railway.app |
| Frontend (Railway) | https://fe-production-d711.up.railway.app |
| Worker (Railway) | worker.railway.internal (internal) — RQ queue `otc`, start: `rq worker otc` |
| Worker-background (Railway) | worker-background.railway.internal (internal) — RQ queue `background`, start: `rq worker background` (added 2026-05-16) |
| Supabase project | etdlladeorfgdmsopzmz.supabase.co |
| GitHub Actions | Manual dispatch only (APScheduler is primary) |

**Worker queue topology (2026-05-16):**

- **`otc` queue (primary worker):** all trading-day pipeline jobs — `suggestions_open`, `suggestions_close`, `paper_auto_execute`, `paper_exit_evaluate`, `intraday_risk_monitor`, `iv_daily_refresh`, `alpaca_order_sync`, etc. Default for `enqueue_job_run(...)`.
- **`background` queue (worker-background):** long-running jobs that would otherwise starve the primary queue. Currently routes only `iv_historical_backfill`. Future long-running handlers should also be routed here by passing `queue_name=BACKGROUND_QUEUE` to their route's `enqueue_job_run(...)` call.

### Key Environment Variables (Railway backend unless noted)
| Variable | Value | Purpose |
|---|---|---|
| EXECUTION_MODE | `alpaca_paper` | Phase selector (paper/micro_live/live) |
| SCHEDULER_ENABLED | `1` | Enables APScheduler (primary scheduler) |
| ORCHESTRATOR_ENABLED | `1` | Autonomous Day Orchestrator |
| CALIBRATION_ENABLED | `1` | Master switch for calibrated EV/PoP |
| RISK_ENVELOPE_ENFORCE | `1` | Force-close enabled (upgraded from warn-only 2026-04-16) |
| RANKER_PORTFOLIO_AWARE | `1` | Canonical ranker sees open positions |
| CANONICAL_RANKING_ENABLED | `1` | Use risk-adjusted EV sort |
| COMPOUNDING_MODE | `true` | 8% base risk + 1.2× boost for micro tier |
| RISK_MAX_SYMBOL_PCT | `0.40` | Paper phase — tighten to 0.30 at micro_live |
| RISK_MAX_DAILY_LOSS | `0.08` | 8% daily loss cap |
| RISK_MAX_WEEKLY_LOSS | `0.10` | 10% weekly loss cap |
| SNAPSHOT_CACHE_TTL | `120` | Seconds; env-configurable |
| OPTION_CHAIN_CACHE_TTL | `300` | Option chain cache TTL |
| ALPACA_API_KEY / ALPACA_SECRET_KEY | set | Alpaca credentials |
| ALPACA_PAPER | `true` | Route to paper endpoint |
| TASK_NONCE_PROTECTION | `1` | Security v4 nonce replay protection |
| TASK_NONCE_FAIL_CLOSED_IN_PROD | `1` | Fail closed if nonce store unavailable |
| TASK_SIGNING_KEYS | set | HMAC keys for /tasks/ endpoint signing |

### Critical env var: paper-vs-live mode

There are TWO env vars with similar names that control different layers:

- **`ALPACA_PAPER`** (Railway BE/worker): read by application code in
  `packages/quantum/brokers/`. Controls whether the trading service routes
  orders to paper or live Alpaca. Currently `false` post-promotion.
- **`ALPACA_PAPER_TRADE`** (alpaca-mcp-server, `.claude.json` env block):
  read by the alpaca-mcp-server library to choose endpoint URL
  (`paper-api.alpaca.markets` vs `api.alpaca.markets`). Defaults to
  `"true"` if unset.

**BOTH must be set to `false` for live trading.** Setting only one
produces a partial-state where one layer talks paper and another talks
live. Verified 2026-04-25 by reading alpaca-mcp-server source — the lib
reads `ALPACA_PAPER_TRADE` specifically; Railway-side application code
reads `ALPACA_PAPER`.

### Alpaca live key prefix gotcha

Alpaca live Trading API keys for this account use the **AK** prefix.
Public Alpaca docs reference `PK` as the typical format, but live keys
for some accounts use `AK`. Confirmed live and working as of 2026-04-25.

Paper keys consistently use `PKPR2` prefix. Distinguishing rule:
- Endpoint `https://api.alpaca.markets` = live (key prefix may be `AK` or `PK`)
- Endpoint `https://paper-api.alpaca.markets` = paper (key prefix `PKPR…`)

### Flags in use — single source of truth

**Permanently on** (do not flip without a code change):
`TASK_NONCE_PROTECTION=1`, `TASK_NONCE_FAIL_CLOSED_IN_PROD=1`,
`SCHEDULER_ENABLED=1`, `ORCHESTRATOR_ENABLED=1`, `CALIBRATION_ENABLED=1`,
`RISK_ENVELOPE_ENFORCE=1`, `RANKER_PORTFOLIO_AWARE=1`,
`CANONICAL_RANKING_ENABLED=1`, `MULTI_STRATEGY_EVAL=1`, `COMPOUNDING_MODE=true`,
`PAPER_AUTOPILOT_ENABLED=1`, `POLICY_LAB_ENABLED=true`,
`ALLOCATION_V4_ENABLED=true`, `FORECAST_V4_ENABLED=true`,
`OPTIMIZER_V4_ENABLED=true`, `REGIME_V4_ENABLED=true`, `SURFACE_V4_ENABLE=true`,
`SHADOW_CHECKPOINT_ENABLED=1`.

**Permanently off**:
`AUTOTUNE_ENABLED=false`, `POLICY_LAB_AUTOPROMOTE=false`,
`PDT_PROTECTION_ENABLED=0`, `ALPACA_DRY_RUN=0`, `ENABLE_DEV_AUTH_BYPASS=0`.

**Kill switches** (flip to disable feature instantly):
`SCHEDULER_ENABLED`, `CALIBRATION_ENABLED`, `RISK_ENVELOPE_ENFORCE`.

---

## Architecture (v4 — 16 Layers + 4 Managed Agents)

1. Market Data (Alpaca primary by design; Polygon Starter + Options Developer is de facto primary for paper-account paths since Alpaca paper lacks SIP)
2. Backtesting
3. Observability
4. Security
5. Regime Engine
6. Forecast Layer
7. Capital Allocation
8. Optimizer / Suggestion Engine
9. Execution (Alpaca)
10. Risk & Capital
11. Learned Nesting
12. Automation
13. Quant Agents
14. UI/UX (Next.js, `apps/web`)
15. Quantum
16. Regression / Determinism Bot

### Managed Agents
| Agent | Trigger | Purpose | agent_sessions rows? |
|---|---|---|---|
| Day Orchestrator | 7:30 AM CT | Boot check, missed-job detection | ✅ yes |
| Loss Minimization | Every 15 min during market hours | Intraday envelope monitoring + force-close | ✅ yes (since 2026-05-04) |
| Self-Learning | 4:45 PM CT | Post-trade calibration + drift detection | ✅ yes (since 2026-05-04) |
| Profit Optimization | apply_calibration during suggestions | Calibrated EV/PoP from learned adjustments | ❌ no (per-call function — different mechanism needed) |

Day Orch, Loss Min, Self-Learning write `agent_sessions`. Profit Optimization is a per-call function, deferred (would touch `workflow_orchestrator.py` which is the highest-blast-radius file).

### Replay / forensic subsystem (gated off)

`data_blobs`, `decision_runs`, `decision_inputs`, `decision_features` exist
in code (`services/replay/`), gated off via `REPLAY_ENABLE=0`. Designed for
post-incident forensics. Not active. Evaluate after micro_live stabilizes —
either wire up or remove using the v4-accounting playbook.

### v4 PnL ledger subsystem (dormant)

`position_legs`, `position_groups`, `position_leg_marks` exist in code
(`services/position_pnl_service.py` + handlers `jobs/handlers/refresh_ledger_marks_v4.py`
+ `jobs/handlers/run_market_hours_ops_v4.py`), not wired to `scheduler.py`.
Zero rows in all three tables; zero `job_runs` for `refresh_ledger_marks_v4`
in 30 days. Same operational shape as the Replay subsystem above. Evaluate
after micro_live stabilizes — either wire up or remove using the
v4-accounting playbook. H9-compliant as of 2026-05-18 (PR #968 migrated the
3 silent-swallow sites — see `docs/bugs_fixed_history.md`).

---

## Market Data Provider Routing

| Data Type | Primary | Fallback |
|---|---|---|
| Options snapshots (MTM) | Alpaca `/v1beta1/options/snapshots` | Polygon `/v3/snapshot` |
| Option chains (scanner) | Alpaca `/v1beta1/options/snapshots/{underlying}` | Polygon `/v3/snapshot/options/{underlying}` |
| Equity snapshots | Alpaca `/v2/stocks/snapshots` | Polygon `/v3/snapshot` |
| Daily bars (IV rank, trend) | Alpaca `/v2/stocks/bars` | Polygon `/v2/aggs` |
| Equity quotes (NBBO) | Alpaca `/v2/stocks/quotes/latest` | Polygon `/v2/last/nbbo` |
| Equity prev close | Alpaca `/v2/stocks/snapshots` (prev_daily_bar) | Polygon `/v2/aggs/prev` |
| Earnings dates | Polygon `/vX/reference/financials` | — |
| Historical contracts | Polygon `/v3/reference/options/contracts` | — |
| Account equity | Alpaca `get_account()` | — (no fallback; skip loss envelopes) |
| Weekly P&L | Alpaca `get_portfolio_history(1W/1D)` | — (no fallback; skip weekly envelope) |

**Runtime note (2026-04-27):** the Primary/Fallback ordering above
reflects design intent. In practice, Alpaca paper accounts lack
SIP entitlement (`subscription does not permit querying recent
SIP data` errors on equity bars), so many calls fall through to
Polygon despite the table's "Alpaca primary" labeling. Polygon
plan upgrade ($108/mo, see *Polygon dependency status*) makes
this de facto path durable. Resolution of the SIP gap depends on
live Alpaca account entitlements (backlog #88).

---

## Daily Cron Pipeline (APScheduler — primary)

```
5:00 AM   calibration_update
7:30 AM   day_orchestrator (boot check)
8:00 AM   suggestions_close → 8:15 paper_exit_evaluate (morning)
9:30-4:00 alpaca_order_sync (every 5 min) + intraday_risk_monitor (every 15 min)
11:00 AM  suggestions_open → 11:30 paper_auto_execute
3:00 PM   paper_exit_evaluate (afternoon) → 3:30 paper_mark_to_market
4:00 PM   daily_progression_eval → 4:10 learning_ingest → 4:20 paper_learning_ingest
4:30 PM   policy_lab_eval → 4:45 post_trade_learning
5:00 PM   promotion_check
```

- `paper_learning_ingest` MUST run after exits close each day or the learning view stalls
- `post_trade_learning` runs after learning_ingest to close the feedback loop
- GitHub Actions `trading_tasks.yml` is fallback (manual dispatch only)

**Weekend behavior (Mon-Fri only):** All scheduled jobs are Mon-Fri only — `day_of_week='mon-fri'` is applied uniformly at `packages/quantum/scheduler.py:212-217` (and the non-SCHEDULES `auto_retry_failed` job at 236-248). Saturday/Sunday silence is expected. Operator-driven HTTP triggers via `scripts/run_signed_task.py` work normally over weekends. When investigating weekend silence (no `job_runs` over a weekend window), confirm Mon-Fri scheduling before assuming outage.

---

## Testing & CI

- **Python 3.11 required** (project uses features incompatible with 3.14+ via
  the `qci-client` dependency; sentinel in `packages/quantum/__init__.py`).
- **CI workflow** `.github/workflows/ci-tests.yml` runs `pytest
  packages/quantum/tests/` on every push and PR. Green is required.
- **Every code PR must include regression tests for any bug it fixes.**
- **Test deletion discipline:** when removing production code, the PR
  description must explicitly state which tests are being deleted and
  confirm no retained surface is exercised by those tests. If a test covers
  both removed and retained surface, split the file before deletion.
- No PR merges to main until CI is green (branch-protection enforced).

---

## Migrations

Supabase migrations do NOT auto-apply on merge. Full migration apply procedure at `docs/migration_procedure.md`.

---

## Key Database Tables

| Table | Purpose |
|---|---|
| `paper_positions` | Open/closed paper positions |
| `paper_orders` | Order fills (execution_mode: internal_paper or alpaca_paper) |
| `go_live_progression` | Current phase + green days count (canonical) |
| `go_live_progression_log` | Audit trail of phase events |
| `v3_go_live_state` | Older readiness table — still written by validation_shadow_eval |
| `policy_lab_cohorts` | 3 active cohorts (conservative / moderate / aggressive) |
| `learning_trade_outcomes_v3` | VIEW: realized P&L joined with suggestions |
| `learning_feedback_loops` | Raw outcome records from paper/live ingest |
| `calibration_adjustments` | EV/PoP multipliers (stored as JSONB `adjustments` keyed by segment) |
| `paper_eod_snapshots` | Daily MTM marks per position |
| `job_runs` | Job execution log (idempotency + status) |
| `risk_alerts` | Risk violations, force-close events, drift alerts |
| `policy_decisions` | Per-cohort accept/reject decisions with realized_outcome |
| `agent_sessions` | Managed Agent session observability (Day Orch + Loss Min + Self-Learning write; Profit Optimization deferred — see Managed Agents table) |

### Instrumentation coverage (per-cycle writes)

What each `suggestions_open` cycle writes for observability, post-2026-05-18 instrumentation fixes:

**`job_runs.result` (FIX 1):** every cycle that reaches the happy path writes a structured dict with:

- `result.counts.universe_size` — symbol count entering scanner (post-filter)
- `result.counts.scanner_emitted` — candidates passing scanner gates
- `result.counts.trade_suggestions_created` — rows inserted to `trade_suggestions`
- `result.counts.h7_passed` / `edge_above_minimum` / `executable` / `staged` — funnel subset counts (post-PR allocator integration these become more independent; today they're approximated from `created` since rejection paths increment `rejection_stats` in a single bucket)
- `result.counts.candidates` / `created` / `existing` — legacy keys preserved for backward-compat
- `result.counts.rejection_persist_failures` — H9 verification metric (FIX 2)
- `result.cycle_metadata.regime` / `tier` / `open_position_count` / `available_envelope_dollars` / `deployable_capital`

Early-return paths (fast-path, no_candidates, scanner_failed) keep their existing minimal counts shape — these paths didn't reach the funnel gates, so the full breakdown would be misleading.

**`suggestion_rejections` (FIX 2):** every `RejectionStats.record()` call inside a `set_symbol(symbol)` context writes one row. `RejectionStats` is constructed in `options_scanner.scan_options()` with `supabase + cycle_date + job_run_id` — see `options_scanner.py:~2346` and the Tier 1C 2026-05-13 instrumentation block. Failures are fail-soft per H9 doctrine anti-pattern 5 (observability writes must not undo primary work), but the failure count surfaces via `rejection_persist_failures` in cycle counts so silent drift is visible.

**`paper_orders.submitted_at` + `filled_at` (FIX 3):** internal-fill close path (`paper_exit_evaluator.py:~1270`) now writes BOTH timing fields. Pre-fix only `filled_at` was populated, breaking exit-side latency analysis for `target_profit_hit` (the most common exit). For internal fills, `submitted_at == filled_at` is intentional — submission and fill happen in the same call site. Alpaca-path submissions write `submitted_at` separately upstream.

### Quick Health Check SQL
```sql
-- Phase status
SELECT current_phase, alpaca_paper_green_days, alpaca_paper_last_green_date
FROM go_live_progression;

-- Open positions (authoritative: must match Alpaca get_all_positions())
SELECT symbol, quantity, avg_entry_price, current_mark, unrealized_pl, status
FROM paper_positions WHERE status = 'open' ORDER BY created_at DESC;

-- Today's job runs
SELECT job_name, status, finished_at FROM job_runs
WHERE created_at::date = CURRENT_DATE ORDER BY created_at;

-- Risk alerts (last 24h)
SELECT alert_type, severity, symbol, message, created_at FROM risk_alerts
WHERE created_at > NOW() - INTERVAL '24 hours' ORDER BY created_at DESC;

-- Latest calibration adjustments (JSONB blob keyed by segment)
SELECT computed_at, total_outcomes, jsonb_object_keys(adjustments) AS segment
FROM calibration_adjustments ORDER BY computed_at DESC LIMIT 5;

-- Drill into a specific segment's multipliers
SELECT computed_at, adjustments->'LONG_CALL_DEBIT_SPREAD:normal:0_21'
FROM calibration_adjustments ORDER BY computed_at DESC LIMIT 3;

-- Today's learning outcomes (trade closes only; filter predates the
-- 2026-04-13 pnl-corruption cutoff — see docs/bugs_fixed_history.md)
SELECT COUNT(*), ROUND(AVG(pnl_realized),2)
FROM learning_feedback_loops
WHERE outcome_type='trade_closed'
  AND created_at >= '2026-04-13'
  AND created_at::date = CURRENT_DATE;

-- Agent sessions (Day Orch + Loss Min + Self-Learning write today;
-- Profit Optimization deferred — see Managed Agents table)
SELECT agent_name, status, COUNT(*), MAX(started_at)
FROM agent_sessions
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY agent_name, status
ORDER BY agent_name, status;
```

---

## Cohort architecture

- 3 cohorts (conservative / neutral / aggressive). Live trade routing reads `policy_lab_cohorts.promoted_at` via `packages/quantum/policy_lab/champion.py::get_current_champion`. Defensive fallback to `"aggressive"` when no cohort is promoted (e.g., transition windows).
- Decision logging (`policy_decisions`) + daily scoring (`policy_daily_scores`) are functional.
- `promoted_at` set on `aggressive` per operator intent (migration `20260518000001_promote_aggressive_cohort.sql`). Pre-PR misalignment (operator manual UPDATE 2026-04-02 had set neutral) corrected by that migration.
- The 2 silent-failure `is_champion` query sites (`paper_autopilot_service._get_champion_portfolio`, `paper_exit_evaluator._resolve_position_cohort` path 3) are rewritten to query `promoted_at`. The H9 anti-pattern (`try/except: pass`) is eliminated at both sites.

Full architecture, sizing duality, and integration-seam closure rationale at `docs/cohort_architecture.md`. Doctrine: `docs/loud_error_doctrine.md` H13 — Parallel architectures without integration.

---

## Risk per trade math

Per-trade sizing is tier-aware. Single producer of `max_risk_per_trade`:
`RiskBudgetEngine.compute_budgets()`, mirroring
`SmallAccountCompounder.calculate_variable_sizing` for consistency.
The two layers are kept in sync — if you change one, change the other.

### Tier definitions

| Tier | Capital | Per-trade base | Multipliers | max_trades | Notes |
|---|---|---|---|---|---|
| micro | $0–$1000 | **90%** | regime only | **1 (one at a time)** | |
| small | $1k–$5k | **25% (allocation-aware)** | full stack via PortfolioAllocator + score_skew | 4 | allocation-aware; see `docs/small_tier_allocation.md` |
| standard | $5k+ | 2% | full stack | 5 | |

**Hard cutoff at $1000** — no smooth interpolation.

### Multiplier behavior

`regime_mult`: 1.0 normal · 0.9 suppressed · 0.8 elevated · 0.5 shock
· 1.0 chop · 1.0 rebound.

For **micro tier**: `final_risk_pct = 0.90 × regime_mult`. Score and
compounding multipliers are intentionally bypassed (operator spec
2026-04-27). `STRATEGY_TRACK` env value has no effect at micro tier —
the engine takes the tier-aware branch before the risk_profile switch.

For **small tier** (post-2026-05-18 allocation-aware policy):
per-trade sizing flows through `PortfolioAllocator` which distributes
capital across the viable candidate set in a single cycle. The
per-trade math is:

- Global envelope: `0.85 × regime_mult × total_equity` (less
  open-position cost basis)
- Per-candidate base: `0.85 / n_candidates` of total equity (where
  `n_candidates = min(viable_count, 4)`)
- Score skew: `clamp(0.8 + (score − median_score)/50 × 0.4, 0.8, 1.2)`
  — same clamp range as the pre-existing `score_mult` formula
- Per-trade ceiling: **36%** of total equity (binding when allocation
  math produces a larger raw value, e.g., single-candidate case)
- See `docs/small_tier_allocation.md` for full spec + 5 worked examples

For **standard tier**: full stack (unchanged):
`final_risk_pct = base_risk_pct × score_mult × regime_mult × compounding_mult`.

- `score_mult = clamp(0.8 + (score − 50)/50 × 0.4, 0.8, 1.2)`.
  Examples: score 50→0.80, 75→1.00, 85→1.08, 100→1.20.
- `compounding_mult`: standard tier never gets the boost.

**Compounding-off safety override** (small tier only, retained
behavior): when `COMPOUNDING_MODE=false`, small-tier path falls
back to the legacy `0.02 (2%)` base computation if the allocator
is bypassed (e.g., test environments). Production small-tier path
always goes through the allocator. Micro tier ignores the
compounding flag entirely.

### Allocation-aware sizing (small tier)

Introduced 2026-05-18 (see `docs/small_tier_allocation.md`). Replaces small tier's per-trade `3% × multipliers` independent-sizing pattern with a cycle-aware allocator that distributes capital across the viable candidate set BEFORE per-trade sizing fires. `PortfolioAllocator` runs once per entry cycle, takes the candidate set + total equity + regime + open positions as inputs, and returns per-candidate allocated budgets. `RiskBudgetEngine` and `SmallAccountCompounder` both accept an optional `allocation_hint` parameter; when provided (small-tier production path), it overrides the legacy per-trade multiplier stack. When absent (test paths, micro tier, standard tier), legacy behavior is preserved.

### Concurrency policy (micro tier)

Asymmetric by design:

- **Midday cycle (entries)**: blocks new entries when any position is
  open. Returns `skipped=True, reason='micro_tier_position_open'`.
- **Morning cycle (exits)**: continues normally with a tier observation
  log line (`[Morning] tier=micro, open_positions=N, exits_continuing`).
  Gating it would prevent exit suggestion generation for open
  positions and dead-lock the account.

The "one trade at a time" rule applies to position acquisition, not
position management. A future PR that "fixes" the apparent asymmetry
by adding a gate to morning cycle would break exit auto-generation —
`test_workflow_orchestrator_micro_concurrency.TestMorningCycleNoConcurrencyGate`
defends against that mistake.

### Per-symbol risk envelope (live trading)

Under any EXECUTION_MODE that uses live equity (`alpaca_live`,
`alpaca_paper`), the intraday risk monitor enforces a per-symbol
stop based on `RISK_MAX_SYMBOL_LOSS` env (default `0.03` = 3%).

- On a $500 live Alpaca account: 3% = **$15 stop per symbol**.
- On a $500 live Alpaca account: 5% = $25 stop per symbol.

The stop is intentionally tight for capital preservation in
`micro_live` phase. **Expected operational behavior:**
- Frequent intraday force-closes on small adverse moves
- Per-trade realized losses typically $5-15
- Round-trip Alpaca fees ~$1-2 per trade
- Each force-close that closes within the same trading session
  increments the PDT day-trade counter

**Day-trade counter awareness:** same-session entry+force-close
counts as 1 day-trade. Live Alpaca account 211900084 currently
at 0/3 day-trades. Three same-session round-trips in 5 business
days flips PDT status (`pattern_day_trader: true`), which has
downstream margin implications.

**Operator lever:** `RISK_MAX_SYMBOL_LOSS` env var. Tighter (3%)
= more force-closes, smaller per-trade losses. Looser (5%) =
fewer force-closes, larger per-trade losses but more position
survival. Recommend observing 1 week at 3% before adjusting.

Full risk-math worked examples, global allocation per-tier, universe price filter rationale, and history at `docs/risk_math.md`.

---

## Polygon dependency

- 63 production Polygon calls across 23 files; 11 services with direct dep.
- Plan: Stocks Starter + Options Developer ($108/mo). #87 resolved at the plan-tier level (2026-04-27).
- Tier 1/2/3 phase-out plan deferred (no longer urgent; provider redundancy / lock-in mitigation only). Full status at `docs/polygon_dependency.md`.

---

## 5 Open Code Gaps (priority order)

- **GAP 1** — Canonical ranking metric: expected PnL after slippage/fees ÷
  marginal risk, adjusted for correlation/concentration. DynamicWeightService
  lays groundwork; full implementation pending.
- **GAP 2** — EV-aware exit ranking: close worst marginal-EV positions first.
- **GAP 3** — Score/PoP/EV calibration against realized outcomes by strategy,
  regime, DTE, liquidity. Partially live via Self-Learning Agent.
- **GAP 4** — Autotune: replace threshold mutation with walk-forward validation.
- **GAP 5** — Production security flags (already set in Railway env, not code).
  Deployed 2026-04-09.

---

## Promotion Path

```
paper → micro_live ($500–$1K, Alpaca, 5 days) → live ($2.5–$5K, 30 days) → full
```

Gate to `micro_live`: 4 consecutive Alpaca paper green days (not internal fills).

---

## NEVER DO

- **Never merge a code-change PR without CI green.** If tests are broken,
  fix or skip with a tracking issue before merging any other work.
- **Never add a new `@pytest.mark.skip`** without: (a) opening a tracking
  issue with unskip criteria, (b) including the issue number in the reason
  string, (c) reviewer approval that the skip is justified. Skip count must
  trend down over time, not up.
- **Never write `paper_positions.status='closed'` directly.** Always use the
  canonical close helper. Duplicate close-order logic is the 2026-04-10 →
  04-15 class of bug.
- Count `internal_paper` execution_mode fills as green days — Alpaca fills only
- Enable iron condors during `alpaca_paper` phase
- Rebuild entire system prompt on every AI call (split static/dynamic)
- Start a new Claude Code session without `--continue` on this project
- Use ChatGPT mid-build — all architecture decisions live here; mixing tools creates drift
- Deploy without verifying `TASK_NONCE_PROTECTION=1` in Railway
- Touch intraday_risk_monitor.py or risk_alerts migration without reading this file
- Enable `PROFIT_AGENT_RANKING=1` — flag is retired (2026-04-16), ignored by code
- Fabricate equity or weekly_pnl inputs when Alpaca is unavailable — skip the
  envelope with a warning instead (pattern in `_check_user` post-83872db)

---

## Bugs Fixed

### Recently fixed (last 7 days)

- 2026-05-18: H9 legacy sweep 3-of-3 closed (PR #968) — `position_pnl_service.refresh_marks_for_user` + `compute_group_nlv` migrated to `alert()` shape at 3 swallow sites. Allow-list 5 → 4 entries (remaining 4 are chain-level-verified false positives + the analyzed-and-deferred `alpaca_order_sync.sync_orders`). Function is part of the dormant v4 PnL ledger subsystem; H9 fix is correct shape if/when the subsystem wires up
- 2026-05-18: H9 legacy sweep (2 of 3 closed) — `universe_service.sync_universe` print-swallow → `alert()`; `iv_point_service.upsert_point` deleted as dead code (zero production callers; canonical write path is `IVRepository.upsert_iv_point`). Allow-list 7 → 5 entries
- 2026-05-18: #62a-D1 architectural seam closure — fork.py:67 now reads `promoted_at` via `get_current_champion` helper; 2 silent-failure `is_champion` query sites rewritten; H13 doctrine entry codified; migration `20260518000001_promote_aggressive_cohort.sql` ships with the PR
- 2026-05-18: H9 AST gate flipped to strict mode (warn-only → strict; allow-list held at 7 entries through the week; zero non-allow-listed violations at flip time)
- 2026-05-18: staleness-gate over-tightening on routine regimes (vendor-quality clause now regime-conditional)
- 2026-05-18: BUG-A scale-asymmetric unrealized_pl recompute in `intraday_risk_monitor._refresh_marks`
- 2026-05-18: BUG-C retry against already-closed position (4 sub-fixes across `intraday_risk_monitor` + `paper_exit_evaluator`)

Entries older than 7 days are appended verbatim to `docs/bugs_fixed_history.md` as part of normal PR hygiene. Full history at `docs/bugs_fixed_history.md`.

---

## Roadmap Status

Completed items, full priority breakdown, and retrospective findings (Notable findings dates, scope corrections, hygiene gaps) live in `docs/roadmap.md`.

Active priorities are tracked in the ## Backlog section below.

---

## Working Style

- Respond with exact SQL, exact Railway commands, exact file paths — no placeholders
- When fixing bugs: show the broken code, explain why it's wrong, show the fix
- When adding features: check GAP priority order before building new things
- Prefer minimal diffs over full rewrites
- Always check `job_runs` table before assuming a cron ran successfully

### Design principles

**Strategy availability vs threshold tuning.** Strategy-level pre-filtering at the scanner is not the preferred fix pattern for systemic rejection issues. Tune thresholds (per-tier, per-regime), not strategy availability. The scanner evaluates all strategies; downstream gates (spread, sizing, EV ranking) decide what makes it through. Rejection variety is information — disabling strategies hides signal we'd want to see.

Example anti-pattern (rejected 2026-04-30): after observing CMCSA short_*_credit_spread at 1150% width-to-credit ratio on cheap underlyings, recommended disabling credit spreads at micro tier. Operator correctly rejected this — instead, we raised the spread threshold (#92) and let the existing gates do their job.

**Round-trip safety as sizing invariant.** See `docs/loud_error_doctrine.md` "Operations preserve capital invariants in both directions" (the H7 doctrine) for the principle; PR #100 (round-trip BP at sizing) is the concrete application protecting against the BAC-class ghost-position incident (2026-05-01). Sizing must verify a position can be safely round-tripped within available buying power, not just that entry fits.

**Persistent worker deploys ≠ code restart.** See `docs/loud_error_doctrine.md` "Persistent worker deploys ≠ code restart" (the H8 doctrine). RQ + APScheduler workers on Railway do not auto-reload on code deploy — the new image ships to the service slot but the existing process keeps running the prior image. Any PR touching worker-resident code requires explicit "verify worker restarted" before validating the fix. Diagnostic shape: "PR shipped, deploy SUCCESS, behavior unchanged" almost always means the worker hasn't recycled yet. Origin: 2026-05-04 OBP-fix verification incident (PR #864 appeared stale at 17:46 UTC; was actually still in DEPLOYING).

**Wrapper drift on field-dependency introductions.** See `docs/loud_error_doctrine.md` Anti-pattern 8. When a fix introduces a NEW field dependency on an upstream provider, audit the WHOLE wrapper chain end-to-end — hand-built whitelist wrappers silently drop new fields and consumers fall through to safe defaults without alerting. Each layer in isolation looks correct; the defect is in the seam between layers. Origin: PR #849 (#93 broker-truth fix) took 5 days to take effect because `alpaca_client.py:200-225` dropped `options_buying_power`; fixed by PR #864 + alert at fallback site (PR #865).

**Verified-write across wrapper chains.** See `docs/loud_error_doctrine.md` "H9 — Verified-write across wrapper chains" — the higher-order doctrine sitting above Anti-patterns 2 and 8. When data flows producer → wrapper(s) → consumer through more than one boundary, the consumer must verify the side effect actually occurred, not infer success from intermediate "no exception raised" signals. Wrappers must return outcome (bool / Result / typed enum), not just absence-of-exception; consumers must verify at anchor checkpoints (independent queries that confirm end-to-end). PR-A Layer 4's `count_rows_for_date` post-loop check is the reference implementation. Origin: 2026-05-04 → 2026-05-10 cascade week — PR-A's 7-layer cascade (#115) + Issue B's 4-layer cascade (PR #908) + #62a sweep (D3/D5/D6/D8) + #864 alpaca_client field-drop + #117 DROPPABLE shim, all sharing the class shape. Cascading-cascade discipline: ship each layer independently so each fix's deploy validates the next-layer surface before fixing it.

**Ghost reconciliation is load-bearing for pipeline liveness.** See `docs/loud_error_doctrine.md` "H10 — Stale state cascades through pipeline gates". A single stale `paper_positions` row can suppress the entire trade pipeline by cascading through suggestions_open (micro-tier "one position" gate) → paper_auto_execute (per-symbol risk envelope cap) → intraday_risk_monitor (in-memory loss recompute → force-close attempt against phantom). Symptom is "system silent"; underlying state is loud gate diagnostics against the stale row. When operator manually intervenes (e.g., closing via Alpaca UI bypassing our submission chain), the FIRST follow-up action is DB reconciliation — before any other engineering work resumes. PR #98's `ghost_position` alerts are urgent operational signals, not informational noise. Origin: 2026-05-12 CSX ghost incident (reconciled in PR #921).

**Status-check baseline: critical alerts independent of operator framing.** See `docs/loud_error_doctrine.md` "H11 — Status-check methodology". Every operational status check or diagnostic that investigates an operator hypothesis ("did a trade happen?", "is the worker stale?") MUST also include a baseline section querying critical/high severity `risk_alerts` independently of the hypothesis. The operator's framing is the hypothesis under investigation, not the boundary of the investigation. Required baseline: `SELECT ... FROM risk_alerts WHERE created_at >= NOW() - INTERVAL '<window>' AND severity IN ('critical', 'high') ORDER BY created_at DESC`. Origin: 2026-05-12 morning status check missed 2 critical `paper_order_marked_needs_manual_review` alerts at 15:15Z because queries were anchored on `paper_positions`/`paper_orders` rather than `risk_alerts` directly.


## Backlog

Full backlog (item descriptions, sub-items, audit catalogs) lives in `docs/backlog.md`. This section keeps only the active focus.

### Operating mode — learning-mode at micro tier (declared 2026-05-12)

**Operator is in learning-mode at micro tier. Goal is code correctness + system behavior validation, NOT capital deployment.**

Current capital ($681, micro tier) is INTENTIONAL — not a constraint to escape. Micro tier is the development environment for perfecting entry/exit logic before scaling capital.

**Operator's stated framing:**

> "At micro tier I want to perfect the code and make sure it enters and exits accordingly. After these are perfected I will add more capital. Right now I want to focus on logic and learning to optimize the best list of options and the best combination for profits/time for the account."

**What this means operationally (for future sessions reading this file):**

DO:
- Recommend observability/analytics infrastructure work
- Recommend bug fixes as they surface
- Recommend diagnostics that surface system behavior
- Recommend doctrine/codification work that captures empirical findings
- Recommend strategy-mix observation (which strategies behave well at micro tier)
- Treat low trade frequency as a FEATURE of careful operation, not a problem

DO NOT:
- Recommend capital addition unless explicitly asked
- Push toward "more trades" framing as a goal
- Treat "no trade today" as a problem to fix when the system is working as designed
- Push toward tier-upgrade work (small/standard tier features) until operator signals readiness
- Treat warmup-window low frequency as a bottleneck to be eliminated

TREAT WITH CARE:
- Universe widening / strategy unlocking work — valuable for OBSERVATION (more behavior to learn from) but NOT for capital deployment goals
- Diagnostics that surface "system isn't trading enough" — first verify the framing is correct given learning-mode (system working correctly may not produce trades; that's expected). H11 baseline still fires on critical alerts; that's orthogonal to trade-frequency framing.

**Mode exit:** operator declares mode transition explicitly. No hard exit criteria. Likely signals (not triggers): operator explicitly says "I'm adding capital" or "moving past learning-mode"; operator asks about scaling decisions; operator references entry/exit reliability metrics as "good enough now." If unsure whether learning-mode still applies, ASK rather than assume.

**Source:** Tuesday 2026-05-12 afternoon strategic discussion. Tier inflection diagnostic surfaced the $1,000 cliff (micro→small per `small_account_compounder.py:24-50`); operator's explicit reframe redirected from "deploy capital efficiently" toward "perfect code, then scale." See `docs/backlog.md` "[2026-05-12] LEARNING-MODE CODIFICATION" entry.

**Related work shaped by this framing:**
- Lever 2 α (IV backfill, design diagnostic shipped 2026-05-12): valuable for observation surface during warmup, not capital deployment
- Path A (universe widening to $100, shipped 2026-05-12): valuable for candidate volume to observe, not for activity-maximization
- Observability / analytics infrastructure: HIGH priority — directly serves learning-mode goal
- Capital tier inflection at $1,000+: DEFERRED until operator signals readiness

### Active focus (next 3)

1. **PR #908 empirical validation (waiting on next natural close)** — PR #908's mleg sign-flip + clamp is live in the worker (verified 2026-05-12 H8 false-alarm investigation) but as of 2026-05-17 still untested on a real close: 0 paper_positions opened OR closed since 2026-05-12, so the validation event hasn't been triggerable. Validation remains valid; just dormant. Original framing ("tomorrow's first close") is stale — should be read as "whenever the next position closes naturally". Capture spec unchanged: `limit_price` sign, `abs(limit_price)` ≥ 0.01, broker response. Failure-mode triage in `docs/backlog.md` "Recent operational events" → PR #908 empirical validation entry. Also still on watch: Tier 1 body acceptance smoke (`python scripts/run_signed_task.py alpaca_order_sync --force-rerun`).
2. **H9 Convention Slot 2 — silent-exception grep test (queued, promoted from #3 2026-05-18 after #62a-D1 closed).** Slot 1 (AST gate) closed 2026-05-18 with strict-mode flip; allow-list stable at 7 entries since ship, zero non-allow-listed violations on main, this week's 6 PRs all passed the gate without expansion. Slot 2 was originally framed as a complementary regex/grep test for silent-exception shapes that AST inspection might miss; may consolidate with Slot 1 if Slot 1's surface proves adequate. Decision pending observation of strict-mode CI behavior over the next ~2 weeks. Slot 3 (Literal status returns) already adopted as convention for new wrappers; no separate PR needed.
3. **H9 legacy migration candidates — genuine-legacy arc CLOSED 2026-05-18.** All 3 originally-flagged candidates are resolved: `universe_service.sync_universe` migrated (PR #966), `iv_point_service.upsert_point` deleted as dead code (PR #966), `position_pnl_service.refresh_marks_for_user` migrated (PR #968). Allow-list shrunk 7 → 4 entries. The 4 remaining: 3 chain-level-verified false positives (`iv_repository.upsert_iv_point`, `execution_router.sync_positions`, `position_sync.sync_from_alpaca`) + 1 analyzed-and-deferred nested-handler refactor candidate (`alpaca_order_sync.sync_orders` — see `docs/sync_orders_analysis.md`). All 4 stay on the allow-list with 2026-08-12 forced re-review. NOTE: previous Active focus item (#62a-D1 architectural PR) closed 2026-05-18.

See `docs/roadmap.md` for the full Active focus block including recently-closed items and `docs/backlog.md` for full item descriptions and the catalogs (#62a schema drift, #72 loud-error doctrine).

### Operational state notes

**α IV pipeline:** full-universe historical `iv_rank` decidable for 67 of 70 active universe symbols (Phase 3 complete 2026-05-17). 2 symbols (WBD, XLK) at the 60-row threshold; 1 sparse (BKNG) at 30 rows — `daily_refresh` closes the BKNG gap naturally by mid-July 2026. IV-sensitive strategies (credit spreads, iron condors) are now decidable via `strategy_selector`'s existing `iv_rank` consumer paths. Full history at `docs/alpha_iv_history.md`.

### Exit thresholds (defaults under empirical review)

**Current values** (`paper_exit_evaluator.py:329-330`):

- `_DEFAULT_TARGET_PROFIT_PCT = 0.35` — Target profit fires at +35% of entry cost (env-overridable via `EXIT_TARGET_PROFIT_PCT`)
- `_DEFAULT_STOP_LOSS_PCT = 0.50` — Stop loss fires at -50% of entry cost (env-overridable via `EXIT_STOP_LOSS_PCT`)

**Time-scaling** (`paper_exit_evaluator.py:180-203`, stop-loss scaling 225-258):

- Profit target time-scales 50% (at entry) → 25% (near expiry) via sqrt-decay function, locking in profits before theta accelerates against winners.
- Stop loss is FLAT by default (no time-scaling). As of 2026-05-18, a symmetric sqrt-decay path exists for debit_spread stops, gated behind `EXIT_STOP_LOSS_TIME_SCALING_ENABLED=1` (default OFF). When enabled: sl tightens 50% → floor 0.30 (`EXIT_STOP_LOSS_FLOOR_PCT`). Iron condors explicitly bypass via `_is_iron_condor` guardrail. See `docs/audit_hold_period_asymmetry.md` for the audit (LOW confidence at N=6; sample 5+ weeks stale).

**Empirical observation as of 2026-05-13 (90-day window, paper_positions):**

| Strategy family | Exit type | N | Avg hold | Avg PnL |
|---|---|---|---|---|
| iron_condor | profit_target | 35 | 18.4h | +$1,852 |
| iron_condor | stop_loss | 1 | 96.4h | +$1,202* |
| debit_spread | profit_target | 9 | 56.4h | +$1,511 |
| debit_spread | stop_loss | 6 | 143.4h | -$2,063 |
| debit_spread | other_close | 13 | 89.9h | -$40 |

\* The single iron-condor stop_loss is profitable — wing-breach exit on already-profitable position. PR #929's `hold_period_buckets` v2 view buckets this as `profitable_stop` to avoid mislabeling.

Sample-size discussion, re-evaluation criterion (N=20 per outcome bucket), and what-this-does-not-claim caveats at `docs/exit_thresholds.md`.

### Structural findings (operational summary)

5 verified-fittable structure classes at $681 micro:

- **Class A** — 1-leg long options at modest deltas
- **Class B** — sub-$30 narrow-strike debit spreads
- **Class C** — $1-wide credit spreads
- **Class D** — narrow-wing iron condors (post-α; `strategy_selector`'s `iv_rank` gate no longer holds them back)
- **Class E** — excluded (CSP/CC capital reservation exceeds BP)

Binding constraint for Class B at micro: `edge_below_minimum` (downstream of H7). Full empirical work + 2-leg debit spread geometry mechanism + entry-premium-vs-width derivation at `docs/structural_findings.md`.

---

## Live State (auto-updated)
- **Phase:** micro_live (since 2026-04-25 17:10:36Z)
- **Promotion gate:** bypassed; continuous-growth model
- **Open positions:** 0
- **Alpaca live equity:** ~$681 (micro tier)
- **Alpaca options BP:** $501.61 (ACH settled, as of 2026-05-10)
- **Universe:** 70 symbols (post-Phase-3 α coverage; 67 at full iv_rank decidability)
- **Last updated:** 2026-05-18
