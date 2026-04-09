# Options Trading Companion — Project Context
# Loaded by Claude Code on EVERY turn. Keep this current.

---

## Identity & Repo

- **Repo:** BrightBoost-Tech/options-trading-companion
- **Owner User ID:** 75ee12ad-b119-4f32-aeea-19b4ef55d587
- **Stack:** Python/FastAPI backend (`packages/quantum`) · Next.js frontend · Supabase Postgres · Railway deploy · GitHub Actions cron · Alpaca market data (primary for options) · Polygon.io (equities + reference data) · Alpaca broker API

---

## Current Phase

- **Trading mode:** `alpaca_paper`
- **Promotion target:** 4 consecutive green days through Alpaca → advances to `micro_live`
- **Green days so far:** Reset to 0 on 2026-04-04 (internal fills were miscounted; audit trail logged)
- **Iron condors:** DISABLED in current phase. Debit spreads only.
- **Calibration job:** Currently skipping with exit code 2 (insufficient data — expected until more paper trades accumulate)
- **RISK_MAX_SYMBOL_PCT=0.40** (paper phase — tighten to 0.30 at micro_live, 0.25 at live)

---

## Infrastructure

| Service | URL / Location |
|---|---|
| Backend (Railway) | https://be-production-48b1.up.railway.app |
| Frontend (Railway) | https://fe-production-d711.up.railway.app |
| Supabase project | etd1ladeorfgdmsopzmz.supabase.co |
| GitHub Actions | Fallback/manual dispatch only (APScheduler is primary) |

### Key Environment Variables (Railway backend)
- `TRADING_MODE` — `paper` / `micro_live` / `live`
- `TASK_NONCE_PROTECTION=1` ← must be set in prod
- `TASK_NONCE_FAIL_CLOSED_IN_PROD=1` ← must be set in prod
- `ALLOW_LEGACY_CRON_SECRET=0` ← must be set in prod
- `SCHEDULER_ENABLED=1` ← enables APScheduler (primary scheduler)
- `RISK_ENVELOPE_ENFORCE=0` ← set to 1 after 2026-04-13 to enable force-close
- `PROFIT_AGENT_RANKING=0` ← set to 1 after 5 days of learning data
- `ORCHESTRATOR_ENABLED=0` ← set to 1 after all agents tested individually

---

## Architecture (v4 — 16 Layers + 4 Managed Agents)

1. Market Data (Alpaca primary for options, Polygon for equities/reference)
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
14. UI/UX (Next.js)
15. Quantum
16. Regression / Determinism Bot

### Managed Agents (Claude Console)
| Agent | Schedule | Purpose | Feature Flag |
|---|---|---|---|
| Loss Minimization | Every 15 min (9:30-4 CT) | Intraday risk envelope monitoring + force-close | `RISK_ENVELOPE_ENFORCE` |
| Self-Learning | 4:45 PM CT daily | Post-trade calibration, drift detection, strategy health | Always on |
| Profit Optimization | Applied during suggestions_open | Dynamic weight loading from learned calibrations | `PROFIT_AGENT_RANKING` |
| Day Orchestrator | 7:30 AM CT daily | Boot check, missed job detection, chain status | `ORCHESTRATOR_ENABLED` |

---

## Market Data Provider Routing

| Data Type | Primary Provider | Fallback |
|---|---|---|
| Options snapshots (MTM) | Alpaca `/v1beta1/options/snapshots` | Polygon `/v3/snapshot` |
| Option chains (scanner) | Alpaca `/v1beta1/options/snapshots/{underlying}` | Polygon `/v3/snapshot/options/{underlying}` |
| Equity snapshots | Polygon `/v3/snapshot` | — |
| Daily bars (IV rank, trend) | Polygon `/v2/aggs` | — |
| Earnings dates | Polygon `/vX/reference/financials` | — |
| Historical contracts | Polygon `/v3/reference/options/contracts` | — |

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

## Key Database Tables

| Table | Purpose |
|---|---|
| `paper_positions` | Open/closed paper positions |
| `paper_orders` | Order fills (execution_mode: internal_paper or alpaca_paper) |
| `go_live_progression` | Current phase + green days count |
| `go_live_progression_log` | Audit trail of phase events |
| `policy_lab_cohorts` | 3 active cohorts (conservative / moderate / aggressive) |
| `learning_trade_outcomes_v3` | VIEW: realized P&L joined with suggestions |
| `learning_feedback_loops` | Raw outcome records from paper/live ingest |
| `calibration_adjustments` | EV/PoP multipliers per (strategy, regime, dte_bucket) |
| `paper_eod_snapshots` | Daily MTM marks per position |
| `job_runs` | Job execution log (idempotency + status) |
| `risk_alerts` | Risk violations, force-close events, drift alerts |
| `signal_weight_history` | Calibration multiplier changes per segment |
| `strategy_adjustments` | Strategy-level weight reductions/flags |
| `agent_sessions` | Managed Agent session observability |
| `policy_decisions` | Per-cohort accept/reject decisions with realized_outcome |

### Quick Health Check SQL
```sql
-- Phase status
SELECT current_phase, alpaca_paper_green_days, alpaca_paper_last_green_date
FROM go_live_progression;

-- Open positions
SELECT symbol, quantity, avg_entry_price, current_mark, unrealized_pl, status, cohort_id
FROM paper_positions WHERE status = 'open' ORDER BY created_at DESC;

-- Today's job runs
SELECT job_name, status, finished_at FROM job_runs
WHERE created_at::date = CURRENT_DATE ORDER BY created_at;

-- Risk alerts (last 24h)
SELECT alert_type, severity, symbol, message, created_at FROM risk_alerts
WHERE created_at > NOW() - INTERVAL '24 hours' ORDER BY created_at DESC;

-- Learning agent activity
SELECT segment_key, old_multiplier, new_multiplier, trade_count, trigger
FROM signal_weight_history ORDER BY created_at DESC LIMIT 10;

-- Agent sessions
SELECT agent_name, status, started_at, completed_at FROM agent_sessions
ORDER BY created_at DESC LIMIT 5;
```

---

## 5 Open Code Gaps (implement in this order)

- **GAP 1** — Canonical ranking metric: expected PnL after slippage/fees ÷ marginal risk, adjusted for correlation/concentration. Replace ALL other ranking objectives. ← DynamicWeightService lays groundwork; full implementation pending.
- **GAP 2** — EV-aware exit ranking: close worst marginal-EV positions first (replace `min_one` logic).
- **GAP 3** — Score/PoP/EV calibration against realized outcomes by strategy, regime, DTE, liquidity, earnings context. ← Self-Learning Agent now automates this via exponential decay calibration.
- **GAP 4** — Autotune: replace threshold mutation with walk-forward validation + promotion/demotion rules.
- **GAP 5** — Production security flags (set in Railway env, not code). ← Broker + policy lab auth fix deployed 2026-04-09.

---

## Promotion Path

```
paper → micro_live ($500–$1K, Alpaca, 5 days) → live ($2.5–$5K, 30 days) → full automation
```

Gate to `micro_live`: 4 consecutive Alpaca paper green days (not internal fills).

---

## NEVER DO

- Count `internal_paper` execution_mode fills as green days — Alpaca fills only
- Enable iron condors during `alpaca_paper` phase
- Rebuild entire system prompt on every AI call (split static/dynamic)
- Start a new Claude Code session without `--continue` on this project
- Use ChatGPT mid-build — all architecture decisions live here; mixing tools creates drift
- Deploy without verifying `TASK_NONCE_PROTECTION=1` in Railway
- Touch intraday_risk_monitor.py or risk_alerts migration (Loss Agent is deployed and stable)
- Enable `RISK_ENVELOPE_ENFORCE=1` before 2026-04-13 (observation period)
- Enable `PROFIT_AGENT_RANKING=1` before 5 days of learning data exist
- Duplicate close-order logic — always use `PaperExitEvaluator._close_position()`

---

## Bugs Fixed (do not re-introduce)

- All-or-nothing leg pricing on MTM (if any leg fails to quote, skip entire position mark)
- `nearest_expiry` backfill required for exit conditions to work
- `paper_learning_ingest` must be in cron — not just manual trigger
- OCC symbol format for Alpaca order submission
- Internal fills miscounted as Alpaca fills in green day logic (fixed + reset 2026-04-04)
- Polygon options data empty (plan lacks quotes) — Alpaca now primary for options snapshots + chains (2026-04-08)
- MTM `_compute_position_value_from_snapshots` read `snap.get("bid")` instead of `snap.get("quote", {}).get("bid")` — fixed 2026-04-08
- 11 broker endpoints + 6 policy lab endpoints missing explicit `Depends(get_current_user)` — fixed 2026-04-09
- Deprecated `POST /tasks/iv/daily-refresh` stub accepting legacy X-Cron-Secret — removed 2026-04-09
- `calculate_portfolio_inputs()` was synchronous inside async optimizer endpoint — wrapped in run_in_executor 2026-04-10
- Close orders missing `position_intent` — Alpaca inferred `buy_to_open` instead of `buy_to_close`, rejecting ADBE/AVGO exits. Fixed: set `buy_to_close`/`sell_to_close` per leg when `position_id` is set (2026-04-10)
- Close orders on near-worthless spreads had negative `limit_price` (AMD: -1.53). Alpaca rejects limit ≤ 0. Fixed: clamp to 0.01 for close orders (2026-04-10)
- `paper_exit_evaluate` 3 PM run never fired — idempotency key `{date}-exit-evaluate-{user_id}` was same for 8:15 AM and 3:00 PM. Morning's `succeeded` record blocked afternoon. Fixed: key now includes UTC hour (2026-04-10)
- `LIVE_MANUAL_APPROVAL=true` is NOT wired into paper submission path — `safety_checks.py` defines it but `paper_endpoints.py` and `paper_exit_evaluator.py` never call `stage_for_approval()`. Paper orders go directly to `submit_and_track()`. No fix needed.

---

## Roadmap Status

- [x] 10-day paper test complete
- [x] Policy Lab (3 cohorts active)
- [x] Alpaca paper execution live
- [x] Parallel reads via asyncio.gather() in suggestion pipeline
- [x] Fast-path weekend/no-user checks on startup
- [x] Alpaca retry: 10 retries, exponential backoff with jitter, 90s watchdog, needs_manual_review fallback
- [x] Option chain cache TTL extended to 300s (env-configurable)
- [x] Directional bid/ask pricing on spread legs (sell@bid, buy@ask) + 5% slippage floor in canonical ranker
- [x] Calibration enabled by default, threshold lowered to 8 trades, added to scheduler, applied to morning window
- [x] Promotion check job: detects stuck phase transitions, logs CRITICAL alerts for go_live_gate cancellations
- [x] Risk envelope wired into pre-entry and MTM (warn-only mode — log violations, no blocking)
- [x] Multi-strategy scan caching: bars, regime, chain fetched once per symbol, reused across strategy retries
- [x] Debit spread stop loss widened from 20% to 50% (was triggering on normal bid-ask noise with 25-45 DTE)
- [x] Scheduler heartbeat job + never_run alert escalation (ops_health_check now alerts on dead scheduler)
- [x] Calibration DTE-bucket segmentation: adjustments now computed per (strategy, regime, dte_bucket)
- [x] Risk envelope circuit breaker: auto-execute blocks new entries when envelope is breached (force-close still warn-only)
- [x] Alpaca primary for options data — Polygon fallback only (2026-04-08)
- [x] Security: explicit auth on all 17 broker + policy lab endpoints (2026-04-09)
- [x] Loss Minimization Agent: 15-min intraday risk monitor with force-close capability (2026-04-09)
- [x] Self-Learning Agent: post-trade calibration, drift detection, strategy health flagging (2026-04-10)
- [x] Profit Optimization Agent: dynamic weight loading from learned calibrations (2026-04-10)
- [x] Day Orchestrator Agent: boot check, missed job detection, chain status (2026-04-10)
- [x] Efficiency: async optimizer, V4 quality cache, condor EV memoization (2026-04-10)
- [x] Alpaca close order fixes: position_intent + negative limit_price clamp + exit-evaluate idempotency (2026-04-10)
- [ ] Risk envelope: switch force-close from warn-only to block mode (RISK_ENVELOPE_ENFORCE=1 after 2026-04-13)
- [ ] Enable PROFIT_AGENT_RANKING=1 after 5 days of learning data
- [ ] Enable ORCHESTRATOR_ENABLED=1 after individual agent testing
- [ ] GAP 1–2 implementation
- [ ] Micro-live test ($500 cap, separate portfolio)
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
- **Green days:** 0
- **Last green:** 
- **Open positions:** 4
- **Last updated:** 2026-04-10 00:00
