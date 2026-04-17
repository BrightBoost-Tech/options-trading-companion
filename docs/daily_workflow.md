# Daily Workflow: The Scheduled Pipeline

This document describes the full daily pipeline. All times America/Chicago.
Primary scheduler is APScheduler in `packages/quantum/scheduler.py`; GitHub
Actions (`.github/workflows/trading_tasks.yml`) is manual-dispatch only.

## Full schedule

| Time | Task | Purpose |
|---|---|---|
| 05:00 | `calibration_update` | Recompute EV/PoP multipliers from outcomes |
| 07:30 | `day_orchestrator` | Boot check, missed-job detection, chain status |
| 08:00 | `suggestions_close` | Generate exit suggestions for open positions |
| 08:15 | `paper_exit_evaluate` (morning) | Overnight gap protection exits |
| 09:30–16:00 | `alpaca_order_sync` every 5m | Poll Alpaca for fills + reconciliation |
| 09:30–16:00 | `intraday_risk_monitor` every 15m | Portfolio envelope + per-position stops |
| 11:00 | `suggestions_open` | Generate entry suggestions |
| 11:30 | `paper_auto_execute` | Execute top suggestions through Alpaca |
| 15:00 | `paper_exit_evaluate` (afternoon) | Condition-based exits |
| 15:30 | `paper_mark_to_market` | Refresh position marks for EOD snapshot |
| 16:00 | `daily_progression_eval` | Green-day evaluation |
| 16:10 | `learning_ingest` | Ingest executed trades |
| 16:20 | `paper_learning_ingest` | Paper outcomes → learning_feedback_loops |
| 16:30 | `policy_lab_eval` | Cohort comparison |
| 16:45 | `post_trade_learning` | Self-Learning Agent (closes feedback loop) |
| 17:00 | `promotion_check` | Detect stuck phase transitions |
| 08:00–17:00, :07/:37 | `ops_health_check` | System health + scheduler-death detection |
| 08:00–17:00, every 30m | `scheduler_heartbeat` | Liveness pings to job_runs |

## How it works (end-to-end)

### Morning (07:30 – 11:00)

1. `day_orchestrator` at 07:30 verifies overnight jobs ran, checks option chain
   freshness, and writes an `agent_sessions` row.
2. `suggestions_close` at 08:00 runs the morning cycle on open positions,
   computing exit thresholds via the canonical ranker.
3. `paper_exit_evaluate` at 08:15 acts on any overnight-hit exit conditions.

### Midday (11:00 – 15:00)

4. `suggestions_open` at 11:00 scans the universe, runs the full optimizer,
   applies calibration (EV/PoP multipliers from `calibration_adjustments`),
   and writes to `trade_suggestions`.
5. `paper_auto_execute` at 11:30 submits top-ranked suggestions through the
   `paper_endpoints` submission path → Alpaca.
6. Every 5 minutes, `alpaca_order_sync` polls Alpaca for fills and updates
   `paper_orders` + `paper_positions`. Includes orphan-repair + ghost sweep.
7. Every 15 minutes, `intraday_risk_monitor` runs the risk envelope (greeks,
   concentration, loss, stress) + per-position stop-loss and expiration checks.

### Afternoon (15:00 – 17:00)

8. `paper_exit_evaluate` at 15:00 runs the afternoon exit cycle.
9. `paper_mark_to_market` at 15:30 refreshes marks and writes
   `paper_eod_snapshots` rows.
10. `daily_progression_eval` at 16:00 evaluates whether today was a green
    day (realized PnL > 0) and increments `go_live_progression.alpaca_paper_
    green_days`.
11. Learning chain (16:10 → 16:45): ingest trades, compute calibration,
    run Self-Learning Agent.
12. `promotion_check` at 17:00 alerts if the phase transition is stuck.

## Auth

All scheduled tasks use v4 HMAC-signed requests. The scheduler calls
`/internal/tasks/...` or `/tasks/...` endpoints with a signed `X-Task-*`
header set (`TASK_SIGNING_KEYS` on Railway). See
`packages/quantum/security/task_signing_v4.py`.

## Manual dispatch (debugging)

Go to the GitHub Actions tab → Trading Tasks (v4 Signed) workflow →
Run workflow → pick a task from the dropdown. Supports `--skip-time-gate`,
`--dry-run`, and custom payload JSON.

## Troubleshooting

| Symptom | Check |
|---|---|
| Suggestions not firing | `job_runs` table for today's `suggestions_open` row |
| Exits not firing | `job_runs` for `paper_exit_evaluate`; ensure both 08:15 and 15:00 ran |
| Orders stuck in `needs_manual_review` | Fixed in PR #764; check `broker_response` |
| Green day not counted | `daily_progression_eval` result; confirm Alpaca fills not internal |
| `intraday_risk_monitor` latency high | See `ops_health_check` tripwire |

## File reference

| File | Purpose |
|---|---|
| `packages/quantum/scheduler.py` | APScheduler registration + signed-request fire |
| `packages/quantum/public_tasks.py` | `/tasks/...` endpoint handlers |
| `packages/quantum/jobs/handlers/*.py` | Individual task implementations |
| `packages/quantum/services/workflow_orchestrator.py` | Core suggestion pipeline |
| `.github/workflows/trading_tasks.yml` | Manual dispatch UI (no cron) |
