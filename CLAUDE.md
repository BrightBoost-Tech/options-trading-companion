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

- **Trading mode:** `alpaca_paper` (EXECUTION_MODE env)
- **Promotion target:** 4 consecutive green days through Alpaca → `micro_live`
- **Green days so far:** 1 of 4 required
- **Last green day:** 2026-04-16 (counted after ghost-position reconcile + weekly_pnl math fix)
- **Open positions:** 0 (reconciled 2026-04-16 ~20:00Z)
- **Pipeline status:** Full end-to-end pipeline validated 2026-04-10
- **daily_progression_eval:** Running at 16:00 CT (21:00 UTC standard / 20:00 UTC DST)
- **Iron condors:** DISABLED in current phase. Debit spreads only.
- **Calibration job:** Running daily at 05:00 CT; writes to `calibration_adjustments`.
- **Risk profile:** 70/100 — aggressive paper growth (8% base risk, compounding ON, 4 max trades)
- **Alpaca live account:** Approved Level 3 options trading (spreads, multi-leg)
- **Live trading:** Ready pending 4 consecutive green days in alpaca_paper phase

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

## Live State (auto-updated)
- **Phase:** alpaca_paper
- **Green days:** 1 of 4 required
- **Last green day:** 2026-04-16
- **Open positions:** 0 (matches Alpaca `get_all_positions()` → [])
- **Alpaca equity:** $97,276.32 (last_equity $97,711.88 close of 4/15)
- **Last updated:** 2026-04-17 01:05
