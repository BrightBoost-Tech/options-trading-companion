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
  Polygon.io (fallback + reference data)

---

## Current Phase

- **Trading mode:** `micro_live` (EXECUTION_MODE env, flipped 2026-04-25 17:10:36Z)
- **Promotion type:** manual operator-initiated. Green-day gate (1/4) bypassed; continuous-growth model adopted. Audit `risk_alerts.id = 82f1c294-19a4-4c66-8a68-0b0811ef5b24`.
- **Account:** live Alpaca `211900084`, options Level 3
- **Starting capital:** $500 on `v3_go_live_state.paper_baseline_capital` (set 2026-04-25 15:38:04Z, audit `c9d87caf-24db-4f7f-842a-748620a5c84f`)
- **Open positions:** 0 (AMZN closed 2026-04-25 15:56:36Z with realized_pl +$325.50, audit `b6229d5e-1543-4304-9ab1-6f37e0e869c8`)
- **Settlement:** `options_buying_power = $0` as of 2026-04-25 (ACH settlement pending; expected to clear Mon–Tue)
- **Universe:** 62 symbols. PR #804 added F, BAC, SOFI, T, KO, VZ; sync triggered 2026-04-25 17:17Z (job_run `25eec261-d3e3-4b4a-aefe-2865770b001d`).
- **Pipeline status:** Full end-to-end pipeline validated 2026-04-10
- **daily_progression_eval:** Running at 16:00 CT. The alpaca_paper → micro_live promotion gate has been bypassed (operator-initiated promotion). Future phase transitions are a deferred decision under the continuous-growth model.
- **Iron condors:** DISABLED in current phase. Debit spreads only.
- **Calibration job:** Running daily at 05:00 CT; writes to `calibration_adjustments`.
- **Risk profile:** micro-tier — 8% base risk per trade × score/regime/compounding multipliers (see "Risk per trade math"). Effective per-trade risk typically 8–12% of capital.
- **Phase 2 contract:** enforced — `check_close_reason_enum` (9 values), `check_fill_source_enum`, `close_path_required` constraints intact

---

## Infrastructure

| Service | URL / Location |
|---|---|
| Backend (Railway) | https://be-production-48b1.up.railway.app |
| Frontend (Railway) | https://fe-production-d711.up.railway.app |
| Worker (Railway) | worker.railway.internal (internal) |
| Supabase project | etdlladeorfgdmsopzmz.supabase.co |
| GitHub Actions | Manual dispatch only (APScheduler is primary) |

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

1. Market Data (Alpaca primary for options + equities, Polygon fallback)
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
| Loss Minimization | Every 15 min during market hours | Intraday envelope monitoring + force-close | ❌ no |
| Self-Learning | 4:45 PM CT | Post-trade calibration + drift detection | ❌ no |
| Profit Optimization | apply_calibration during suggestions | Calibrated EV/PoP from learned adjustments | ❌ no |

**Gap:** Only Day Orchestrator writes to `agent_sessions`. The other three
run on schedule but produce no agent-session records. Planned: shared
`agent_session_context` helper; tracked for post-micro_live observability PR.

### Replay / forensic subsystem (gated off)

`data_blobs`, `decision_runs`, `decision_inputs`, `decision_features` exist
in code (`services/replay/`), gated off via `REPLAY_ENABLE=0`. Designed for
post-incident forensics. Not active. Evaluate after micro_live stabilizes —
either wire up or remove using the v4-accounting playbook.

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

## Migration Apply Procedure

Supabase migrations in this repo do NOT auto-apply on merge. The
deploy pipeline ships code only — schema changes require a human
operator to apply the SQL manually.

Discovered 2026-04-23 during PR #6 (#796) — the Phase 1 migration
merged with the code but was never applied to production. This gap
has existed for the entire life of the repo (84 of 85 prior
migrations were not tracked in `supabase_migrations.schema_migrations`
before 2026-04-23). Auto-apply wiring and drift reconciliation
(329 divergent columns + 12 missing tables vs migration history)
are planned as separate multi-PR efforts — see backlog #62. Until
then, follow the procedure below for every PR that touches
`supabase/migrations/*.sql`.

### Apply checklist

1. **Confirm merge.** PR includes `supabase/migrations/*.sql`. Note
   the merge commit SHA and timestamp (ISO 8601 UTC, from GitHub's
   `mergedAt` field).

2. **Re-inspect the SQL.** Open the migration file on the merged
   `main` branch. Read it end-to-end with fresh eyes. The
   `manual_endpoint` vs `manual_close_user_initiated` bug in PR #6
   Commit 1 survived both code review and a post-merge
   verification-distribution message because reviewers deferred
   to the artifact under review. At apply time, re-derive expected
   behavior from upstream sources (enum definitions in
   `close_helper.py`, the semantic contract) — not from the SQL
   under review.

3. **Apply via `mcp__supabase__apply_migration`** (canonical for
   this repo). Pass the SQL verbatim from the merged file. This
   tool both runs the DDL and records the migration in
   `supabase_migrations.schema_migrations`.

   Alternative: Supabase Dashboard SQL editor (paste + execute).
   Does NOT record in `schema_migrations`; avoid unless the MCP
   path is unavailable.

   If Dashboard is used (emergency / human-without-Claude), the
   operator MUST manually INSERT a corresponding row into
   `supabase_migrations.schema_migrations` after the DDL runs,
   matching the version and name convention. Otherwise the
   audit-trail gap that caused this procedure to exist reproduces.

   DO NOT use `supabase db push` as of 2026-04-23 — with 84
   un-tracked historical migrations on disk, it would attempt to
   re-apply all of them. Resolution tracked in backlog #62.

4. **Verify the apply took effect.** Query the DB for the specific
   constraints / columns the migration introduced. Example for an
   ADD CONSTRAINT migration:

   ```sql
   SELECT conname, pg_get_constraintdef(oid)
   FROM pg_constraint
   WHERE conrelid = '<table>'::regclass
     AND conname = '<new_constraint>';
   ```

5. **Capture deploy-relevant state.** If the migration introduces
   time-sensitive invariants (e.g. PR #6's 48h observation window
   needing `PR6_DEPLOY_TIMESTAMP`), set those env vars on the
   worker service via `mcp__railway-mcp-server__set-variables`
   with `skipDeploys: true`.

6. **Log the apply for audit trail.** Every manual apply from here
   forward becomes queryable:

   ```sql
   INSERT INTO risk_alerts (user_id, alert_type, severity,
                            message, metadata)
   VALUES (
     '<trading account owner UUID>',
     'migration_apply',
     'info',
     'Applied <migration_name>',
     jsonb_build_object(
       'migration_file', 'supabase/migrations/<filename>',
       'commit_sha',     '<merge commit SHA>',
       'applied_at',     NOW()::text,
       'applied_via',    'mcp__supabase__apply_migration',
       'operator',       '<one of: claude_mcp | human_dashboard | human_cli | automation>',
       'operator_note',  '<free-text: who, why, special circumstances>',
       'pr_number',      <PR number>
     )
   );
   ```

   `operator` values:
   - `claude_mcp` — Claude Code via `mcp__supabase__apply_migration`
   - `human_dashboard` — human via Supabase Dashboard SQL editor
   - `human_cli` — human via `supabase` CLI (viable only post-drift-reconciliation)
   - `automation` — future auto-apply mechanism (backlog #62)

7. **Query manual-apply history** (audit surface for future drift
   analysis):

   ```sql
   SELECT metadata->>'migration_file',
          metadata->>'applied_at',
          metadata->>'operator',
          metadata->>'pr_number'
   FROM risk_alerts
   WHERE alert_type = 'migration_apply'
   ORDER BY created_at DESC;
   ```

### When NOT to apply on merge

If the migration's PR description explicitly states observation-
window sequencing (e.g. "apply after Phase 1 verifies clean at
T+24h"), do NOT apply on merge. Follow the PR's gating exactly.

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
| `agent_sessions` | Managed Agent session observability (currently only Day Orchestrator writes) |

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
-- 2026-04-13 pnl-corruption cutoff — see Bugs Fixed)
SELECT COUNT(*), ROUND(AVG(pnl_realized),2)
FROM learning_feedback_loops
WHERE outcome_type='trade_closed'
  AND created_at >= '2026-04-13'
  AND created_at::date = CURRENT_DATE;

-- Agent sessions (only Day Orchestrator writes today)
SELECT agent_name, status, started_at, completed_at FROM agent_sessions
ORDER BY created_at DESC LIMIT 5;
```

---

## Cohort architecture (current state, 2026-04-25)

The system has three cohorts (conservative / neutral / aggressive) in
`policy_lab_cohorts` per user. **Original design:** champion/challenger
evaluation with `promoted_at` field selecting the live cohort.

**Actual implementation:**

- Live trade routing is **hardcoded to "aggressive"** at
  `packages/quantum/policy_lab/fork.py:67`. Source suggestions emerge
  from the orchestrator's `SmallAccountCompounder.rank_and_select` call
  at `packages/quantum/services/workflow_orchestrator.py:2049-2094` and
  are tagged `cohort_name = "aggressive"` regardless of `promoted_at`.
- Decision-logging path (`policy_decisions` table) is **live**: 189
  decisions in last 30 days across all 3 cohorts, 45 outcomes backfilled.
  Latest decision 2026-04-24 16:00Z.
- Daily-scoring path (`policy_lab_daily_results`, `policy_daily_scores`)
  is **silent**: both tables empty for 30+ days.
- `policy_lab_eval` scheduled job (16:30 CT daily, registered at
  `scheduler.py:55`) has fired **0 times in the last 7 days** while peer
  scheduled jobs ran 5 times each.
- `check_promotion` runs daily but returns `no_scores_data` due to empty
  score tables; **no promotions are possible** in current state.

**Sizing duality (documented intent, not bug):**

- **Layer 1 — live aggressive trades:** sized via `SmallAccountCompounder`
  (micro tier, 8% base × multipliers). See "Risk per trade math".
- **Layer 2 — shadow cohort clones (conservative + neutral portfolios):**
  sized via `cohort.policy_config.max_risk_pct_per_trade × risk_multiplier`
  in `fork.py:196-201`. These trades execute against separate
  `paper_portfolio_id`s for shadow comparison.

These are **intentionally separate** sizing layers. Layer 1 drives live
execution. Layer 2 drives shadow comparison data. Reconciliation deferred
until 30+ days of `policy_lab_daily_scores` accumulate to inform which
layer's math correlates with better outcomes.

**Roadmap:** backlog #65 covers reviving `policy_lab_eval`. Without
revival, the system runs single-strategy (aggressive only) with no
learning loop on cohort comparisons.

---

## Risk per trade math

Live trades are sized by
`SmallAccountCompounder.calculate_variable_sizing` at
`packages/quantum/services/analytics/small_account_compounder.py:62-115`.

```
final_risk_pct = base_risk_pct × score_mult × regime_mult × compounding_mult
risk_budget    = capital × final_risk_pct
```

**Components:**

- `base_risk_pct` from `CapitalTier`:
  - micro (cap < $1k) → **0.08 (8%)**
  - small ($1k–$5k) → 0.03
  - standard (≥ $5k) → 0.02
- `score_mult = clamp(0.8 + (score − 50)/50 × 0.4, 0.8, 1.2)`.
  Examples: score 50→0.80, 75→1.00, **85→1.08**, 100→1.20.
- `regime_mult`: 1.0 normal · 0.9 suppressed · 0.8 elevated · 0.5 shock.
- `compounding_mult`: 1.2 if `COMPOUNDING_MODE=true` AND tier ∈ {micro, small}
  AND score ≥ 80; else 1.0.

**Defensive cap:** when `COMPOUNDING_MODE=false` AND tier ∈ {micro, small},
`base_risk_pct` is overridden to **0.02 (2%)** regardless of tier default
(`small_account_compounder.py:76-77`).

**Worked example** at $500 + score 85 + normal regime + `COMPOUNDING_MODE=true`:

```
risk_pct    = 0.08 × 1.08 × 1.0 × 1.2 = 0.10368  (~10.4%)
risk_budget = $500 × 0.10368 ≈ $52 per trade
```

**The "1.08 risk_multiplier observed in logs" is the score multiplier
in `SmallAccountCompounder` for a candidate scoring 85, NOT the cohort
`risk_multiplier`** (1.08 / 1.0 / 1.2 in `policy_lab_cohorts.policy_config`,
which sizes shadow clones at `fork.py:196-201`, not live trades).

---

## Polygon dependency status (2026-04-25)

**Current state:**
- 63 production Polygon API calls across 23 files
- 11 services with direct Polygon dependency: `options_scanner`,
  `paper_mark_to_market_service`, `paper_endpoints`, `dashboard_endpoints`,
  `option_contract_resolver`, `outcome_aggregator`, `universe_service`,
  `earnings_calendar_service`, `iv_daily_refresh`, `event_engine`,
  `nested/backbone`.
- `MarketDataTruthLayer` provides Alpaca-first failover **for snapshot
  paths only**. Most heavy callers bypass it.
- **Failure mode: silent degradation.** The `@guardrail` decorator in
  `services/provider_guardrails.py` returns typed empty values
  (`None`, `{}`, `[]`) on Polygon errors. No `risk_alerts` written. No
  `job_run.error` populated. Saturday 2026-04-25's `update_metrics`
  429s left zero database trace.

**Phase-out plan (committed):**

**Tier 1 — within 2 weeks (safety-critical):**
- Delete dead code: `packages/quantum/polygon_client.py` (zero non-test
  callers) and `market_data.py:_get_option_snapshot_api` (deprecated).
- Harden `outcome_aggregator._calculate_execution_pnl`: replace the
  silent-`None` pattern with explicit `logger.error` + `risk_alerts`
  insert on bar-fetch failure. The current pattern silently corrupts
  realized-P&L attribution feeding the calibration loop.

**Tier 2 — within 6 weeks (high-frequency-failure paths):**
- Migrate `universe_service` to Alpaca for `get_historical_prices` and
  `get_iv_rank`. Eliminates the Saturday 429 root cause.
- Migrate `market_data.py` base layer (`get_historical_prices`,
  `get_recent_quote`, `get_option_chain_snapshot`) to Alpaca.
  Subsequent service migrations (paper_mtm, dashboard, options_scanner)
  flow from this base.

**Tier 3 — deferred indefinitely (acceptable residual):**
- `get_ticker_details` (sector, market_cap) — no Alpaca equivalent.
  Implement Supabase-cache pattern with weekly manual refresh.
- `get_last_financials_date` (earnings ±90d estimation) — no Alpaca
  equivalent. Same Supabase-cache pattern.
- `I:VIX` historical bars — no Alpaca equivalent for index symbols.
  Single symbol, low call volume; keep Polygon for this.
- Backtest paths (`historical_simulation`, `option_contract_resolver`
  backtest paths) — non-production; defer.

**Backlog tracking:** items #65–#70 below.

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

### Last 30 days (verbatim)

- `paper_learning_ingest` must be in cron — not just manual trigger
- OCC symbol format for Alpaca order submission
- Internal fills miscounted as Alpaca fills in green day logic (fixed + reset 2026-04-04)
- Polygon options data empty (plan lacks quotes) — Alpaca now primary for options (2026-04-08)
- MTM `_compute_position_value_from_snapshots` read `snap.get("bid")` instead of `snap.get("quote", {}).get("bid")` — fixed 2026-04-08
- 11 broker endpoints + 6 policy lab endpoints missing explicit `Depends(get_current_user)` — fixed 2026-04-09
- Deprecated `POST /tasks/iv/daily-refresh` stub accepting legacy X-Cron-Secret — removed 2026-04-09
- `calculate_portfolio_inputs()` was synchronous inside async optimizer endpoint — wrapped 2026-04-10
- Close orders missing `position_intent` — Alpaca inferred `buy_to_open` — fixed 2026-04-10
- Close orders on near-worthless spreads had negative `limit_price` — clamp to 0.01 (2026-04-10)
- `paper_exit_evaluate` 3 PM never fired — idempotency key collision with 8:15 AM (2026-04-10)
- Debit spread PoP used raw long-leg delta instead of breakeven-adjusted — fixed 2026-04-12
- Intraday risk monitor only checked portfolio-level envelopes, not per-position stops — fixed 2026-04-12
- Intraday stop_loss=True was gated behind `RISK_ENVELOPE_ENFORCE` — decoupled 2026-04-13
- `paper_auto_execute` had no symbol-level dedup (3-AMD bug) — fixed 2026-04-13
- `_close_position` multi-leg inversion read `leg.get("side")` but stored legs use `action` — fixed 2026-04-13
- Close orders rejected with `held_for_orders` — pre-cancel + idempotency guard (2026-04-15)
- Alpaca close orders filled but paper_positions never marked closed — `_close_position_on_fill` (2026-04-15)
- Calibration DTE_BUCKETS misaligned with post_trade_learning buckets — aligned 2026-04-16
- `compute_risk_adjusted_ev` called with empty `existing_positions` (3-AMD entry bug) — fixed 2026-04-16
- Sector concentration check used raw SIC strings — canonical GICS mapping 2026-04-16
- `ttl_snapshot` hardcoded at 10s — env-configurable via `SNAPSHOT_CACHE_TTL` (2026-04-16)
- `apply_calibration` multiplied PoP without output clamp — clamped to [0,1] 2026-04-16
- `loss_weekly` severity=warn at -190% — upgraded to force_close 2026-04-16
- `PROFIT_AGENT_RANKING` was a dead kill switch — retired 2026-04-16
- **2026-04-16 ghost-position incident:** 3 close orders filled on Alpaca but
  stuck in `needs_manual_review` due to retry loop treating Alpaca code
  42210000 "position intent mismatch" as retriable. Fixes: (a) `poll_pending_
  orders` now includes `needs_manual_review` in status filter when
  `alpaca_order_id` is set; (b) `submit_and_track` breaks on 42210000 — no
  duplicate retries; (c) new `ghost_position_sweep` gated on
  `RECONCILE_POSITIONS_ENABLED` for 48h observation (PR #764).
- **2026-04-16 weekly_pnl math:** `_compute_weekly_pnl` summed per-position
  EOD marks (not P&L deltas) including closed positions — produced -190%
  weekly on a real week-to-date of ~-1%. Fix: Alpaca-authoritative
  `get_account()` + `get_portfolio_history(1W/1D)` with per-user cache;
  caller skips envelope on None rather than fabricating equity (commit 83872db).
- **2026-04-16 calibration pnl_realized corruption:** 34 outlier rows from
  internal-paper era and early Alpaca-paper era (before 2026-04-13) produced
  cumulative +$95K P&L in learning_feedback_loops vs Alpaca lifetime -$3K.
  Fix: hard date floor (`CORRUPTED_PNL_FLOOR`) in calibration_service filters
  pre-2026-04-13 rows out of the fetch. Query-time only; source preserved.

### Historical bugs (pre-2026-04-01, summarized)

Approximately 20 fixes before the current 30-day window covered:
- Scheduler heartbeat + never-run alert escalation
- Calibration DTE-bucket segmentation
- Risk-envelope circuit breaker (auto-execute blocks on breach)
- Multi-strategy scan caching reuse
- Debit spread stop-loss widening 20% → 50%
- Directional bid/ask pricing on spread legs (sell@bid, buy@ask)
- Option chain cache TTL 300s (env-configurable)
- Alpaca retry: 10 retries, exponential backoff, 90s watchdog, needs_manual_review fallback

Full chronology lives in git history; search commits from 2026-03 and earlier.

---

## Roadmap Status

### Completed
- [x] 10-day paper test
- [x] Policy Lab (3 cohorts)
- [x] Alpaca paper execution
- [x] Parallel reads via asyncio.gather() in suggestion pipeline
- [x] Promotion check job
- [x] Risk envelope wired into pre-entry and MTM
- [x] Multi-strategy scan caching
- [x] Scheduler heartbeat + never-run escalation
- [x] Calibration DTE-bucket segmentation
- [x] Risk envelope circuit breaker
- [x] Alpaca primary for options data (2026-04-08)
- [x] Security: explicit auth on all 17 broker + policy lab endpoints (2026-04-09)
- [x] Loss Minimization Agent (2026-04-09)
- [x] Self-Learning Agent (2026-04-10)
- [x] Profit Optimization Agent (2026-04-10)
- [x] Day Orchestrator Agent (2026-04-10)
- [x] Efficiency: async optimizer, V4 quality cache, condor EV memoization (2026-04-10)
- [x] Alpaca primary for equity data (2026-04-10)
- [x] Time-scaled profit targets (50% early → 25% late, 2026-04-11)
- [x] Sector field wired for envelope concentration checks (2026-04-11)
- [x] Raw EV stored alongside calibrated EV (2026-04-11)
- [x] Auto-retry failed_retryable jobs during market hours (2026-04-11)
- [x] PoP fix: breakeven-adjusted delta (2026-04-12)
- [x] Intraday stop losses (2026-04-12)
- [x] Cohort decision accuracy (2026-04-12)
- [x] Baseline capital synced to Alpaca at micro_live (2026-04-12)
- [x] MTM batch updates (2026-04-12)
- [x] Intraday stop-loss decoupled from RISK_ENVELOPE_ENFORCE (2026-04-13)
- [x] Symbol-level dedup in paper_auto_execute (2026-04-13)
- [x] Pre-cancel conflicting Alpaca orders + idempotency (2026-04-13)
- [x] Risk envelope force-close mode (`RISK_ENVELOPE_ENFORCE=1`, 2026-04-16)
- [x] Ghost-position rescue + reconcile sweep (PR #764, 2026-04-16)
- [x] Alpaca-authoritative weekly P&L math (83872db, 2026-04-16)
- [x] CI workflow with pytest + coverage (PR #1, 2026-04-17)

### In flight / up next
- [x] PR #1 (#765): CI workflow — merged 2026-04-17 as `f884077`
- [x] PR #776: NEVER DO skip-discipline rule — merged 2026-04-17 as `355e565`
- [x] PR #777: calibration `pnl_realized` date-cutoff filter (P1) — merged 2026-04-17 as `230f0a1`
- [ ] PR #778: docs rewrite (this PR, in flight)
- [ ] P1 before micro_live: remove dead adaptive-caps stack (RiskEngine.get_active_policy,
      apply_adaptive_caps) — outcome_type='guardrail_policy' last written 2026-01-05
- [ ] P1 before micro_live: consolidate `_estimate_equity` / `_compute_weekly_pnl` into
      shared module (72h follow-up from 83872db)
- [ ] P1 before micro_live: close-path consolidation (3 violators + shared helper)
- [ ] Dead-code removal: v4 accounting ledger, outcomes_log chain,
      strategy_backtest v3 endpoints, polygon_client.py (pending PR)
- [ ] Migration to drop `outcomes_log`, `risk_budget_policies`, `risk_state`,
      `signal_weight_history`, `strategy_adjustments`, `v4 accounting ledger` tables,
      `strategy_backtest_folds/trades/events`
- [ ] Agent sessions observability (shared agent_session_context helper)
- [ ] GHA `trading_tasks.yml` unreachable schedule blocks cleanup (~1000 LOC removal)
- [ ] Micro-live test ($500 cap, separate portfolio)
- [ ] Evaluate Replay subsystem after micro_live is stable — wire up or remove
- [ ] GAP 3–4 after data accumulates
- [ ] Full live automation

---

## Working Style

- Respond with exact SQL, exact Railway commands, exact file paths — no placeholders
- When fixing bugs: show the broken code, explain why it's wrong, show the fix
- When adding features: check GAP priority order before building new things
- Prefer minimal diffs over full rewrites
- Always check `job_runs` table before assuming a cron ran successfully

## Backlog (post-promotion)

**#65 — Revive `policy_lab_eval`** (HIGH)
Diagnose why the scheduler-registered job hasn't fired in 7+ days
despite `scheduler.py:55` defining it. Restore daily scoring rollup to
populate `policy_lab_daily_results` and `policy_daily_scores`. Without
revival, champion/challenger learning is non-functional and
`check_promotion` returns `no_scores_data` indefinitely.

**#66 — Polygon Tier 1: dead-code deletion** (LOW)
Remove `packages/quantum/polygon_client.py` (zero non-test callers) and
`market_data.py:_get_option_snapshot_api` (deprecated). Single PR, no
functional change.

**#67 — Polygon Tier 1: outcome_aggregator hardening** (HIGH)
Replace silent-`None` pattern in `_calculate_execution_pnl` with
loud-error logging + `risk_alerts` insert. Currently corrupts the
calibration loop invisibly when Polygon bar fetches fail.

**#68 — Polygon Tier 2: universe_service migration** (MEDIUM)
Replace `get_historical_prices` and `get_iv_rank` with Alpaca
equivalents. Eliminates the 429 root cause from Saturday 2026-04-25.

**#69 — Polygon Tier 2: market_data.py base-layer migration** (MEDIUM)
Foundational PR for stock bars and quotes via Alpaca. Enables
downstream service migrations (paper_mtm, dashboard, options_scanner).

**#70 — Polygon Tier 3: HARD_TO_REPLACE strategy** (LOW)
Implement Supabase-cache pattern for `get_ticker_details` and
`get_last_financials_date`. Document `I:VIX` as accepted residual
Polygon dependency. Defer until #66–#69 complete.

---

## Live State (auto-updated)
- **Phase:** micro_live (since 2026-04-25 17:10:36Z)
- **Promotion gate:** bypassed; continuous-growth model
- **Open positions:** 0 (AMZN closed 2026-04-25 15:56Z, realized_pl +$325.50)
- **Alpaca live equity:** $500.00 (account 211900084)
- **Alpaca options BP:** $0.00 (ACH settlement pending)
- **Universe:** 62 symbols (refreshed 2026-04-25 17:17Z)
- **Last updated:** 2026-04-25
