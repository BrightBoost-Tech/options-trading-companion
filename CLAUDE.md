# Options Trading Companion — Project Context
# Loaded by Claude Code on EVERY turn. Keep this current.

---

## Identity & Repo

- **Repo:** BrightBoost-Tech/options-trading-companion
- **Owner User ID:** 75ee12ad-b119-4f32-aeea-19b4ef55d587
- **Stack:** Python/FastAPI backend (`packages/quantum`) · Next.js frontend · Supabase Postgres · Railway deploy · GitHub Actions cron · Polygon.io market data · Alpaca broker API

---

## Current Phase

- **Trading mode:** `alpaca_paper`
- **Promotion target:** 4 consecutive green days through Alpaca → advances to `micro_live`
- **Green days so far:** Reset to 0 on 2026-04-04 (internal fills were miscounted; audit trail logged)
- **Iron condors:** DISABLED in current phase. Debit spreads only.
- **Calibration job:** Currently skipping with exit code 2 (insufficient data — expected until more paper trades accumulate)

---

## Infrastructure

| Service | URL / Location |
|---|---|
| Backend (Railway) | https://be-production-48b1.up.railway.app |
| Frontend (Railway) | https://fe-production-d711.up.railway.app |
| Supabase project | etd1ladeorfgdmsopzmz.supabase.co |
| GitHub Actions | Cron scheduler for all automated jobs |

### Key Environment Variables (Railway backend)
- `TRADING_MODE` — `paper` / `micro_live` / `live`
- `TASK_NONCE_PROTECTION=1` ← must be set in prod
- `TASK_NONCE_FAIL_CLOSED_IN_PROD=1` ← must be set in prod
- `ALLOW_LEGACY_CRON_SECRET=0` ← must be set in prod
- `PLAID_ENV` — remove/ignore; Plaid is no longer relevant

---

## Architecture (v4 — 16 Layers)

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
suggestions_open → paper_auto_execute → paper_exit_evaluator
→ paper_mark_to_market → paper_learning_ingest → validation_eval
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

- **GAP 1** — Canonical ranking metric: expected PnL after slippage/fees ÷ marginal risk, adjusted for correlation/concentration. Replace ALL other ranking objectives.
- **GAP 2** — EV-aware exit ranking: close worst marginal-EV positions first (replace `min_one` logic).
- **GAP 3** — Score/PoP/EV calibration against realized outcomes by strategy, regime, DTE, liquidity, earnings context. ← needs more data first.
- **GAP 4** — Autotune: replace threshold mutation with walk-forward validation + promotion/demotion rules.
- **GAP 5** — Production security flags (set in Railway env, not code).

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

---

## Bugs Fixed (do not re-introduce)

- All-or-nothing leg pricing on MTM (if any leg fails to quote, skip entire position mark)
- `nearest_expiry` backfill required for exit conditions to work
- `paper_learning_ingest` must be in cron — not just manual trigger
- OCC symbol format for Alpaca order submission
- Internal fills miscounted as Alpaca fills in green day logic (fixed + reset 2026-04-04)

---

## Roadmap Status

- [x] 10-day paper test complete
- [x] Policy Lab (3 cohorts active)
- [x] Alpaca paper execution live
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
