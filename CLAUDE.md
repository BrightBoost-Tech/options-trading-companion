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
- Daily-scoring path (`policy_daily_scores`) is **functional as of
  2026-04-26 06:19Z**: PR #807 fixed the ImportError that prevented the
  endpoint from running, PR #808 fixed the schema drift that prevented
  writes. First successful canary at 2026-04-26 06:19Z populated
  `policy_daily_scores` with 3 rows. Awaiting Monday 2026-04-27 16:30 CT
  scheduler fire as final end-to-end verification.
- Legacy `policy_lab_daily_results` table has zero writers and zero
  consumers post-PR-#808; cleanup tracked as backlog #73.
- `check_promotion` runs daily; promotion eligibility resumes once
  `policy_daily_scores` accumulates a meaningful window of cohort data.

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
- [x] Close-path consolidation: 5 violators → single `close_helper.close_position_shared`,
      Phase 1 enum expand (PR #796, 2026-04-23) + Phase 2 enum contract (PR #802)
- [x] `_estimate_equity` / `_compute_weekly_pnl` consolidation: canonical
      `services/equity_state.py` module + shim delegations from
      `intraday_risk_monitor`, `paper_mark_to_market`, `paper_autopilot_service`.
      PR #780 (2026-04-19) extracted to `services/equity_state.py` + migrated
      `intraday_risk_monitor`. PR #795 (2026-04-22) migrated `paper_mark_to_market`
      and `paper_autopilot_service`. Zero false `loss_weekly` events since
      83872db patch on 2026-04-16. Tests in `test_equity_state_*.py` defend
      the invariant.
- [x] Micro-live promotion ($500 cap, Alpaca live) — operator-initiated 2026-04-25
- [x] Policy lab eval ImportError fix (PR #807, 2026-04-25)
- [x] Policy lab eval schema-drift fix + per-cohort observability (PR #808, 2026-04-26 06:15Z)
- [x] #62a-D2 nested_regimes write-only orphan deleted (2026-04-26) — 0 rows ever, 0 readers; deleted `log_global_context` rather than fix; table drop tracked as #75

### Prioritized Roadmap (post-2026-04-26)

Bucketing criteria, in order: SAFETY (live trades / P&L / execution) →
OBSERVABILITY (surfaces other bugs faster) → CORRECTNESS → CLEANUP.

**Priority 1 — Do This Week**

#62a audit complete (2026-04-26). Two small high-value drift fixes
slot in here alongside the Monday verification:

- [ ] **#65 final verification** (Monday 2026-04-27 16:30 CT scheduler
      fire — passive observation only, ~5 min check). Expected: 3
      rows with `trade_date=2026-04-27` in `policy_daily_scores`
      within 10 minutes of fire time, no
      `policy_lab_eval_cohort_failure` alerts. Final acceptance
      criterion for #65 closure.
- [ ] **#62a-D4-PR1 — `routing_mode` column migration** (PR open;
      awaits operator-approved manual apply per the migration
      procedure). Migration file
      `supabase/migrations/20260426000000_add_routing_mode_to_paper_portfolios.sql`.
      Data-only; backfills Conservative + Neutral cohort portfolios
      → `shadow_only`; everything else defaults to `live_eligible`.

**Priority 2 — This Month**
- [ ] **#72 Loud-error doctrine audit** — establish doctrine + first
      wave. Informs review criteria for #71/#68/#69.
- [ ] **#71 RQ dispatch audit** — sweep `public_tasks.py` /
      `internal_tasks.py` for synchronous handlers; migrate to
      `enqueue_job_run` pattern.
- [ ] **Agent sessions observability** — shared `agent_session_context`
      helper so Loss Min / Self-Learning / Profit Optimization write rows.
- [ ] **#62a-D1 — `is_champion` column missing** (LATENT-HIGH).
      Prerequisite: resolve `'neutral'` vs `'aggressive'` intent
      disagreement between migration and code. See #62a-D1 below.
- [ ] **#62a-D3 — `regime_snapshots` table missing.** Decision needed:
      apply migration vs delete writes. See #62a-D3 below.
- [ ] **#62a-D5 — `execution_cost_*` silently dropped.** Decision
      needed: are signals load-bearing? See #62a-D5 below.
- [ ] **#62a-D4-PR2 — routing dispatch enforcement** (~1 day, MEDIUM
      risk). Broker dispatch checks `portfolio.routing_mode`;
      `_simulate_fill` path for `shadow_only`. Tests assert
      shadow_only portfolios never reach Alpaca regardless of
      `EXECUTION_MODE`. Sequenced after PR1.
- [ ] **#62a-D4-PR3 — symbol drop fix** (~5 min code + 30 min verify).
      Original one-line drop. Sequenced last; LOW risk after PR1+PR2.
- [ ] **#68 Polygon Tier 2 — `universe_service` Alpaca migration**
      (eliminates Saturday 2026-04-25 429 root cause).
- [ ] **#69 Polygon Tier 2 — `market_data.py` base-layer Alpaca
      migration** (foundational; unlocks downstream cutovers).

**Priority 3 — Next Quarter**
- [ ] **GAP 1** — Canonical ranking metric (PnL ÷ marginal risk,
      correlation-adjusted). Hold until P2 observability ships.
- [ ] **GAP 2** — EV-aware exit ranking. Depends on GAP 1.
- [ ] **GAP 3** — Calibration deepening (segment by strategy / regime /
      DTE / liquidity). Gated on ≥30d micro_live data.
- [ ] **GAP 4** — Autotune walk-forward replacement. After GAP 3.
- [ ] **#62 — Migration drift reconciliation** (329 cols + 12 tables).
      Multi-PR effort, sequenced from #62a catalog.
- [ ] **#62a-D6 — `model_governance_states` table missing.** Apply
      table-creation portion of `20251215000000_learned_nesting_v3.sql`,
      OR delete writes if v3 is dormant.
- [ ] **#62a-D7 — `shadow_cohort_daily` table missing.** Consumer
      feature is permanently off; recommend remove writer rather
      than apply migration.
- [ ] **#62a-D8 — `trade_executions` 8 wrong columns.** Investigation
      first: is `register_execution` still on any active path?
- [ ] **#73 — Remove dead `GET /policy-lab/results` endpoint and
      `policy_lab_daily_results` table.** Gated on #65 fully closed.
- [ ] **#66 Polygon Tier 1 — dead-code deletion** (`polygon_client.py`,
      `_get_option_snapshot_api`). Wait until #69 lands so callers gone.
- [ ] **Dead-code sweep:** v4 accounting ledger, outcomes_log chain,
      strategy_backtest v3 endpoints, adaptive-caps stack
      (`RiskEngine.get_active_policy`, `apply_adaptive_caps`).
- [ ] **Drop-unused-tables migration:** `outcomes_log`,
      `risk_budget_policies`, `risk_state`, `signal_weight_history`,
      `strategy_adjustments`, v4 accounting ledger,
      `strategy_backtest_folds/trades/events`.

**Priority 4 — Deferred (no plan to do)**
- [ ] **#70 Polygon Tier 3** (HARD_TO_REPLACE Supabase-cache strategy).
      Acceptable residual; only revisit if Polygon billing changes.
- [ ] **Replay subsystem evaluation** — gated on micro_live stable for
      30+ days. Wire up or remove.
- [ ] **GHA `trading_tasks.yml` cleanup** (~1000 LOC unreachable
      schedule blocks). APScheduler is primary; pure hygiene.
- [ ] **#62a-D9 — `trade_suggestions` rebalance flow extra cols.**
      Cleanup batch (verify cold then fix or remove endpoint).
- [ ] **#62a-D11 — `symbol_regime_snapshots`** — note only, no active
      writer.
- [ ] **#62a-D12 — Out-of-band tables** — acknowledge, do not rebuild
      migration history.
- [ ] **Full live automation** — final, after GAPs 1-4.

### Notable findings 2026-04-26 (Sunday)

#67 was queued as Priority 1 SAFETY work based on Saturday's
Diagnostic B premise that `outcome_aggregator` was corrupting the
calibration loop. Sunday's pre-fix diagnostic showed the premise
was wrong:

- `outcome_aggregator.py` has never run in production.
- `outcomes_log` table is empty for all time (zero rows ever).
- Calibration reads `learning_feedback_loops`, not `outcomes_log`.
- Six test files were already marked dead (Cluster I, PR #9 / #770).

The error in Saturday's analysis was inferring the consumption chain
from code structure rather than verifying through DB state and a
caller search. Pattern lesson: when claiming a path is "live and
hot," verify with `COUNT(*)` on the destination table and grep for
scheduler bindings.

Outcome: #67 demoted to dead-code cleanup. The Priority 1 SAFETY
slot is filled by `_estimate_equity` / `_compute_weekly_pnl`
consolidation plus the #62a schema drift audit kickoff — **not** by
close-path consolidation, which was already completed by PR #796 +
PR #802 and lives in the Completed list. #62a was elevated to
Priority 2 (with kickoff in Priority 1) due to a third confirmed
instance of the schema-drift pattern in one week.

**Pattern check applied 2026-04-26:** even immediately after
documenting this lesson, the operator's first revision of the
backlog update attempted to re-add close-path consolidation to
Priority 1 (which was completed by PR #796 / PR #802) and reference
a "Sequence" section that exists only in chat history, not in
CLAUDE.md. Both errors caught pre-apply via verification against
current file state. The lesson generalizes: verify the file state
before making edits to it, not just the consumption chain before
claiming behavior.

### Backlog/PR closure discipline gap (2026-04-26)

Two Priority 1 items in two consecutive sessions were found to be
already completed by earlier PRs:

- **Close-path consolidation:** completed by PR #796 + PR #802, but
  item remained in Priority 1 until 2026-04-26 backlog correction.
- **`_estimate_equity` / `_compute_weekly_pnl` consolidation:**
  completed by PR #780 (2026-04-19) + PR #795 (2026-04-22), but item
  remained in Priority 1 until 2026-04-26 (this session).

Root cause: the backlog tracked deferral commitments but PRs
fulfilling them did not close those entries back into CLAUDE.md.
Result: operator energy spent investigating what's already done.

Process fix: every PR that fulfills a backlog item should include a
CLAUDE.md edit marking the item DONE in the same PR. The PR
description should reference the specific backlog line being closed.
Future backlog audits should expect Priority 1 items to be small and
active, not commitment shadows from weeks-old commits.

Pattern check: the diagnostic discipline lessons documented today
("verify consumption chain before claiming behavior" + "verify file
state before editing it") apply equally to backlog state. Verify
backlog-tracked work is actually outstanding before scheduling work
against it.

### #62a-D4 fix scope correction (2026-04-26)

Audit catalog flagged D4 as a 1-hour fix (one-line drop). Diagnostic
revealed a routing safety question that wasn't visible from static
analysis. Fix scope correctly expanded from 1 PR to 3 PRs after
understanding the architectural intent (shadow cohorts are
paper-only learning channels, must be enforced regardless of
`EXECUTION_MODE`).

Pattern: audit catalogs surface candidate symptoms. Architectural
intent (the "why") often determines the right fix shape, and intent
isn't always visible from code alone — sometimes requires operator
clarification.

This is the 5th time this weekend that diagnostic-first discipline
caught something audit-surface analysis missed. The discipline is
robust enough to formalize as protocol: every backlog fix begins
with diagnosis, then design conversation, then implementation.

---

## Working Style

- Respond with exact SQL, exact Railway commands, exact file paths — no placeholders
- When fixing bugs: show the broken code, explain why it's wrong, show the fix
- When adding features: check GAP priority order before building new things
- Prefer minimal diffs over full rewrites
- Always check `job_runs` table before assuming a cron ran successfully

## Backlog (post-promotion)

**#65 — Revive `policy_lab_eval`** (HIGH) — **CLOSED 2026-04-26**
Resolved by PR #807 (ImportError fix) + PR #808 (schema-drift fix +
per-cohort observability), merged 2026-04-26 06:15:54Z. First
successful canary populated `policy_daily_scores` with 3 rows at
2026-04-26 06:19Z. Final end-to-end verification pending Monday
2026-04-27 16:30 CT scheduler fire.

**#66 — Polygon Tier 1: dead-code deletion** (LOW)
Remove `packages/quantum/polygon_client.py` (zero non-test callers) and
`market_data.py:_get_option_snapshot_api` (deprecated). Single PR, no
functional change.

**#67 — outcome_aggregator dead-code removal** (LOW)

CORRECTED 2026-04-26: `outcome_aggregator.py` is dead code. Verified:
- `outcomes_log` table empty for all time (zero rows ever).
- No scheduler entry, no GHA workflow, no FastAPI endpoint.
- Only caller is CLI script `scripts/update_outcomes.py` (never run
  in production).
- `calibration_service` reads `learning_feedback_loops`, NOT
  `outcomes_log`.
- 6 test files already marked `@pytest.mark.skip` with reference to
  Cluster I deletion (PR #9 / issue #770).

Saturday 2026-04-25's Diagnostic B premise that this corrupts the
calibration loop was wrong. Hardening was unnecessary.

Action: fold into the dead-code removal sweep already in Priority 3
("Dead-code sweep: v4 accounting ledger, outcomes_log chain, ...").

Cleanup scope:
- Delete `packages/quantum/services/outcome_aggregator.py`
- Delete `packages/quantum/scripts/update_outcomes.py`
- Delete `log_outcome()` from `packages/quantum/nested_logging.py`
- Update `system_health_service.py:95` and `capability_service.py:34`
  to use `learning_feedback_loops` or remove the checks
- Drop `outcomes_log` table via migration (already in Priority 3
  drop-unused-tables list)
- Delete the 6 already-skipped test files

Keep priority LOW. This is hygiene, not safety.

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

**#71 — RQ dispatch migration for synchronous task endpoints** (MEDIUM)
Audit `packages/quantum/public_tasks.py` and `internal_tasks.py` for
handlers that run work synchronously instead of dispatching to RQ.
Pattern surfaced from `policy_lab_eval` diagnostic 2026-04-26: the
endpoint ran synchronously, didn't `enqueue_job_run`, produced no
observability trace. Migrate affected handlers to the `enqueue_job_run`
pattern matching reliable peers. Effort: medium (audit + 1 PR per
affected endpoint). Source: 2026-04-26 morning diagnostic.

**#72 — Loud-error doctrine audit** (MEDIUM)
Catalog all error-handling that swallows exceptions without writing
`risk_alerts`. Establish doctrine: every production exception must
produce a `risk_alert` at minimum severity=info OR fail loudly to the
caller. Multi-PR effort — sequenced as doctrine first, then waves of
fixes. Source patterns identified 2026-04-26:
- `ALPACA_PAPER` vs `ALPACA_PAPER_TRADE` env mismatch (Saturday)
- Polygon `@guardrail` decorator returns empty values silently
- `policy_lab_eval` ImportError + scheduler-logs-warning-then-continues
- per-cohort exception swallow at `evaluator.py:151-153`

**#73 — Remove dead `GET /policy-lab/results` endpoint and table** (LOW)
After PR #808 (closes #65), `policy_lab_daily_results` has zero
writers. Reader at `policy_lab/endpoints.py:42-75` has zero frontend
callers (verified in `apps/web/`). Delete the route, drop the table
via migration, scrub references in CLAUDE.md. Gated on #65 fully
closed (Monday 2026-04-27 verification). Effort: ~1 hour.

**#75 — Drop `nested_regimes` table (orphan after #62a-D2)** (LOW)

Source: #62a-D2 fix on 2026-04-26 deleted `log_global_context`, the
only writer to `nested_regimes`. Table now has zero writers and
zero readers (verified during D2 diagnostic — no Python code reads
the table; no scheduler entry; no FastAPI route).

Cleanup scope:
- Migration to `DROP TABLE nested_regimes`.
- Remove the original creation migration if appropriate (or keep
  as a historical artifact).

Effort: ~30 min, single PR. Bundle with the existing "drop unused
tables" Priority 3 batch.

Priority: LOW — orphan table costs nothing, just noise.

**#74 — Remove `RISK_EQUITY_SOURCE=legacy` rip-cord from `equity_state.py`** (LOW)

Source: 83872db (2026-04-16) committed *"Kept 72h for safety;
scheduled for removal in a follow-up PR."* Now 10 days stable.

Cleanup scope:
- Remove `_estimate_equity_legacy` and `_compute_weekly_pnl_legacy`
  from `equity_state.py`.
- Remove `RISK_EQUITY_SOURCE` env-based switching logic.
- Update `.github/workflows/ci-tests.yml:24` (currently sets
  `RISK_EQUITY_SOURCE=legacy`).
- Prune legacy-branch tests in `test_equity_state_helpers.py`.

Effort: ~1-2 hours, single PR, no functional change in production
(rip-cord is unset in Railway env, defaults to `alpaca`).

### #62a — Schema drift audit COMPLETE 2026-04-26

Audit catalog: **12 drift instances** found across 70 tables, ~1,100
columns, ~60 production write sites, 85 migrations.

The initial Saturday/Sunday findings (3 instances — PR #6 enum, #65
`policy_lab_daily_results`, `outcomes_log` cols) captured a fraction
of actual drift. The audit revealed 9 additional instances including
1 latent live-trade-routing issue and 4 broken data-collection paths
(regime persistence dead, cohort fan-out broken, execution-cost
gating dropped silently, regime_snapshots table missing).

Method limitations documented (8 false-negative classes — see
"#62a audit method limitations" below). Confidence: **HIGH on 10
actionable findings, MEDIUM on completeness.**

Catalog summary:
- **1 CRITICAL** in audit (verified DOWNGRADED to HIGH-LATENT
  after deep-dive — see #62a-D1).
- **4 HIGH** (cohort fan-out broken, regime persistence dead,
  execution-cost gating silently dropped, regime_snapshots table
  missing).
- **3 MEDIUM** (governance state, shadow_cohort_daily, legacy
  execution_service).
- **4 LOW** (rebalance flow, outcomes_log dead-code,
  symbol_regime_snapshots, OOB tables).

Status: AUDIT COMPLETE. Catalog forms the work plan for #62 proper.
Sub-items #62a-D1 through #62a-D12 below.

#### #62a-D1 — `is_champion` column missing (LATENT, HIGH)

Verified 2026-04-26: column missing from `policy_lab_cohorts`, but
autopilot has produced zero orders in 8+ days, and live routing
goes through `fork.py:67` cohort_name tag path — not through
`_get_champion_portfolio`. Not Monday-blocking.

Compounding issue: migration `20260402000000_small_account_cohorts.sql`
intends `'neutral'` as champion; live code (`fork.py:67`) hardcodes
`'aggressive'`. The two designs disagree.

**Prerequisite before fix:** resolve `'neutral'` vs `'aggressive'`
intent disagreement.

Fix scope after intent resolution:
- `ALTER TABLE policy_lab_cohorts ADD COLUMN is_champion boolean DEFAULT false`
- `UPDATE` to set `is_champion=true` on the resolved cohort.
- Decide whether `_get_champion_portfolio` should actually be
  reachable, or be deleted (the live routing stays in fork.py's
  tag-based path).
- Optional: clean up 3 orphan $500 "Main Paper" portfolios from
  2026-04-02.

Effort: ~2-4 hours after intent resolution.

#### #62a-D2 — `nested_regimes` writer deleted (CLOSED 2026-04-26)

Originally classified as HOT-HIGH "rename keys in writer". Diagnostic
revealed three layered failures: wrong column names, missing required
`timestamp` field, silent try/except. Plus zero readers anywhere
(no code, no scheduler, no FastAPI route) and zero rows ever written.

Resolution: **deleted `log_global_context`** rather than fix —
empty-table writes don't fit the loud-error doctrine emerging from
#62a/#67. Also removed dead `_get_supabase_client` helper, dead
`supabase` import in `backbone.py`, dead import in `optimizer.py`,
and three unused test mocks. Table-level cleanup tracked as #75.

#### #62a-D3 — `regime_snapshots` table missing (HOT, HIGH)

Files: `api.py:627`, `workflow_orchestrator.py:1130`, `:1951`.
Migration `20251213000000_regime_snapshots.sql` exists but never
applied. Daily morning + midday cycles attempt persistence and
fail silently.

Fix: apply migration, OR delete the writes (decide if snapshot is
needed for backtest/replay).

Effort: ~1 day if applying migration, ~1 hour if deleting writes.

#### #62a-D4 — Cohort fan-out routing safety + symbol drop fix

Status: HIGH — multi-PR architectural work, **NOT one-line fix.**

Original audit finding: clone path writes `symbol` key to
`trade_suggestions` but column is `ticker`. Single-key drop appears
trivial.

Verification finding 2026-04-26: applying the drop in current
`micro_live` mode could route conservative/neutral cohort orders to
the live broker, violating the design intent that shadow cohorts
are paper-only learning channels (operator clarification 2026-04-26:
fan-out is meant to amplify *learning* per trade — one cohort
trades real capital, others produce shadow observations that must
NEVER reach the live broker).

Current implementation conflates routing: `EXECUTION_MODE` is
global; no portfolio-level safety. Restoring shadow data flow
without routing enforcement is unsafe.

**Required sequence (3 PRs):**

**PR 1 — Add `routing_mode` column to `paper_portfolios`**
- Migration: `ALTER TABLE paper_portfolios ADD COLUMN routing_mode
  text NOT NULL DEFAULT 'live_eligible'
  CHECK (routing_mode IN ('live_eligible', 'shadow_only'))`
- UPDATE existing cohort portfolios:
  - Conservative Cohort, Neutral Cohort → `'shadow_only'`
  - Aggressive Cohort → `'live_eligible'` (current champion path)
  - Main Paper → `'live_eligible'`
- Effort: ~30 min.
- Risk: LOW (data-only change, no code change yet).

**PR 2 — Routing dispatch enforcement**
- Modify broker dispatch to check `portfolio.routing_mode` before
  live submission.
- Implement `_simulate_fill` for shadow_only portfolios (decide
  between mid-price simulation, mirror-champion, or paper_mtm
  reuse).
- Tests: assert shadow_only portfolios never reach Alpaca
  regardless of `EXECUTION_MODE`.
- Effort: ~1 day.
- Risk: MEDIUM (architectural change, needs careful testing).

**PR 3 — Apply original #62a-D4 single-line symbol fix**
- Drop `"symbol": source.get("symbol")` from clone dict at
  `packages/quantum/policy_lab/fork.py:229`.
- Verification: shadow trades start appearing in `trade_suggestions`;
  `paper_orders` for shadow_only portfolios show simulated fills.
- Effort: 5 min code + 30 min verification.
- Risk: LOW after PRs 1 and 2 land.

Total effort: **~2 days across 3 PRs.**

Architectural principle: each portfolio's intent (live-capable vs
shadow-only) becomes explicit data, not implicit code-path
knowledge. Safe by default — new portfolios default to
`live_eligible`; shadow status must be intentionally set.

Verified production state (still true as of 2026-04-26):
**0 conservative/neutral shadow clones in 30 days** vs 58
aggressive. Shadow eval data collection has been broken at the
source for the entire month. The "189 cohort decisions" stat
referenced in CLAUDE.md cohort architecture section is from
`policy_decisions`, NOT actual shadow trades.

#### #62a-D5 — `execution_cost_*` columns silently dropped (HOT, HIGH)

File: `packages/quantum/services/workflow_orchestrator.py:468-478`.
3 columns (`execution_cost_soft_gate`, `execution_cost_soft_penalty`,
`execution_cost_ev_ratio`) dropped via `DROPPABLE_SUGGESTION_COLUMNS`
retry shim on every suggestion write. Verified absent from
`trade_suggestions` schema.

**Decision needed:** are these signals load-bearing for execution
gates? If yes, add columns via migration. If no, remove the
computation and the shim entirely.

Effort: ~2 hours after decision.

#### #62a-D6 — `model_governance_states` table missing (MEDIUM)

Migration `20251215000000_learned_nesting_v3.sql` partially applied
— ALTER statements landed but `CREATE TABLE model_governance_states`
did not. Learned Nesting v3 governance writes fail silently.

Fix: apply table-creation portion, OR delete the writes if Learned
Nesting v3 is dormant.

Effort: ~1 day.

#### #62a-D7 — `shadow_cohort_daily` table missing (MEDIUM)

File: `packages/quantum/public_tasks.py:1861`. Migration
`20260122100000_shadow_cohort_daily.sql` not applied. Autopromote
v4-L1E feature broken silently. Note: `POLICY_LAB_AUTOPROMOTE=false`
permanently, so the consumer feature is off anyway.

Fix: apply migration OR remove writer (deletion is the lower-risk
choice given the consumer is off).

Effort: ~1 hour to remove writer, ~2 hours to apply + verify.

#### #62a-D8 — `trade_executions` 8 wrong columns (MEDIUM)

File: `packages/quantum/services/execution_service.py:215-254`.
Writes `mid_price_at_submission`, `order_json`, `trace_id`,
`window`, `strategy`, `model_version`, `features_hash`, `regime`
— none in legacy `trade_executions` schema. Canonical execution
path is `paper_orders` + `position_legs`.

**Prerequisite:** trace whether `register_execution` is on any
active path. If dead → delete the legacy `ExecutionService`. If
alive → drop-cols-or-add-cols decision.

Effort: ~half day investigation + ~1-2 hours fix.

#### #62a-D9 — `trade_suggestions` rebalance flow extra cols (LOW)

File: `packages/quantum/api.py:869-885,898`. Writes `symbol`,
`confidence_score`, `notes` — none in schema. Rebalance flow likely
unused; insert 400s if exercised.

Effort: ~1 hour (verify cold, then either fix or remove endpoint).

#### #62a-D10 — `outcomes_log` 5 cols (LOW) — TRACKED UNDER #67

5 cols (`status`, `reason_codes`, `counterfactual_pl_1d`,
`counterfactual_available`, `counterfactual_reason`) absent. Already
folded into the dead-code sweep via backlog #67.

#### #62a-D11 — `symbol_regime_snapshots` table missing (LOW)

Created by migration `20251213000000_regime_snapshots.sql` (same as
D3) but no active write site found in code. Note only — no fix
needed unless a writer is reintroduced.

#### #62a-D12 — Out-of-band tables (LOW) — ACKNOWLEDGE, NO ACTION

7 tables exist in prod with no creator migration: `audit_logs`,
`profiles`, `portfolios`, `option_positions`, `weekly_trade_reports`,
`user_settings`, `plaid_items`. Pre-migration-tracking artifacts.
Don't rebuild migration history; just acknowledge.

### #62a audit method limitations

The audit catches static patterns: dict-literal upserts,
enum-constraint writes, migration-vs-prod schema diff. It does
NOT catch:

1. `**kwargs` / variadic dict expansion in writes.
2. Dicts built across functions (9 sites flagged opaque).
3. `SELECT *` reads on schema-drifted tables.
4. JSONB metadata field shape conventions.
5. Joins / RLS / FK referencing dropped columns.
6. Views drifting from base tables.
7. Migrations rolled back via dashboard.
8. **Migration intent vs runtime code disagreement** (the
   `'neutral'` vs `'aggressive'` issue under D1 was caught only
   by manual review of the migration file, not by any automated
   step).

Confidence: HIGH on 10 actionable findings, MEDIUM on completeness.
Future drift is expected; this audit method catches the bulk but
not all.

---

## Live State (auto-updated)
- **Phase:** micro_live (since 2026-04-25 17:10:36Z)
- **Promotion gate:** bypassed; continuous-growth model
- **Open positions:** 0 (AMZN closed 2026-04-25 15:56Z, realized_pl +$325.50)
- **Alpaca live equity:** $500.00 (account 211900084)
- **Alpaca options BP:** $0.00 (ACH settlement pending)
- **Universe:** 62 symbols (refreshed 2026-04-25 17:17Z)
- **Last updated:** 2026-04-25
