# Options Trading Companion â€” Project Context
# Loaded by Claude Code on EVERY turn. Keep this current.

---

## Identity & Repo

- **Repo:** BrightBoost-Tech/options-trading-companion
- **Owner User ID:** 75ee12ad-b119-4f32-aeea-19b4ef55d587
- **Stack:** Python/FastAPI backend (`packages/quantum`) Â· Next.js frontend Â· Supabase Postgres Â· Railway deploy Â· GitHub Actions cron Â· Polygon.io market data Â· Alpaca broker API

---

## Current Phase

- **Trading mode:** `alpaca_paper`
- **Promotion target:** 4 consecutive green days through Alpaca â†’ advances to `micro_live`
- **Green days so far:** Reset to 0 on 2026-04-04 (internal fills were miscounted; audit trail logged)
- **Iron condors:** DISABLED in current phase. Debit spreads only.
- **Calibration job:** Currently skipping with exit code 2 (insufficient data â€” expected until more paper trades accumulate)

---

## Infrastructure

| Service | URL / Location |
|---|---|
| Backend (Railway) | https://be-production-48b1.up.railway.app |
| Frontend (Railway) | https://fe-production-d711.up.railway.app |
| Supabase project | etd1ladeorfgdmsopzmz.supabase.co |
| GitHub Actions | Cron scheduler for all automated jobs |

### Key Environment Variables (Railway backend)
- `TRADING_MODE` â€” `paper` / `micro_live` / `live`
- `TASK_NONCE_PROTECTION=1` â† must be set in prod
- `TASK_NONCE_FAIL_CLOSED_IN_PROD=1` â† must be set in prod
- `ALLOW_LEGACY_CRON_SECRET=0` â† must be set in prod
- `PLAID_ENV` â€” remove/ignore; Plaid is no longer relevant

---

## Architecture (v4 â€” 16 Layers)

1. Market Data (Polygon.io)
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

---

## Daily Cron Pipeline (GitHub Actions)

```
suggestions_open â†’ paper_auto_execute â†’ paper_exit_evaluator
â†’ paper_mark_to_market â†’ paper_learning_ingest â†’ validation_eval
```

- `paper_learning_ingest` MUST run after exits close each day or the learning view stalls
- All jobs deployed on commit hash tracked in Railway

---

## Key Database Tables

| Table | Purpose |
|---|---|
| `paper_positions` | Open/closed paper positions |
| `paper_orders` | Order fills (execution_mode: internal_paper or alpaca_paper) |
| `go_live_progression` | Current phase + green days count |
| `go_live_progression_log` | Audit trail of phase events |
| `v3_go_live_state` | Legacy state; `paper_consecutive_passes` |
| `policy_lab_cohorts` | 3 active cohorts (conservative / moderate / aggressive) |
| `learning_trade_outcomes_v3` | Realized P&L for checkpoint evaluation |
| `paper_eod_snapshots` | Daily MTM marks per position |
| `job_runs` | Railway job execution log |

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

-- Cohort decisions today
SELECT cohort_id, decision, COUNT(*) FROM policy_decisions
WHERE created_at::date = CURRENT_DATE GROUP BY cohort_id, decision;
```

---

## 5 Open Code Gaps (implement in this order)

- **GAP 1** â€” Canonical ranking metric: expected PnL after slippage/fees Ã· marginal risk, adjusted for correlation/concentration. Replace ALL other ranking objectives.
- **GAP 2** â€” EV-aware exit ranking: close worst marginal-EV positions first (replace `min_one` logic).
- **GAP 3** â€” Score/PoP/EV calibration against realized outcomes by strategy, regime, DTE, liquidity, earnings context. â† needs more data first.
- **GAP 4** â€” Autotune: replace threshold mutation with walk-forward validation + promotion/demotion rules.
- **GAP 5** â€” Production security flags (set in Railway env, not code).

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
- Risk envelope force_close is still warn-only in paper_mark_to_market.py — switch to block mode after 2026-04-13 (one week from deploy)

---

## Bugs Fixed (do not re-introduce)

- All-or-nothing leg pricing on MTM (if any leg fails to quote, skip entire position mark)
- `nearest_expiry` backfill required for exit conditions to work
- `paper_learning_ingest` must be in cron â€” not just manual trigger
- OCC symbol format for Alpaca order submission
- Internal fills miscounted as Alpaca fills in green day logic (fixed + reset 2026-04-04)

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
- [ ] Risk envelope: switch force-close from warn-only to block mode after 1 week observation
- [ ] GAP 1â€”2 implementation
- [ ] Micro-live test ($500 cap, separate portfolio)
- [ ] GAP 3â€”4 after data accumulates
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
- **Green days:** 0
- **Last green:** 
- **Open positions:** 4
- **Last updated:** 2026-04-06 12:37
