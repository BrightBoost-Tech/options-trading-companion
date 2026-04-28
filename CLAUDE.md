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
- **Risk profile:** micro-tier — 90% per trade × regime_mult, one position at a time (see "Risk per trade math"). Hard cutoff at $1000 (standard tier behavior above). Operator spec 2026-04-27.
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

8. **Update backlog tracker.** After successful apply, search
   CLAUDE.md for the migration's backlog item by file name or
   item number. If found in any *Priority X* or *pending*
   section, move it to *Roadmap → Completed* (or *Bugs Fixed
   (last 30 days)* if the migration also resolves a runtime bug)
   with the apply date and audit reference (`risk_alerts.id` or
   the `migration_apply` row's `applied_at`). If the apply and
   the backlog edit can't happen in the same operator turn, add
   the backlog edit to the next session's first action so it
   doesn't drift.

   The same step should be applied to *PR Merge Procedure* when
   one is formalized — merged PRs that resolve backlog items
   should close those items in CLAUDE.md within the same
   operator turn. This step exists because three closure-
   discipline gaps surfaced this weekend (see *Backlog hygiene
   check 2026-04-27 evening* in the Notable findings section)
   and the underlying pattern is documentation drift, not
   operator error.

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
  + `RiskBudgetEngine` (micro tier post-2026-04-27: 90% × regime_mult,
  one trade at a time). See "Risk per trade math".
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

Per-trade sizing is tier-aware. Single producer of `max_risk_per_trade`:
`RiskBudgetEngine.compute_budgets()`, mirroring
`SmallAccountCompounder.calculate_variable_sizing` for consistency.
The two layers are kept in sync — if you change one, change the other.

### Tier definitions

| Tier | Capital | Per-trade base | Multipliers | max_trades |
|---|---|---|---|---|
| micro | $0–$1000 | **90%** | regime only | **1 (one at a time)** |
| small | $1k–$5k | 3% | full stack (score × regime × compounding) | 4 |
| standard | $5k+ | 2% | full stack | 5 |

**Hard cutoff at $1000** — no smooth interpolation.

### Multiplier behavior

`regime_mult`: 1.0 normal · 0.9 suppressed · 0.8 elevated · 0.5 shock
· 1.0 chop · 1.0 rebound.

For **micro tier**: `final_risk_pct = 0.90 × regime_mult`. Score and
compounding multipliers are intentionally bypassed (operator spec
2026-04-27). `STRATEGY_TRACK` env value has no effect at micro tier —
the engine takes the tier-aware branch before the risk_profile switch.

For **small/standard tiers**: full stack:
`final_risk_pct = base_risk_pct × score_mult × regime_mult × compounding_mult`.

- `score_mult = clamp(0.8 + (score − 50)/50 × 0.4, 0.8, 1.2)`.
  Examples: score 50→0.80, 75→1.00, 85→1.08, 100→1.20.
- `compounding_mult`: 1.2 if `COMPOUNDING_MODE=true` AND tier=small
  AND score ≥ 80; else 1.0. (Standard tier never gets the boost.)

**Compounding-off safety override** (small tier only post-2026-04-27):
when `COMPOUNDING_MODE=false`, small-tier `base_risk_pct` is overridden
to **0.02 (2%)**. Micro tier ignores the compounding flag entirely.

### Worked examples ($500 capital, micro tier, NORMAL regime)

| Score | Regime | risk_budget |
|---:|---|---:|
| any | normal | $450 |
| any | suppressed | $405 |
| any | elevated | $360 |
| any | shock | $225 |

For $500 capital + score 85 + normal regime + `COMPOUNDING_MODE=true`:
`risk_pct = 0.90 × 1.0 = 0.90`, `risk_budget = $500 × 0.90 = $450`.

### Global allocation (micro tier)

`global_alloc.max = deployable_capital × 0.90 × regime_mult_for_micro`.
Mirrors per-trade for one-at-a-time tiers (one position consumes the
entire slot). Standard/small tiers retain
`global_alloc.max = total_equity × global_cap_pct` (regime-based 5–50%).

### Universe price filter (micro tier)

For micro-tier accounts, the scanner pre-filters the 62-symbol
universe at `options_scanner._apply_tier_price_filter` (called
immediately after the batch quote fetch, before per-symbol Polygon
option-chain calls) to drop symbols whose underlying price exceeds
$50 (configurable via `MICRO_TIER_MAX_UNDERLYING` env var).

The threshold aligns with existing scanner spread-width logic at
`options_scanner.py:~1084`: spreads default to 2.5-wide for sub-$50
underlyings and 5-wide above. Sub-threshold names produce
~$200-$250 max_loss/contract that fits the micro $450 budget;
above-threshold names produce ~$300-$500+ that often exceeds it.

Without this filter, ~80% of the universe (FAANG + high-priced
ETFs) produces uneconomic candidates that pass scanner gates only
to be vetoed at sizing — wasting Polygon API calls and producing
zero suggestions. Tonight's 19:16 UTC manual cycle was the
forcing example: 30 symbols → scanner → 1 candidate (AMZN $1247
underlying, $1223 max_loss) → 0 suggestions.

For small/standard tiers, no filter is applied; the full universe
is scanned per existing behavior. Hard cutoff matches the sizing
fix's tier transition.

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

### History

- Pre-2026-04-27: `RiskBudgetEngine` used flat 3% balanced default,
  silently overriding `SmallAccountCompounder`'s tier math via
  `min()` at `workflow_orchestrator.py:2347`. The compounder layer
  was documented but never wired through to per-trade sizing.
- 2026-04-27: tier-aware engine landed. Both layers now agree.
  Discovered during PR #827 fix validation when all 3 candidates
  (BAC at $286, AMZN at $1248, AAPL at $1274 single-contract risk)
  were vetoed at sizing because `max_risk_per_trade=$15` (3% of $500).

---

## Polygon dependency status (2026-04-27)

**Current state:**
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

**2026-04-27 plan upgrade:** Stocks Basic ($0) → Stocks Starter
($29/mo); Options Basic ($0) → Options Developer ($79/mo). Total
$108/mo recurring. Resolved #87 (chronic 429 + entitlement gap).
Polygon is now a durable paid provider for the foreseeable future.

**Phase-out status (post-upgrade):**

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

**Cost contingency:** $108/mo is the new monthly recurring cost.
If Polygon raises Starter or Options Developer pricing materially,
or if the live Alpaca account unlocks options + SIP entitlements
making redundancy free, revisit #68/#69 as the cost-driven
fallback path. Track Polygon billing changes as a soft signal
(no automated trigger).

**Backlog tracking:** items #65–#70, #87a/b, #88, #91 below.

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

- **2026-04-27 Polygon plan upgrade (#87 RESOLVED):** Stocks Basic
  ($0) → Stocks Starter ($29/mo); Options Basic ($0) → Options
  Developer ($79/mo). Total $108/mo recurring. Today's "chronic 429
  storm" was actually two stacked failures on Basic tier:
  (a) hard 5 calls/min/product cap, and (b) Basic tier lacked
  entitlements for the snapshot, Greeks, IV, and Open Interest
  endpoints used by the scanner — surfaced as `403 NOT_AUTHORIZED`
  on `/v3/snapshot` for KURA/AMZN options in worker logs. PR #823's
  H3 doctrine alerts (`polygon_circuit_open` × 46,
  `polygon_retries_exhausted` × 18 in 24h) gave us the diagnostic
  signal; the diagnostic narrative initially attributed it to
  cold-cache cycling but the underlying root cause was plan-tier
  insufficient + entitlements missing. No code change required —
  same API key, new entitlements propagate automatically. Tomorrow's
  16:00 UTC scheduled cycle is the validation window.
- **2026-04-27 universe-price filter for micro tier:** with the
  sizing fix landed (PR feat/micro-tier-90pct-single-position),
  the 19:16 UTC manual rerun proved the budget gate worked but
  produced 0 suggestions — only AMZN passed the scanner ($1247
  underlying, $1223 max_loss/contract), and $1223 > $450 micro
  budget. Root cause: ~80% of the 62-symbol universe is FAANG +
  high-priced ETFs whose contracts run $300-$1500; only sub-$50
  underlyings produce contracts that fit micro tier. Fix:
  `options_scanner._apply_tier_price_filter` drops symbols with
  underlying > $50 (configurable via `MICRO_TIER_MAX_UNDERLYING`
  env) for micro tier only. Inserted after the batch quote
  fetch, before per-symbol option-chain calls — saves Polygon
  API calls too. PR feat/85-micro-tier-universe-price-filter.
  Closes #85.
- **2026-04-27 sizing-layer override:** `RiskBudgetEngine` flat 3%
  balanced default silently shadowed `SmallAccountCompounder` tier
  math via `min()` at `workflow_orchestrator.py:2347`. With $500
  micro-tier capital, all 3 candidates (BAC/AMZN/AAPL) were vetoed
  at sizing because `max_risk_per_trade=$15` < single-contract risk
  ($286/$1248/$1274). Engine + compounder rewired tier-aware:
  micro = 90% × regime, one trade at a time; small/standard
  unchanged. `STRATEGY_TRACK` env now no-op for micro tier. Asymmetric
  concurrency gate (entries blocked when position open; exits continue).
  PR feat/micro-tier-90pct-single-position.
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

Completed items, full priority breakdown, and retrospective findings (Notable findings dates, scope corrections, hygiene gaps) live in `docs/roadmap.md`.

Active priorities are tracked in the ## Backlog section above.

---

## Working Style

- Respond with exact SQL, exact Railway commands, exact file paths — no placeholders
- When fixing bugs: show the broken code, explain why it's wrong, show the fix
- When adding features: check GAP priority order before building new things
- Prefer minimal diffs over full rewrites
- Always check `job_runs` table before assuming a cron ran successfully


## Backlog

Full backlog (item descriptions, sub-items, audit catalogs) lives in `docs/backlog.md`. This section keeps only the active focus.

### Active focus (next 3)

1. **#72-H4c** — workflow_orchestrator audit + ancillary doctrine sites (~half day).
2. **#87b** — `scanner_universe` metadata backfill (~half day, reduces per-cycle Polygon calls).
3. **#62a-D4-PR2** — routing dispatch enforcement (~1 day; builds on D4-PR1 to make conservative/neutral cohorts actually skip live dispatch).

See `docs/backlog.md` for full item descriptions and the catalogs (#62a schema drift, #72 loud-error doctrine).

---

## Live State (auto-updated)
- **Phase:** micro_live (since 2026-04-25 17:10:36Z)
- **Promotion gate:** bypassed; continuous-growth model
- **Open positions:** 0 (AMZN closed 2026-04-25 15:56Z, realized_pl +$325.50)
- **Alpaca live equity:** $500.00 (account 211900084)
- **Alpaca options BP:** $0.00 (ACH settlement pending)
- **Universe:** 62 symbols (refreshed 2026-04-25 17:17Z)
- **Last updated:** 2026-04-25
