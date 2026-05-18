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
- **EXECUTION_MODE env:** must be one of `internal_paper`, `alpaca_paper`, `alpaca_live`, `shadow`. Routes broker submissions accordingly. For live trading, also requires `LIVE_ENABLED=true` (second-stage safety check at `execution_router.py:88-94` falls back to `alpaca_paper` otherwise). **Bug fixed 2026-04-30:** EXECUTION_MODE was set to `'micro_live'` (phase name, not a valid mode value) for 5 days. Silent fallback to internal_paper. Surfaced when first candidate (BAC) reached the routing layer; force-closed within 15 min by per-symbol risk cap. Loud-error alert added at `execution_router.py` to prevent recurrence (#A4 sequence).
- **Promotion type:** manual operator-initiated. Green-day gate (1/4) bypassed; continuous-growth model adopted. Audit `risk_alerts.id = 82f1c294-19a4-4c66-8a68-0b0811ef5b24`.
- **Account:** live Alpaca `211900084`, options Level 3
- **Starting capital:** $500 on `v3_go_live_state.paper_baseline_capital` (set 2026-04-25 15:38:04Z, audit `c9d87caf-24db-4f7f-842a-748620a5c84f`)
- **Open positions:** 0 (AMZN closed 2026-04-25 15:56:36Z with realized_pl +$325.50, audit `b6229d5e-1543-4304-9ab1-6f37e0e869c8`)
- **Settlement:** `options_buying_power = $501.61` as of 2026-05-10 (ACH settled; equity $801.61, position_market_value $265 across the open CSX 43/47 debit spread)
- **Universe:** 62 symbols. PR #804 added F, BAC, SOFI, T, KO, VZ; sync triggered 2026-04-25 17:17Z (job_run `25eec261-d3e3-4b4a-aefe-2865770b001d`).
- **Pipeline status:** Full end-to-end pipeline validated 2026-04-10
- **daily_progression_eval:** Running at 16:00 CT. The alpaca_paper → micro_live promotion gate has been bypassed (operator-initiated promotion). Future phase transitions are a deferred decision under the continuous-growth model.
- **micro_live → full_auto auto-promotion (rewritten 2026-05-06):** `promotion_check` handler now auto-promotes when ALL gates pass: (1) broker equity ≥ $1500, (2) cumulative_realized_pl > 0 across Alpaca-real closed trades, (3) alpaca_real_trade_count ≥ 3. "Alpaca-real" excludes internal-paper-era simulations + the 34 corrupted rows from CLAUDE.md 2026-04-16 entry — the trade lens is now shared with `daily_progression_eval` via `get_alpaca_real_closed_trades` helper. Pre-rewrite, `promotion_check` read a non-existent `micro_live_green_days` column and never fired. Manual override (`ProgressionService.promote(...)`) preserved as bypass.
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
- **`background` queue (worker-background):** long-running jobs that would otherwise starve the primary queue. Currently routes only `iv_historical_backfill` (multi-hour BS-inversion backfill — see backlog Tier 1 candidate `[2026-05-15] worker-queue blocker` for the Phase 1 incident that motivated the split). Future long-running handlers should also be routed here by passing `queue_name=BACKGROUND_QUEUE` to their route's `enqueue_job_run(...)` call.

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

**Gap mostly closed 2026-05-04:** Shared `agent_session` context manager
at `packages/quantum/observability/agent_sessions.py` wraps the
`execute()` body of `IntradayRiskMonitor` (loss_minimization) and
`PostTradeLearningAgent` (self_learning). Both now write rows matching
Day Orchestrator's existing column convention (agent_name, status,
started_at, completed_at, summary) plus populate the schema's `error`
column on the failed path. Day Orchestrator left untouched in that PR
(refactor is separate scope).

**Remaining gap — Profit Optimization:** `apply_calibration` is a
per-suggestion math function called hundreds of times per scanner
cycle, not a per-invocation agent. Wrapping it row-by-row would flood
`agent_sessions` without insight. Per-cycle aggregation at
`workflow_orchestrator.py` is the right shape; that work is tracked
separately (would touch the highest-blast-radius file in the codebase).

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

**Weekend behavior (Mon-Fri only):** All scheduled jobs are Mon-Fri only — `day_of_week='mon-fri'` is applied uniformly to every job in the SCHEDULES list at `packages/quantum/scheduler.py:212-217` (and also to the non-SCHEDULES `auto_retry_failed` job at line 236-248). Saturday/Sunday silence is expected; `scheduler_heartbeat`, `iv_daily_refresh`, `suggestions_open`, etc. do NOT fire on weekends. Next fire after Friday close: Monday 04:30 CT (`iv_daily_refresh`). Operator-driven HTTP triggers via `scripts/run_signed_task.py` work normally over weekends — only the scheduler-driven dispatch is paused.

When investigating weekend silence (no `job_runs` over a weekend window), refer to this note before assuming outage. The Thursday 2026-05-14 morning outage was a real Mon-Fri outage with Supabase HTTP timeouts (see H11 doctrine); weekend silence is design. Saturday 2026-05-16 evening status check rediscovered this pattern in ~5 min and prompted this note.

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
-- 2026-04-13 pnl-corruption cutoff — see Bugs Fixed)
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

**[ADDENDUM 2026-05-12 — corrected framing from #62a-D1 sub-investigation]**

The "Original design vs Actual implementation" framing above was
accurate but incomplete. Sub-investigation revealed the system has
**two complete-but-unwired architectures**:

1. **Champion/challenger evaluator** (`policy_lab/evaluator.py`,
   `scoring.py`, `policy_lab_eval` scheduled job) — fully built,
   runs daily, scores all 3 cohorts via 7 promotion gates (≥3 days,
   ≥10 trades, no -20% drawdown, ≥15% utility margin, ≥70%
   posterior probability, drawdown not worse than champion, 2-day
   cooldown). On promotion: writes `UPDATE policy_lab_cohorts SET
   promoted_at = NOW()` AND inserts `policy_lab_promotions` audit
   row. 4 successful runs to date, 0 promotions (either no
   qualifying challenger or gates miscalibrated — empirical signal
   needed).
2. **Live route hardcode** (`fork.py:67`) — fully built since
   2026-03-20 (commit `f396334f`, original file commit). Hardcodes
   `cohort_name = "aggressive"`. No connection to evaluator output.

The evaluator writes `promoted_at`; the live route ignores
`promoted_at`. Nothing currently reads `promoted_at` for routing.

**Two silent-failure `is_champion` query sites are bugs:**
- `paper_autopilot_service.py:867` `_get_champion_portfolio`
- `paper_exit_evaluator.py:892` cohort fallback

Both query `is_champion = True` (a non-existent column), wrapped
in `try/except: pass`, return None on exception. Authored when
someone assumed the migration's `is_champion=true` INSERT intent
would land as a column. Architectural PR will replace these with
`promoted_at`-based queries OR delete them as redundant.

**DB state misalignment (pending correction):** `promoted_at` is
currently set on `neutral` (operator manual UPDATE on
2026-04-02 21:28Z, predating the intent clarification). Should be
on `aggressive` per operator intent confirmed 2026-05-12 (aggressive
= starting champion; conservative + neutral are shadow challengers).

**`POLICY_LAB_AUTOPROMOTE`** stays OFF (C-1 endpoint chosen) until
evaluator gates have empirical track record. Manual promotion only;
evaluator output is advisory until the gates are validated against
observed outcomes.

**Architectural PR queued (ships after CSX validation week):**
- DB: flip `promoted_at` from neutral to aggressive
- Fix the 2 silent-failure query sites (or delete if redundant)
- Modify `fork.py:67` to read current champion via `promoted_at`
  instead of hardcoding aggressive
- Effort: ~half day. No live trading behavior change at the time
  of wire-up (aggressive stays live; this is mechanical correctness,
  not param change). Tracked as #62a-D1.

**Doctrine note:** This is the first concrete instance of "parallel
architectures without integration" — adjacent to H9 wrapper-drift
in `docs/loud_error_doctrine.md` but a distinct class. Two complete
subsystems can each work in isolation while the integration seam
(the writer's output → consumer's input wire) is the bug. Worth
design-review discussion alongside #62a-D1's architectural PR.

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
- Compounding behavior implicit: the historical "25% ×
  multipliers" → 36% ceiling derivation already accounts for the
  1.2 compounding boost at score≥80; the allocator caps flat 36%
  regardless of `COMPOUNDING_MODE` value
- See `docs/small_tier_allocation.md` for full spec + 5 worked
  examples

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

Introduced 2026-05-18 (see `docs/small_tier_allocation.md`). Replaces
small tier's per-trade `3% × multipliers` independent-sizing pattern
with a cycle-aware allocator that distributes capital across the
viable candidate set BEFORE per-trade sizing fires. `PortfolioAllocator`
runs once per entry cycle, takes the candidate set + total equity +
regime + open positions as inputs, and returns per-candidate
allocated budgets. `RiskBudgetEngine` and `SmallAccountCompounder`
both accept an optional `allocation_hint` parameter; when provided
(small-tier production path), it overrides the legacy per-trade
multiplier stack. When absent (test paths, micro tier, standard
tier), legacy behavior is preserved.

### Worked examples ($500 capital, micro tier, NORMAL regime)

Micro tier examples (unchanged):

| Score | Regime | risk_budget |
|---:|---|---:|
| any | normal | $450 |
| any | suppressed | $405 |
| any | elevated | $360 |
| any | shock | $225 |

For $500 capital + score 85 + normal regime + `COMPOUNDING_MODE=true`:
`risk_pct = 0.90 × 1.0 = 0.90`, `risk_budget = $500 × 0.90 = $450`.

### Worked examples (small tier, post-2026-05-18 allocator)

Full math + 3 more examples in `docs/small_tier_allocation.md`.
Summaries:

- **$1,500, 4 candidates [95/88/82/76], normal:** allocator emits
  ~$280/$263/$255/$255 (total ~$1,053 = 70% of equity)
- **$1,500, 1 candidate [88], normal:** 36% ceiling binds → $540
  (single-candidate concentration defended by the ceiling)
- **$1,500, $450 open, 3 new candidates [90/82/74], normal:** envelope
  $825; allocator emits $367/$340/$118 (Cand 3 truncated by remaining
  envelope after open-position subtraction)

### Global allocation

**Micro tier:** `global_alloc.max = deployable_capital × 0.90 ×
regime_mult_for_micro`. Mirrors per-trade for one-at-a-time tiers.

**Small tier (post-2026-05-18):** `global_alloc.max = total_equity ×
0.85 × regime_mult`. Per-cycle availability after subtracting current
open-position cost basis. See `docs/small_tier_allocation.md` §2.

**Standard tier:** `global_alloc.max = total_equity × global_cap_pct`
(regime-based 5-50%, unchanged).

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

### History

- Pre-2026-04-27: `RiskBudgetEngine` used flat 3% balanced default,
  silently overriding `SmallAccountCompounder`'s tier math via
  `min()` at `workflow_orchestrator.py:2347`. The compounder layer
  was documented but never wired through to per-trade sizing.
- 2026-04-27: tier-aware engine landed. Both layers now agree.
  Discovered during PR #827 fix validation when all 3 candidates
  (BAC at $286, AMZN at $1248, AAPL at $1274 single-contract risk)
  were vetoed at sizing because `max_risk_per_trade=$15` (3% of $500).
- 2026-05-18: allocation-aware sizing policy landed for small tier.
  Replaces per-trade-independent `3% × multipliers` math with
  `PortfolioAllocator` cycle-aware distribution. Motivated by α's
  full-universe IV pipeline (Phase 3 v3 completed 2026-05-17)
  unlocking IV-sensitive strategies, expected to produce richer
  candidate sets per cycle as operator transitions from micro tier
  ($681) to small tier ($1500+). Spec at
  `docs/small_tier_allocation.md`; implementation in
  `packages/quantum/services/portfolio_allocator.py`; integration
  via additive `allocation_hint` parameter on `RiskBudgetEngine`
  and `SmallAccountCompounder` for backward-compat.

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

- **2026-05-18 BUG-A scale-asymmetric unrealized_pl recompute:**
  `intraday_risk_monitor._refresh_marks` multi-leg branch computed
  `leg_total` per-1-spread (using `leg.quantity = 1` per the stored
  per-leg JSON convention) but `entry_value` per-N-spread (using
  `pos.quantity`, e.g. 4). For any multi-contract position the
  subtraction `leg_total - entry_value` produced a fabricated large
  loss. Today's CSX 4-contract debit spread (entry $2.50, current
  spread mid ~$2.20) computed unrealized_pl = $220 - $1000 = -$780
  within 5 seconds of opening, triggering immediate intraday
  stop_loss force-close. Fix: scale BOTH sides by `pos.quantity` in
  the same step (long: `(per_spread_value - per_spread_entry) ×
  qty_abs`; short: `(per_spread_entry - abs(per_spread_value)) ×
  qty_abs`); credit/debit branch preserved. Inline scale-consistency
  invariant comment defends against regression. Single-leg branch
  was already scale-consistent; no change there. Tier-transition
  blocker — at micro tier (contracts=1) the bug was invisible; at
  small tier with `PortfolioAllocator` (PR #958) emitting 2-4
  contracts, this fires on every multi-contract live position.
  File: `packages/quantum/jobs/handlers/intraday_risk_monitor.py:354-407`.
- **2026-05-18 BUG-C retry against already-closed position:** within a
  single `intraday_risk_monitor` cycle, after the first successful
  force-close the in-memory `positions` list (fetched once at line
  127) is stale. The violation loop in 5b iterates
  `result.force_close_ids` per force-close-severity violation;
  multiple loss-envelope violations against the same position
  produced 4 spurious retries today. Two idempotency checks
  (`intraday_risk_monitor._execute_force_close:462-489` and
  `paper_exit_evaluator._close_position:1000-1024`) omitted
  status='filled' from their status filter — internal-paper close
  orders fill synchronously, so the prior close was already 'filled'
  and the retry punched through. Neither check filtered by side, so
  adding 'filled' alone would also match the (filled) entry order.
  `_close_position` had no `status='closed'`/`quantity=0` early-return,
  so retries reached compute_realized_pl(qty=0) and raised. Fix
  (4 sub-fixes): (a) add 'filled' + 'cancelled' to both idempotency
  filters AND scope by close side (sell for long, buy for short);
  (b) add `status='closed' or quantity=0` early-return to
  `_close_position` returning `routed_to='already_closed'` (not an
  error, expected behavior — H9 verified-state check); (c) move
  position fetch ahead of idempotency check in `_close_position` so
  the side filter can use observed `quantity`; (d) track
  `closed_in_this_cycle` set in `intraday_risk_monitor` violation
  loop and skip subsequent iterations for already-closed positions.
  Files: `packages/quantum/jobs/handlers/intraday_risk_monitor.py:186-260,453-505`;
  `packages/quantum/services/paper_exit_evaluator.py:995-1115`.
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
2. **H9 Convention Slot 1 — AST gate shipped 2026-05-12 in warn-only mode.** See `packages/quantum/tests/test_h9_wrapper_drift_gate.py`. Catches all 5 known H9 instances via fixtures; codebase scan found 7 real-but-deferred violations now in `packages/quantum/tests/h9_allow_list.yml` (4 are chain-level-verified / read-shaped false positives; 3 are genuine legacy migration candidates — `iv_point_service.upsert_point`, `position_pnl_service.refresh_marks_for_user`, `universe_service.sync_universe`). Plus 1 nested-handler refactor candidate (`alpaca_order_sync.sync_orders`). **Next step:** ~1 week observability via `h9_violations.json` CI artifact; flip `H9_GATE_STRICT = True` in `test_h9_wrapper_drift_gate.py` after the allow-list is stable. Slot 2 (silent-exception grep test) queued behind; may consolidate if Slot 1 covers same surface. Slot 3 (Literal status returns) adopted as convention for new wrappers.
3. **#62a-D1 architectural PR (queued)** — `promoted_at` flip from neutral → aggressive + fix 2 silent-failure `is_champion` query sites at `paper_autopilot_service.py:867` and `paper_exit_evaluator.py:892` + rewire `fork.py:67` to read champion via `promoted_at` lookup. ~half day. Backlog notes "ships after CSX validation week completes" — CSX is now reconciled but PR #908 empirical validation still pending, so technically still in window. Doctrine note: first concrete instance of "parallel architectures without integration" class (H12 candidate). NOTE: previous active focus item (#62a-D3 / #62a-D5 architectural decisions) was stale — both items closed 2026-05-10 (D3 via deletion in #62a sweep; D5 via Option B in same sweep).

See `docs/roadmap.md` for the full Active focus block including recently-closed items and `docs/backlog.md` for full item descriptions and the catalogs (#62a schema drift, #72 loud-error doctrine).

### Operational state notes

**[2026-05-17] iv_rank warmup — effectively closed for 67 of 70 active universe symbols.** Post-Phase 3 v3 (job_run `13b89a7e-642c-48f7-9e4f-259c4922eec4`, completed 2026-05-17 21:36 UTC, ~213 min duration), `underlying_iv_points` coverage is:

- **67 symbols at 61+ rows** → `iv_repository.get_iv_context` returns non-null `iv_rank`
- **2 symbols (WBD, XLK) at 60 rows** → at threshold, marginal
- **1 symbol (BKNG) at 30 rows** → still null; `daily_refresh` closes the gap naturally over ~30 trading days (mid-July 2026); see Tier 3 backlog observation 2026-05-17

IV-sensitive strategies (credit spreads, iron condors) are now decidable for ~95% of the active universe. Earlier "warmup window day N of ~60" framing was correct at Phase 1+2 delivery (3 reference symbols); Phase 3 v3 short-circuited the per-symbol day-counting wait. "No trade today" outcomes are STILL acceptable in learning-mode (per operating-mode codification above) — warmup gate is no longer the dominant reason for low trade frequency. Production observability remains H11 `risk_alerts` baseline; sample_size threshold no longer gates the universe.

**[2026-05-14] iv accounting alerts — RESOLVED (evening).** The `iv_handler_accounting_mismatch` alerts that fired 3 times in table history (2× on 2026-05-09, 1× on 2026-05-14, all with identical `stats_ok=1, actual_rows=5, delta=-4`) were traced via H5 unification investigation to a single mechanism: local developer pytest execution against real Supabase credentials.

**Root cause:** `test_iv_daily_refresh_handler.py` mocks `IVRepository` (causing `count_rows_for_date` to return hardcoded `5` at line 43) AND calls `run({})` directly (line 46) — bypassing `enqueue_job_run`. The handler's accounting check (`iv_daily_refresh.py:130-153`) does a lazy `from packages.quantum.observability.alerts import _get_admin_supabase` which reads env at call time and constructs a REAL admin client, then writes to production `risk_alerts` as a side-effect of test execution. All alert metadata reconciled: "5" = test mock; "1" = universe math (only AAPL succeeds); "delta=-4" = arithmetic; "no `job_runs`" = direct `run()` call.

**Fix applied (this PR):** test mocks `_get_admin_supabase` directly (primary); `_get_admin_supabase` gains a `PYTEST_CURRENT_TEST` env-guard returning `None` unless `ALERTS_ALLOW_ADMIN_UNDER_PYTEST=1` is set (defense-in-depth).

**Phase 1 readiness: CLEAR.** The production pathway is unaffected — Phase 1 trigger via standard `enqueue_job_run` uses real `IVRepository` against production Supabase; `count_rows_for_date` returns actual count; verification works correctly. `iv_historical_backfill` was never at risk (it writes its audit alert via the test-mocked `client` directly, not via the lazy `_get_admin_supabase` pattern).

**Cross-references:** see `docs/backlog.md` Tier 2 candidates (now RESOLVED) + today's silent invocation investigation in conversation history for full evidence chain.

**[2026-05-14] α Phase 1 trigger (post-plumbing PR).** α PR #935 shipped the `iv_historical_backfill` handler but the operator-trigger plumbing (HTTP route + `run_signed_task.py` registry entry) was missing — surfaced during today's Phase 1 trigger verification. Plumbing landed via the follow-up PR. Canonical Phase 1 trigger:

```
python scripts/run_signed_task.py iv_historical_backfill \
  --payload-json '{"days": 60, "symbols": ["SPY", "AAPL", "AMD"]}'
```

POSTs to `/internal/tasks/iv/historical-backfill`, writes a `job_runs` row via `enqueue_job_run`, worker claims and executes in production environment. Full observability via `job_runs` + handler's own audit `risk_alerts` row + new `underlying_iv_points` rows. Smoke variant: `'{"days": 1, "symbols": ["SPY"]}'` produces ~1 row for plumbing verification before the 60-day fire.

Phase 2 (manual validation) follows: capture barchart/Tastytrade `iv_rank` reference for SPY/AAPL/AMD; run `validate_alpha_backfill.py` harness; ≥2/3 within ±10 percentile points = α validated.

**[2026-05-15] α Phase 1 — COMPLETED (reference backfill clean).**

Phase 1 reference backfill completed successfully on 2026-05-15.
job_run_id: `9627c667-61e5-4915-a83c-a584b03bab0a`.

**Results:**
- Duration: 8.5 hours (11:55 → 20:28 UTC, longer than expected)
- Rows written: 165 (55 trading days × 3 underlyings)
- Data quality: PASS — `iv_30d` values smooth and within typical bounds:
  - SPY: 0.14-0.26 (avg 0.18)
  - AAPL: 0.23-0.33 (avg 0.28)
  - AMD: 0.54-0.69 (avg 0.60)
- Handler stats: ok=165, failed=0, skipped_existing=12, missing_data=3
- Accounting verification: PASS (handler's H9 post-write count matches table state)
- Alerts during run: only 2 info-severity audit rows from handler itself

**Phase 1 data is ready for Phase 2 manual validation.**

**Operational finding (captured as Tier 1 candidate in `docs/backlog.md`):**

Phase 1 ran during trading hours and starved the worker queue for 8.5 hours, delaying the entire trading-day pipeline (`day_orchestrator`, `suggestions_close`, `paper_exit_evaluate`, `suggestions_open`, `paper_auto_execute` all delayed 4-8h). When `suggestions_open` finally fired at 20:31 UTC it early-exited on staleness gate. Today's actual cost was low (0 open positions, micro tier) but the same pattern at higher tiers / with open positions starves `intraday_risk_monitor` + `paper_exit_evaluate` — both load-bearing. See backlog entry "[2026-05-15] TIER 1 CANDIDATE: worker-queue blocker" for full mechanism + three mitigation options.

**[2026-05-15] α Phase 2 — VALIDATED (3/3 symbols passed).**

Phase 2 manual validation completed via `packages.quantum.tests.validate_alpha_backfill` harness on 2026-05-15.

**Validation methodology:**

Harness reconstructs IV30 live via Polygon BS inversion for each reference symbol on a target date (2026-05-08), then prompts operator for an independent reference value (from barchart.com Options Overview History "Imp Vol" column). Computes delta in percentage points. Pass criterion: ≥2/3 symbols within ±10 percentage points.

**Results (3/3 passed):**

| Symbol | Reconstructed IV30 | Barchart Reference | Delta (pct-points) | Verdict |
|---|---|---|---|---|
| SPY | 0.1381 | 0.1512 | 1.31 | ✓ Pass |
| AAPL | 0.2261 | 0.2388 | 1.27 | ✓ Pass |
| AMD | 0.6814 | 0.6788 | 0.26 | ✓ Pass |

**Interpretation:**

All three reconstructed IV30 values closely match barchart's independently-computed Imp Vol values. Deltas range from 0.26 to 1.31 percentage points — well within the ±10 point tolerance. AMD's 0.26 point delta is particularly tight (essentially exact match despite 2026-05-08 being a high-IV day for AMD relative to its recent range).

**This validates:**

- Polygon BS inversion produces accurate IV30 values
- Phase 1's 165 bulk-written rows are trustworthy
- The historical IV pipeline can drive `iv_rank` computation reliably
- IV-rank-gated strategies can be confidently enabled at Phase 5 cutover

**Validation note (transparency):**

Operator entered SPY reference as `0.0512` (typo, missing leading "1") instead of `0.1512`. The harness recorded delta as 8.69 pct-points using the typo'd value. The verdict (Pass) was unchanged either way — `0.0512` still passes the ±10 tolerance — but the correct delta is 1.31 pct-points. Future readers should refer to the table above for accurate per-symbol deltas, not the harness's raw terminal output for SPY.

**α validation status: VALIDATED.**

**Phase 3 (full 67-symbol backfill) is now GATED ONLY on:**

- Worker-queue blocker mitigation (Tier 1 backlog candidate captured 2026-05-15 — see `docs/backlog.md`)

All other prerequisites are met (α implementation, trigger plumbing, Phase 1 backfill clean, Phase 2 validation passed).

**Phase 4 + Phase 5:** Will follow Phase 3 completion. Phase 4 = sanity check on `iv_rank` distribution post-backfill. Phase 5 = operational cutover where IV-sensitive strategies (credit spreads, iron condors per the structural finding entries above) activate automatically as `sample_size >= 60` is satisfied universe-wide.

**[2026-05-17] α Phase 3 — COMPLETED + α IMPLEMENTATION CHAIN DELIVERED.**

α historical IV backfill is operationally complete. Goal A (full-universe historical `iv_rank` decidability) achieved.

**Weekend arc 2026-05-15 to 2026-05-17 — chronological delivery chain:**

- **PR #946 (worker queue separation):** new `worker-background` Railway service listening on `background` RQ queue, isolated from trading-day pipeline (`otc` queue). Phase 1's 8.5h run no longer starves trading-day jobs.
- **PR-A2 (PR #948):** `expired=true` parameter on Polygon contracts endpoint. Finding B mechanical fix: contract listings now time-stable.
- **PR-A (PR #950, range-query refactor):** per-contract range OHLC fetch replacing per-(symbol, date, contract) serial calls. Phase 3 wall-clock projection dropped from ~4.5 days to ~hours.
- **F1 (PR #952, RQ timeout map):** per-job-name timeout overrides; `iv_historical_backfill` gets 6h budget (default 10m preserved for trading-day jobs).
- **F2a (PR #953, pagination cap):** raised contract-listing default cap from 1000 to 20000. Deep-chain symbols (QQQ, MSFT, NVDA, etc.) had their pagination budget consumed by daily-expiry strikes; F2a unblocks full coverage.
- **Phase 3 v3:** full-universe backfill (job_run `13b89a7e-...`, ~3.5h runtime, 67 of 70 symbols at full 61-row coverage, 0 failed).

**Outstanding (Tier 2/3 backlog; not blocking):**

- **Finding C (Tier 2, captured 2026-05-17, PR #949):** anchor-selection time-instability. Same `(symbol, as_of_date)` may produce different `iv_30d` over time as available-contract set shifts. iv_rank consumers tolerate ~1-2 pct-pt drift.
- **BKNG sparse residual (Tier 3, captured 2026-05-17, PR #954):** F2a recovered 18 of 19 sparse symbols; BKNG (Booking Holdings, ~$4500/share) remains at 30 rows. Hypotheses range from chain-depth exceeding new 20000 cap to strike-density interaction; investigation when prioritized.

**Architectural notes for future readers:**

- "Phase 3 (full-universe backfill)" is no longer aspirational — it's an operationally tractable trigger with explicit `symbols` list payload. Option P3c (handler-side universe loading via `scanner_universe` table) was discussed but not shipped; explicit symbols in payload is the current pattern.
- Worker queue separation (PR #946) is justified by actual usage: long backfill jobs (~3.5h+) MUST route to `background` queue to avoid starving trading-day pipeline.
- Polygon Options Developer tier ($79/mo) is sufficient for α's BS-inversion approach; Options Advanced doesn't expose historical pre-computed IV (verified Sunday 2026-05-17 investigation). Vendor change not needed.

**Phase 4 + Phase 5 framing UPDATED:** with Phase 3 complete and `iv_rank` decidable for 67 symbols, the boundary between "Phase 4 sanity check" and "Phase 5 operational cutover" is fuzzy — IV-sensitive strategies are now technically active via `strategy_selector`'s existing `iv_rank` consumer paths. Operator-driven empirical observation will surface any cutover concerns; no explicit cutover event needed.

### Exit thresholds (defaults under empirical review)

**Current values** (`paper_exit_evaluator.py:329-330`):

- `_DEFAULT_TARGET_PROFIT_PCT = 0.35` — Target profit fires at +35% of entry cost (env-overridable via `EXIT_TARGET_PROFIT_PCT`)
- `_DEFAULT_STOP_LOSS_PCT = 0.50` — Stop loss fires at -50% of entry cost (env-overridable via `EXIT_STOP_LOSS_PCT`)

**Time-scaling** (`paper_exit_evaluator.py:180-203`, stop-loss scaling 225-258):

- Profit target time-scales 50% (at entry) → 25% (near expiry) via sqrt-decay function, locking in profits before theta accelerates against winners.
- Stop loss is FLAT by default (no time-scaling). As of 2026-05-18, a symmetric sqrt-decay path exists for debit_spread stops, gated behind `EXIT_STOP_LOSS_TIME_SCALING_ENABLED=1` (default OFF). When enabled: sl tightens 50% → floor 0.30 (`EXIT_STOP_LOSS_FLOOR_PCT`). Iron condors explicitly bypass via `_is_iron_condor` guardrail. See `docs/audit_hold_period_asymmetry.md` for the audit (LOW confidence at N=6; sample 5+ weeks stale).

**Status: inherited defaults, under empirical review.**

These threshold values were inherited rather than set by deliberate design. They produce an asymmetric exit profile (system tolerates more loss than gain before exiting):

- Threshold ratio: 50/35 = 1.43× (loss tolerance vs gain capture)
- Within-strategy hold ratio observed: ~2.5× (debit spreads, N=15 across both buckets)
- Aggregate hold ratio observed: ~5× (across full strategy mix — partly inflated by iron-condor wins resolving fast vs debit-spread losses bleeding slow)

**Empirical observation as of 2026-05-13 (90-day window, paper_positions):**

| Strategy family | Exit type | N | Avg hold | Avg PnL |
|---|---|---|---|---|
| iron_condor | profit_target | 35 | 18.4h | +$1,852 |
| iron_condor | stop_loss | 1 | 96.4h | +$1,202* |
| debit_spread | profit_target | 9 | 56.4h | +$1,511 |
| debit_spread | stop_loss | 6 | 143.4h | -$2,063 |
| debit_spread | other_close | 13 | 89.9h | -$40 |

\* The single iron-condor stop_loss is profitable — wing-breach exit on already-profitable position. PR #929's `hold_period_buckets` v2 view buckets this as `profitable_stop` to avoid mislabeling.

**Re-evaluation criterion:** when debit-spread sample reaches **N=20 per outcome bucket** (currently 9 winners / 6 losers), re-investigate whether 35/50 is the right threshold pair for micro-tier behavior. Earlier re-evaluation may be triggered if outcome-bucket pattern shifts substantially. See `docs/backlog.md` "[2026-05-13] WATCH: Exit threshold re-evaluation trigger (N=20)" entry.

**What this note does NOT claim:**
- That 35/50 is the right design (they're inherited, not validated)
- That they should be changed (insufficient evidence either way)
- That asymmetry is wrong (asymmetric thresholds are common in options strategies; just not deliberately chosen here)

**Cross-references:**
- Hold-ratio investigation 2026-05-13 (session history)
- PR #928 (`hold_period_buckets` v1 view that surfaces this data)
- PR #929 (this PR — operational note + view v2 relabel)
- Learning-mode codification — micro tier IS the development environment for evaluating these defaults

### Structural learning: 2-leg debit spread geometry at micro BP (2026-05-14)

**Specific finding (well-supported by Path A + Option A experiments):**

At $681 micro BP, with H7 round-trip safety enforced, and with the scanner's current 2-leg debit spread emissions using $5-wide strikes on $50+ underlyings:

- Typical max_loss per contract: ~$500
- Round-trip cost (entry + 1.1× close safety): ~$1,020
- $1,020 > $681 BP → contracts=0 → REJECT at sizing layer
- Result: 2-leg debit spreads on $50+ underlyings cannot pass H7 at current capital

**This is mechanical math, not a tunable parameter.** The H7 check is load-bearing capital invariant (codified after the BAC 2026-05-01 ghost-position incident); the chain geometry comes from underlying market structure ($5-wide strikes are standard for $50-$200 stocks); the budget is the operator's current capital.

**What this DOES NOT imply (over-generalization warned against):**

The diagnostic synthesis initially generalized this finding to "no strategies fit at $681." Operator caught the over-generalization. The specific finding does NOT imply:

- That NO strategies fit at $681 (some may; not all tested)
- That capital scaling is the only path (strategy class change also changes the math)
- That the H7 check should be modified (it's working correctly)
- That spread-width should be changed across all tiers (yesterday's γ1 near-miss showed why)

**Specific NOT-evaluated cases that may still be viable at $681:**

- 2-leg credit spreads (max_loss = width − premium collected)
- Iron condors (4-leg credit structure with collected premium)
- 1-leg long options where premium is small (max_loss = premium paid)
- 2-leg debit spreads on sub-$30 underlyings with $1 or $2.50 strikes (max_loss reduced by chain granularity)
- Different delta-gap strategies producing narrower max_loss

**Diagnostic gate:** before claiming "strategy X doesn't fit," verify empirically with chain data + sizing math. Without that verification, "doesn't fit" is over-generalization (H12 instance from 2026-05-14 — see `docs/loud_error_doctrine.md` meta-observation).

**Operational implication:**

Two strategic responses possible (NOT decided in this note):
1. **Capital scaling** — adds available BP, makes existing geometry work
2. **Strategy class shift** — different geometry, may work at current BP

Both may apply. See `docs/backlog.md` "Capital scaling framework" entry for open questions; α implementation (separate work) tests the strategy-class-shift hypothesis.

**Refinement of "perfect code" (learning-mode):**

The learning-mode codification stated: "At micro tier I want to perfect the code and make sure it enters and exits accordingly. After these are perfected I will add more capital."

Today's finding refines "perfect code" to include **structural fit between emission geometry and operational capital**. A scanner that produces emissions structurally incompatible with available BP at the intended capital level is not "perfected" — it has a structural mismatch.

The codification's discipline is preserved: code must be perfected before capital scales. Today's finding clarifies that "perfected" includes "structural fit between emission geometry and operational capital."

**Cross-references:**
- Path A experiment (2026-05-12) — empirical refutation of $100 cap (KO H7 trace)
- Option A experiment / PR #932 (2026-05-13) — Path A reverted
- Option A validation 2026-05-14 — empirical refutation of "pure $60 revert reliably produces creatable candidates"
- KO H7 trace 2026-05-13 (downstream gate identification)
- γ1 near-miss 2026-05-13 (wrong-line attribution — H12 instance 4)
- Scheduler-stuck mechanism attribution 2026-05-14 (H12 instance 5)
- Meta-observation 2026-05-14 (H12 applies to synthesis scope; this entry is the corrective)
- `docs/backlog.md` Capital scaling framework entry

### Structural finding refinement — Entry-premium-vs-width ratio (2026-05-14)

**Pairs with:** the prior structural learning note above ("2-leg debit spread geometry at micro BP"). The prior note identifies the symptom; this note identifies the mechanism. Read together.

**Refinement:**

The prior note identified that current 2-leg debit spread emissions with $5-wide chains on $50+ underlyings exceed H7 round-trip safety at $681. The 2026-05-14 budget-fit diagnostic (empirical test of 22+ structures across 3 sample underlyings: HBAN $15.57, KHC $23.58, KO $80.72) identified the underlying mechanism:

**The H7-fit constraint is governed by entry-premium-vs-width ratio, NOT by width or leg count alone.**

Max_loss for any spread structure follows:
- Debit spread: `max_loss = (width × 100) − entry_premium_paid`
- Credit spread: `max_loss = (width × 100) − premium_collected`

H7 requires `max_loss × 2.1 ≤ available_BP`. At $681 BP, `max_loss ≤ ~$324/contract`.

**Empirical examples (2026-05-14 ~late-morning CT snapshot):**

| Underlying | Width | Structure | Entry/Credit | Max_loss | Fits at $681? |
|---|---|---|---|---|---|
| KO ($80) | $5 | debit ATM-OTM (77.5C/82.5C) | $301 paid | $199 | NO ($418 RT — matches the prior note's firing case) |
| KO ($80) | $2.50 | debit deep-ITM (77.5C/80C) | $175 paid | $75 | YES ($158 RT) |
| KO ($80) | $2.50 | debit ATM-OTM (82.5C/85C) | $65 paid | $185 | NO ($389 RT) |
| KO ($80) | $1 | credit OTM put (79P/78P) | $26 collected | $74 | YES ($155 RT) |
| KO ($80) | $1 | iron condor (78P/79P/82C/83C) | $46 net credit | $54/wing | YES ($113 RT) |
| KHC ($23) | $0.50 | debit ATM (23C/23.5C) | $24.50 paid | $25.50 | YES ($54 RT) |
| KHC ($23) | $1 IC | iron condor (21.5P/22.5P/24.5C/25.5C) | $21 net credit | $79/wing | YES ($166 RT) |
| HBAN ($15) | $1 | debit OTM (16C/17C) | $25 paid | $75 | YES ($158 RT) |

**Implications for scanner emission patterns (observation, not action):**

The scanner's `_select_legs_from_chain` uses delta-target leg selection, which naturally clusters legs ATM-to-OTM. At $50+ underlyings with $5-wide chains, ATM-OTM debit spreads produce the worst H7-fit region (low entry premium → high max_loss). This is exactly why the KO emission failed H7 in the prior note's example. (Note: the spread-width line at `options_scanner.py:1260` is iron-condor-only — see γ1 wrong-line attribution from 2026-05-13, H12 instance 4.)

For scanner emission to produce H7-fittable candidates at $50+ underlyings at micro capital, one of:
- **Different strategy class:** credit spreads collect premium, reducing max_loss
- **Strike-granularity awareness:** KO Jun 12 has $1 strikes, Jun 18 has $2.50 — varies by expiration cycle
- **Universe extending to sub-$30 names** with $0.50 or $1 chain granularity (KHC has $0.50 strikes)
- **Delta-target reaching deep-ITM:** high entry premium → low max_loss (counter-intuitive but mechanically correct)

**Verified-fittable structure classes at $681 (2026-05-14 snapshot):**

- **Class A (1-leg long options at modest deltas):** widely fits (16/22 tested). Lower systematic edge; scanner doesn't currently target this surface.
- **Class B (sub-$30 narrow-strike debit spreads):** universally fits (8/8 tested). Robust across $0.50, $1, $2-wide.
- **Class C ($1-wide credit spreads):** fits broadly on both sub-$30 and $50+ names; thin per-contract credit ($9-$46) on $50+ names.
- **Class D (narrow-wing iron condors):** fits per-contract math on KO and KHC, BUT blocked by `iv_rank` gate in `strategy_selector` until α implementation accumulates historical IV depth. **α directly unlocks this class.**
- **Class E (cash-secured puts / covered calls):** excluded — underlying capital reservation ($1,400+ even for HBAN) far exceeds $681 BP.

**Downstream-gate observation (added 2026-05-14 from midday cycle):**

The 2026-05-14 16:00 UTC suggestions_open cycle produced a Ford F LONG_CALL_DEBIT_SPREAD candidate (Class B territory, sub-$15 underlying). The candidate passed scanner-internal gates → H7 round-trip safety → universe filter → reached `trade_suggestions` table → blocked at `edge_below_minimum` (EV 15.44 below threshold). Final status: `NOT_EXECUTABLE`.

This refines the budget-fit landscape: **Class B fits H7 but a separate downstream gate (`edge_below_minimum`) catches sub-$30 narrow-strike candidates with thin expected value.** H7 fit is necessary but not sufficient for creatable suggestions.

For an empirical candidate to reach `status=EXECUTABLE`, it must clear: universe filter → scanner emission gates → H7 round-trip safety → `edge_below_minimum` → any further downstream gates not yet observed. For Class B candidates specifically, the binding constraint has shifted from H7 to `edge_below_minimum`.

**Cross-references:**
- PR #934 (the prior narrow-scope structural finding; this note pairs with it)
- 2026-05-14 budget-fit diagnostic (empirical evidence base — see `docs/backlog.md` 2026-05-14 entry)
- Capital scaling framework (`docs/backlog.md` 2026-05-14 framework entry — informs Q1 trigger)
- PR #935 (α historical IV backfill — directly unlocks Class D)
- 2026-05-14 cycle-shape diagnostic (Ford F downstream-gate observation — see backlog refinement sub-section)
- H12 framing-artifact doctrine (`docs/loud_error_doctrine.md`) — the "no strategies fit" over-generalization (instance #5) is what this empirical work corrects; the cycle-shape misread (instance #6) is what surfaced the Ford F observation

**What this note refines and what it preserves:**

Refines: the constraint isn't "width" or "leg count" — it's entry-premium-vs-width ratio. Multiple structure classes fit at $681 with different geometry choices. α is more load-bearing than "observability fill" — it unlocks a verified-fittable structure class. And: H7 fit is not sufficient — `edge_below_minimum` is the next-most-load-bearing downstream gate for Class B.

Preserves: the prior note's specific finding remains accurate (current 2-leg debit spread emissions with $5-wide chains on $50+ underlyings DO fail H7 — that's the symptom). This note's mechanism explanation doesn't invalidate that symptom observation; it identifies why.

**Sample-size caveats:** 3 underlyings. Bid-ask spreads run 20-100%+ on OTM wings of sub-$30 names. KO IV at 0.17-0.21 is historically low — a vol spike would shift Class C/D credit collected meaningfully and could re-shape the landscape. Findings phrased as "fits today on names tested at current IV" not "always fits."

---

## Live State (auto-updated)
- **Phase:** micro_live (since 2026-04-25 17:10:36Z)
- **Promotion gate:** bypassed; continuous-growth model
- **Open positions:** 0 (AMZN closed 2026-04-25 15:56Z, realized_pl +$325.50)
- **Alpaca live equity:** $500.00 (account 211900084)
- **Alpaca options BP:** $501.61 (ACH settled)
- **Universe:** 62 symbols (refreshed 2026-04-25 17:17Z)
- **Last updated:** 2026-04-25
