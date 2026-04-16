# Options Trading Companion â€” Project Context
# Loaded by Claude Code on EVERY turn. Keep this current.

---

## Identity & Repo

- **Repo:** BrightBoost-Tech/options-trading-companion
- **Owner User ID:** 75ee12ad-b119-4f32-aeea-19b4ef55d587
- **Stack:** Python/FastAPI backend (`packages/quantum`) Â· Next.js frontend Â· Supabase Postgres Â· Railway deploy Â· GitHub Actions cron Â· Alpaca market data (primary for options) Â· Polygon.io (equities + reference data) Â· Alpaca broker API

---

## Current Phase

- **Trading mode:** `alpaca_paper`
- **Promotion target:** 4 consecutive green days through Alpaca â†’ advances to `micro_live`
- **Green days so far:** 0 â€” missed 2026-04-10 by $54.50
- **Open positions:** 4 â€” AMD, ADBE, MSFT, NFLX (all entered 2026-04-10)
- **Net unrealized:** -$54.50 at EOD 2026-04-10
- **Pipeline status:** Full end-to-end pipeline validated 2026-04-10 (first successful run)
- **daily_progression_eval:** Confirmed running at 21:00 UTC
- **Iron condors:** DISABLED in current phase. Debit spreads only.
- **Calibration job:** Currently skipping with exit code 2 (insufficient data â€” expected until more paper trades accumulate)
- **Risk profile:** 70/100 — aggressive paper growth (8% base risk, compounding ON, 4 max trades)
- **RISK_MAX_SYMBOL_PCT=0.40** (paper phase â€” tighten to 0.30 at micro_live, 0.25 at live)
- **Alpaca live account:** Approved for Level 3 options trading (spreads, multi-leg)
- **Live trading:** Ready pending 4 consecutive green days in alpaca_paper phase

---

## Infrastructure

| Service | URL / Location |
|---|---|
| Backend (Railway) | https://be-production-48b1.up.railway.app |
| Frontend (Railway) | https://fe-production-d711.up.railway.app |
| Supabase project | etd1ladeorfgdmsopzmz.supabase.co |
| GitHub Actions | Fallback/manual dispatch only (APScheduler is primary) |

### Key Environment Variables (Railway backend)
- `TRADING_MODE` â€” `paper` / `micro_live` / `live`
- `TASK_NONCE_PROTECTION=1` â† must be set in prod
- `TASK_NONCE_FAIL_CLOSED_IN_PROD=1` â† must be set in prod
- `ALLOW_LEGACY_CRON_SECRET=0` â† must be set in prod
- `SCHEDULER_ENABLED=1` â† enables APScheduler (primary scheduler)
- `COMPOUNDING_MODE=true` — enables 8% base risk + 1.2x boost for micro tier
- `RISK_MAX_SYMBOL_PCT=0.40` — paper phase allows 40% in single name
- `RISK_MAX_DAILY_LOSS=0.08` — 8% daily loss cap ($40 on $500)
- `RISK_ENVELOPE_ENFORCE=1` (enabled 2026-04-16 — force-close blocking mode)
- `PROFIT_AGENT_RANKING=1` (enabled 2026-04-16 — dynamic weights applied during suggestions_open)
- `ORCHESTRATOR_ENABLED=1` (enabled 2026-04-16 — autonomous 7:30 AM CT boot check)

---

## Architecture (v4 â€” 16 Layers + 4 Managed Agents)

1. Market Data (Alpaca primary for options + equities, Polygon for reference only)
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
| Equity snapshots | Alpaca `/v2/stocks/snapshots` | Polygon `/v3/snapshot` |
| Daily bars (IV rank, trend) | Alpaca `/v2/stocks/bars` | Polygon `/v2/aggs` |
| Equity quotes (NBBO) | Alpaca `/v2/stocks/quotes/latest` | Polygon `/v2/last/nbbo` |
| Equity prev close | Alpaca `/v2/stocks/snapshots` (prev_daily_bar) | Polygon `/v2/aggs/prev` |
| Earnings dates | Polygon `/vX/reference/financials` | â€” |
| Historical contracts | Polygon `/v3/reference/options/contracts` | â€” |

---

## Daily Cron Pipeline (APScheduler â€” primary)

```
5:00 AM   calibration_update
7:30 AM   day_orchestrator (boot check)
8:00 AM   suggestions_close â†’ 8:15 paper_exit_evaluate (morning)
9:30-4:00 alpaca_order_sync (every 5 min) + intraday_risk_monitor (every 15 min)
11:00 AM  suggestions_open â†’ 11:30 paper_auto_execute
3:00 PM   paper_exit_evaluate (afternoon) â†’ 3:30 paper_mark_to_market
4:00 PM   daily_progression_eval â†’ 4:10 learning_ingest â†’ 4:20 paper_learning_ingest
4:30 PM   policy_lab_eval â†’ 4:45 post_trade_learning
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

- **GAP 1** â€” Canonical ranking metric: expected PnL after slippage/fees Ã· marginal risk, adjusted for correlation/concentration. Replace ALL other ranking objectives. â† DynamicWeightService lays groundwork; full implementation pending.
- **GAP 2** â€” EV-aware exit ranking: close worst marginal-EV positions first (replace `min_one` logic).
- **GAP 3** â€” Score/PoP/EV calibration against realized outcomes by strategy, regime, DTE, liquidity, earnings context. â† Self-Learning Agent now automates this via exponential decay calibration.
- **GAP 4** â€” Autotune: replace threshold mutation with walk-forward validation + promotion/demotion rules.
- **GAP 5** â€” Production security flags (set in Railway env, not code). â† Broker + policy lab auth fix deployed 2026-04-09.

---

## Promotion Path

```
paper â†’ micro_live ($500â€“$1K, Alpaca, 5 days) â†’ live ($2.5â€“$5K, 30 days) â†’ full automation
```

Gate to `micro_live`: 4 consecutive Alpaca paper green days (not internal fills).

---

## NEVER DO

- Count `internal_paper` execution_mode fills as green days â€” Alpaca fills only
- Enable iron condors during `alpaca_paper` phase
- Rebuild entire system prompt on every AI call (split static/dynamic)
- Start a new Claude Code session without `--continue` on this project
- Use ChatGPT mid-build â€” all architecture decisions live here; mixing tools creates drift
- Deploy without verifying `TASK_NONCE_PROTECTION=1` in Railway
- Touch intraday_risk_monitor.py or risk_alerts migration (Loss Agent is deployed and stable)
- Enable `RISK_ENVELOPE_ENFORCE=1` before 2026-04-13 (observation period)
- Enable `PROFIT_AGENT_RANKING=1` before 5 days of learning data exist
- Duplicate close-order logic â€” always use `PaperExitEvaluator._close_position()`

---

## Bugs Fixed (do not re-introduce)

- All-or-nothing leg pricing on MTM (if any leg fails to quote, skip entire position mark)
- `nearest_expiry` backfill required for exit conditions to work
- `paper_learning_ingest` must be in cron â€” not just manual trigger
- OCC symbol format for Alpaca order submission
- Internal fills miscounted as Alpaca fills in green day logic (fixed + reset 2026-04-04)
- Polygon options data empty (plan lacks quotes) â€” Alpaca now primary for options snapshots + chains (2026-04-08)
- MTM `_compute_position_value_from_snapshots` read `snap.get("bid")` instead of `snap.get("quote", {}).get("bid")` â€” fixed 2026-04-08
- 11 broker endpoints + 6 policy lab endpoints missing explicit `Depends(get_current_user)` â€” fixed 2026-04-09
- Deprecated `POST /tasks/iv/daily-refresh` stub accepting legacy X-Cron-Secret â€” removed 2026-04-09
- `calculate_portfolio_inputs()` was synchronous inside async optimizer endpoint â€” wrapped in run_in_executor 2026-04-10
- Close orders missing `position_intent` â€” Alpaca inferred `buy_to_open` instead of `buy_to_close`, rejecting ADBE/AVGO exits. Fixed: set `buy_to_close`/`sell_to_close` per leg when `position_id` is set (2026-04-10)
- Close orders on near-worthless spreads had negative `limit_price` (AMD: -1.53). Alpaca rejects limit â‰¤ 0. Fixed: clamp to 0.01 for close orders (2026-04-10)
- `paper_exit_evaluate` 3 PM run never fired â€” idempotency key `{date}-exit-evaluate-{user_id}` was same for 8:15 AM and 3:00 PM. Morning's `succeeded` record blocked afternoon. Fixed: key now includes UTC hour (2026-04-10)
- `LIVE_MANUAL_APPROVAL=true` is NOT wired into paper submission path
- Debit spread PoP used raw long-leg delta (0.60-0.65) instead of breakeven-adjusted delta (~0.45). Inflated EV by ~30%, causing negative-EV trades to appear positive. Fixed: interpolate between long/short deltas weighted by premium/width (2026-04-12)
- Intraday risk monitor only checked portfolio-level envelopes, not position-level stop losses. 7-hour gap between exit evaluations (8:15 AM to 3:00 PM) left positions unprotected. Fixed: evaluate_position_exit() now called every 15min in intraday monitor (2026-04-12) â€” `safety_checks.py` defines it but `paper_endpoints.py` and `paper_exit_evaluator.py` never call `stage_for_approval()`. Paper orders go directly to `submit_and_track()`. No fix needed.
- Intraday stop_loss=True was gated behind `RISK_ENVELOPE_ENFORCE` — position-level exits (stop_loss, expiration_day) were warn-only when the flag was 0. Fixed: position-level exits in `intraday_risk_monitor.py` section 5a now always execute; envelope flag only gates portfolio-level force-close (section 5b) (2026-04-13)
- `paper_auto_execute` had no symbol-level dedup — if the scanner generated a new suggestion for an already-held symbol, auto-execute would stage and fill it, doubling the position qty. Fixed: both non-cohort and per-cohort paths now reject suggestions for symbols with open positions (2026-04-13)
- `_close_position` multi-leg inversion read `leg.get("side")` but stored legs use `action` (from OptionLeg model). `side` returned None, so ALL close legs got `action: "buy"`, meaning both legs sent `buy_to_close`. Alpaca rejected: long leg needs `sell_to_close`. Fixed: read `leg.get("action") or leg.get("side")` then invert (2026-04-13)
- Close orders rejected with `held_for_orders` when a prior pending order locked the same contracts. Initial fix (symbols filter) missed MLEG orders because parent has symbol=None. Fixed: fetch ALL open orders and check leg symbols. Also: `_close_position` had no idempotency guard — every call created a new staged order, causing 100+ `needs_manual_review` orders when submission kept failing. Fixed: added idempotency check in `_close_position` itself (the canonical close path), checking for any non-terminal order including `needs_manual_review` (2026-04-15)
- Alpaca close orders filled successfully but paper_positions never marked as closed. `_commit_fill` only updated paper_orders and portfolio cash — never touched paper_positions. `_process_orders_for_user` also missed close fills because they had `position_id` set (not orphans) and were already status=filled (not in staged/working/partial query). Fixed: `poll_pending_orders` now detects close fills (position_id set) and calls `_close_position_on_fill()` which updates position to closed with realized P&L. Added reconciliation step to `alpaca_order_sync` as safety net. (2026-04-15)

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
- [x] Risk envelope wired into pre-entry and MTM (warn-only mode â€” log violations, no blocking)
- [x] Multi-strategy scan caching: bars, regime, chain fetched once per symbol, reused across strategy retries
- [x] Debit spread stop loss widened from 20% to 50% (was triggering on normal bid-ask noise with 25-45 DTE)
- [x] Scheduler heartbeat job + never_run alert escalation (ops_health_check now alerts on dead scheduler)
- [x] Calibration DTE-bucket segmentation: adjustments now computed per (strategy, regime, dte_bucket)
- [x] Risk envelope circuit breaker: auto-execute blocks new entries when envelope is breached (force-close still warn-only)
- [x] Alpaca primary for options data â€” Polygon fallback only (2026-04-08)
- [x] Security: explicit auth on all 17 broker + policy lab endpoints (2026-04-09)
- [x] Loss Minimization Agent: 15-min intraday risk monitor with force-close capability (2026-04-09)
- [x] Self-Learning Agent: post-trade calibration, drift detection, strategy health flagging (2026-04-10)
- [x] Profit Optimization Agent: dynamic weight loading from learned calibrations (2026-04-10)
- [x] Day Orchestrator Agent: boot check, missed job detection, chain status (2026-04-10)
- [x] Efficiency: async optimizer, V4 quality cache, condor EV memoization (2026-04-10)
- [x] Alpaca close order fixes: position_intent + negative limit_price clamp + exit-evaluate idempotency (2026-04-10)
- [x] Alpaca primary for equity data: snapshots, bars, quotes, prev close — Polygon fallback only (2026-04-10)
- [x] Time-scaled profit targets: 50% early → 25% late, replaces flat 35% (2026-04-11)
- [x] Sector field wired to positions for risk envelope concentration checks (2026-04-11)
- [x] Raw EV stored alongside calibrated EV — fixes self-referential calibration loop (2026-04-11)
- [x] Auto-retry failed_retryable jobs every 10min during market hours (2026-04-11)
- [x] Pass spot price to option_chain() — eliminates ~35 redundant API calls/scan (2026-04-11)
- [x] PoP fix: debit spread PoP now uses breakeven-adjusted delta, not raw long delta (2026-04-12)
- [x] Intraday stop losses: monitor now checks position-level exits every 15min (2026-04-12)
- [x] Cohort decision accuracy: policy_decisions now read + compared in policy_lab_eval (2026-04-12)
- [x] Baseline capital synced to actual Alpaca balance at micro_live promotion (2026-04-12)
- [x] MTM batch updates: position marks + EOD snapshots batched into single queries (2026-04-12)
- [x] Intraday stop loss fix: position-level exits decoupled from RISK_ENVELOPE_ENFORCE gate (2026-04-13)
- [x] Symbol-level dedup in paper_auto_execute: reject suggestions for already-held symbols (2026-04-13)
- [x] Pre-cancel conflicting Alpaca orders before close submission + idempotency fix (2026-04-13)
- [x] Risk envelope: switch force-close from warn-only to block mode (RISK_ENVELOPE_ENFORCE=1, 2026-04-16)
- [x] Enable PROFIT_AGENT_RANKING=1 — dynamic weight loading active (2026-04-16)
- [x] Enable ORCHESTRATOR_ENABLED=1 — autonomous Day Orchestrator (2026-04-16)
- [ ] GAP 1â€“2 implementation
- [ ] Micro-live test ($500 cap, separate portfolio)
- [ ] GAP 3â€“4 after data accumulates
- [ ] Full live automation

---

## Working Style

- Respond with exact SQL, exact Railway commands, exact file paths â€” no placeholders
- When fixing bugs: show the broken code, explain why it's wrong, show the fix
- When adding features: check GAP priority order before building new things
- Prefer minimal diffs over full rewrites
- Always check `job_runs` table before assuming a cron ran successfully

## Live State (auto-updated)
- **Phase:** alpaca_paper
- **Green days:** 0 (of 4 required) — 2026-04-15 was a red day (-$2,217 realized)
- **Last green:** 2026-04-03 (then reset 2026-04-04 due to internal-fill miscount)
- **Open positions:** 3 (AMD, AMZN, NFLX — all LONG_CALL_DEBIT_SPREAD, aggressive cohort, entered 2026-04-16 16:35 UTC)
- **Last updated:** 2026-04-16 17:00
