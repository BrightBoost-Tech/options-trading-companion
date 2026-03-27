# Options Trading Companion

Automated options trading platform that scans for opportunities, generates trade suggestions with risk-adjusted ranking, manages paper and live execution through Alpaca, and learns from outcomes via calibration feedback loops.

## Current Status

| Metric | Value |
|--------|-------|
| Phase | Alpaca Paper Testing |
| Gate to next phase | 4 positive (green) trading days |
| Internal paper test | Completed (10 consecutive passes) |
| Next milestone | Micro Live (small real-money trades via Alpaca) |
| Source of truth | `go_live_progression` table |

## Architecture

```
packages/quantum/          Python / FastAPI backend
supabase/migrations/       Postgres schema (60+ tables)
.github/workflows/         GitHub Actions scheduling
apps/web/                  Next.js frontend (dashboard)
scripts/                   Task runners, deployment tools
```

| Component | Technology |
|-----------|-----------|
| Backend | Python 3.12, FastAPI, Pydantic v2 |
| Database | Supabase (managed Postgres) |
| Scheduling | GitHub Actions cron (`trading_tasks.yml`) |
| Broker | Alpaca (paper + live) |
| Market Data | Polygon.io |
| Frontend | Next.js 14, Shadcn UI |

## Progression System

Three-phase state machine in `go_live_progression`:

```
Phase 1: alpaca_paper
  Execute via Alpaca paper trading API.
  Gate: 4 positive trading days (realized PnL > $0).
  Auto-promotes to Phase 2 when gate is met.

Phase 2: micro_live
  Execute via Alpaca live API with sizing caps.
  Gate: Manual promotion (automatic gate TBD).

Phase 3: full_auto
  Full position sizing, fully automated.
```

A **positive day** = total realized PnL from all positions closed that Chicago-timezone trading day > $0.

`ops_control.paused = true` is the **universal kill switch**. When paused, neither the autopilot nor the exit evaluator will execute, regardless of progression phase.

Source of truth: `ProgressionService` in `packages/quantum/services/progression_service.py`.

## Scheduled Jobs

All times are Chicago (CDT in summer, CST in winter). Both UTC offsets are scheduled in the cron; a Python time-gate ensures only the correct one runs.

### Overnight

| Time | Job | Purpose |
|------|-----|---------|
| 3:30 AM | `learning_ingest` | Nightly catch-up of executed trade outcomes (Tue-Sat) |
| 5:00 AM | `calibration_update` | Recompute EV/PoP calibration adjustments (Tue-Sat) |
| 5:30 AM | `walk_forward_autotune` | Weekly walk-forward parameter optimization (Mon only) |

### Morning

| Time | Job | Purpose |
|------|-----|---------|
| 8:00 AM | `suggestions_close` | Generate exit suggestions for existing positions |
| 8:15 AM | `paper_exit_evaluate` | Overnight gap protection exit check |

### Midday

| Time | Job | Purpose |
|------|-----|---------|
| 11:00 AM | `suggestions_open` | Scan for new entry opportunities |
| 11:30 AM | `paper_auto_execute` | Execute top-ranked suggestions |

### Afternoon

| Time | Job | Purpose |
|------|-----|---------|
| 3:00 PM | `paper_exit_evaluate` | Condition-based exits before close |
| 3:30 PM | `paper_mark_to_market` | Refresh position marks from live quotes |

### End of Day

| Time | Job | Purpose |
|------|-----|---------|
| 4:00 PM | `daily_progression_eval` | Sum closed PnL, update green day counter |
| 4:10 PM | `learning_ingest` | Ingest executed trades into learning |
| 4:20 PM | `paper_learning_ingest` | Map paper outcomes to suggestions for calibration |
| 4:30 PM | `policy_lab_eval` | Evaluate Policy Lab cohort performance |

### Continuous

| Cadence | Job | Purpose |
|---------|-----|---------|
| Every 30 min | `ops_health_check` | Monitor job health, data freshness, alerts |

### Deprecated (disabled, not deleted)

| Job | Replaced by |
|-----|-------------|
| `validation_eval` | `daily_progression_eval` |
| `validation_init_window` | Removed (not needed) |
| `validation_preflight` | Removed (not needed) |

## Key Tables

### Trading Pipeline

| Table | Purpose |
|-------|---------|
| `trade_suggestions` | Scored opportunities with EV, PoP, `risk_adjusted_ev` |
| `paper_orders` | Staged and executed orders (staged -> submitted -> filled) |
| `paper_positions` | Open and closed positions with realized PnL |
| `paper_portfolios` | Portfolio cash balance and net liquidation |

### Progression

| Table | Purpose |
|-------|---------|
| `go_live_progression` | Current phase + green day gate (one row per user) |
| `go_live_progression_log` | Append-only audit trail of green days and promotions |

### Learning & Calibration

| Table | Purpose |
|-------|---------|
| `learning_feedback_loops` | Predicted vs realized outcomes |
| `calibration_adjustments` | Cached EV/PoP multipliers per strategy/regime |
| `autotune_history` | Walk-forward parameter evaluation audit trail |

### Operations

| Table | Purpose |
|-------|---------|
| `ops_control` | System-wide kill switch (`paused`, `mode`) |
| `job_runs` | Job execution history and idempotency |
| `task_nonces` | Replay protection for signed task requests |

### Policy Lab

| Table | Purpose |
|-------|---------|
| `policy_lab_cohorts` | Cohort definitions with policy configs |
| `policy_decisions` | Per-suggestion accept/reject decisions with features snapshot |
| `policy_lab_daily_results` | Daily PnL and utility per cohort |

### Deprecated (read-only archive)

| Table | Replaced by |
|-------|-------------|
| `v3_go_live_state` | `go_live_progression` |
| `v3_go_live_runs` | `go_live_progression_log` |
| `v3_go_live_journal` | `go_live_progression_log` |

## Environment Variables

### Required (startup blocks without these)

| Variable | Purpose |
|----------|---------|
| `SUPABASE_JWT_SECRET` | JWT verification |
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL |
| `SUPABASE_ANON_KEY` | Supabase anonymous key |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase service role key |
| `ENCRYPTION_KEY` | Fernet key for token encryption |
| `POLYGON_API_KEY` | Market data (required in production) |

Generate encryption key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

### Broker (Alpaca)

| Variable | Default | Purpose |
|----------|---------|---------|
| `ALPACA_API_KEY` | none | Alpaca API key |
| `ALPACA_SECRET_KEY` | none | Alpaca secret key |
| `ALPACA_PAPER` | `"true"` | Use paper trading API |
| `EXECUTION_MODE` | `"internal_paper"` | Order routing: `internal_paper`, `alpaca_paper`, `alpaca_live` |
| `LIVE_ENABLED` | `""` | Must be `"true"` for `alpaca_live` mode |

### Security

| Variable | Default | Purpose |
|----------|---------|---------|
| `TASK_SIGNING_KEYS` | none | HMAC keys for signed task requests (`kid:secret` format) |
| `TASK_NONCE_PROTECTION` | `"1"` | Replay protection (enabled by default) |
| `TASK_NONCE_FAIL_CLOSED_IN_PROD` | `"1"` | Reject on nonce store failure in prod |
| `ALLOW_LEGACY_CRON_SECRET` | `"0"` | Legacy auth bypass (disabled by default) |
| `ENABLE_DEV_AUTH_BYPASS` | `"0"` | **CRITICAL**: never enable in production |
| `APP_ENV` | `"development"` | Set to `"production"` for prod hardening |

### Feature Flags

| Flag | Default | Purpose |
|------|---------|---------|
| `PAPER_AUTOPILOT_ENABLED` | `"0"` | Enable automated paper trade execution |
| `CANONICAL_RANKING_ENABLED` | `"1"` | Use `risk_adjusted_ev` for entry/exit ranking |
| `EXIT_RANKING_ENABLED` | `"1"` | Rank triggered exits by marginal value |
| `PDT_PROTECTION_ENABLED` | `"0"` | Pattern day trader guard (3 day-trades/5 days) |
| `CALIBRATION_ENABLED` | `"0"` | Apply calibration multipliers to EV/PoP |
| `AUTOTUNE_ENABLED` | `"0"` | Walk-forward parameter optimization |
| `AUTOTUNE_AUTOPROMOTE` | `"0"` | Auto-apply promoted parameter changes |
| `POLICY_LAB_ENABLED` | `""` | Multi-cohort policy testing |

### Thresholds

| Variable | Default | Purpose |
|----------|---------|---------|
| `MIN_EDGE_AFTER_COSTS` | `"15"` | Minimum net edge ($) after fees to take a trade |
| `PAPER_AUTOPILOT_MAX_TRADES_PER_DAY` | `"3"` | Max new positions per day |
| `PAPER_AUTOPILOT_CLOSE_POLICY` | `"close_all"` | Position close policy |
| `PDT_MAX_DAY_TRADES` | `"3"` | Day-trade limit for PDT compliance |
| `MIN_CALIBRATION_TRADES` | `"20"` | Min outcomes before calibration is active |

## How to Run Locally

```bash
# Clone
git clone https://github.com/BrightBoost-Tech/options-trading-companion.git
cd options-trading-companion

# Backend
cd packages/quantum
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Set env vars
cp .env.example .env  # edit with your Supabase + Polygon keys

# Run API server
uvicorn packages.quantum.api:app --reload --port 8000

# Run job worker (separate terminal)
python -m packages.quantum.jobs.worker
```

Requires Python 3.11 or 3.12 (`qci-client` is not available for 3.14+).

**Windows**: Run `start.bat` from the repo root. See `STARTUP.md` for details.

**API docs**: `http://127.0.0.1:8000/docs`

### Authentication (Local Dev)

When `APP_ENV != production`, use header: `X-Test-Mode-User: <UUID>`

Default test user: `75ee12ad-b119-4f32-aeea-19b4ef55d587`

## How to Deploy

- **Backend**: Railway (auto-deploys from `main`)
- **Database**: Supabase (managed Postgres)
- **Scheduling**: GitHub Actions (`trading_tasks.yml` fires signed HTTP requests to Railway)
- **Migrations**: `supabase db push` or Supabase Dashboard SQL editor

After adding new migration columns, run in the SQL editor:
```sql
NOTIFY pgrst, 'reload schema';
```
This refreshes PostgREST's schema cache immediately so new columns are accessible via the API.

## Key Design Decisions

- **Canonical ranking**: `risk_adjusted_ev = expected_pnl_after_costs / (marginal_risk * concentration_penalty)` is the single metric for entry ranking, exit priority, and execution ordering.
- **Debit-aware exits**: Exit conditions detect debit vs credit spreads via strategy name or position direction. Debit spreads profit when the spread widens; credit spreads profit when premium decays.
- **Smooth risk floor**: Small accounts get `max(equity * 2%, $5)` as minimum per-trade risk instead of a hard $50 floor.
- **PDT guard**: Accounts under $25K limited to 3 day-trades per 5 business days. Emergency stops (loss > 80% of entry) override the PDT limit.
- **Exit ranking**: When multiple exits trigger simultaneously, they're ranked by priority (emergency > stop_loss > DTE > target_profit), each sorted by marginal value. PDT budget is consumed in ranked order.
- **Two-step execution**: Orders are staged (with TCM cost estimate), then filled. This decouples order intent from market data freshness.
- **Policy Lab cohorts**: Multiple risk policies (aggressive, neutral, conservative) run simultaneously on the same opportunity set for A/B testing.
- **ops_control kill switch**: Single row with `paused` boolean. When true, autopilot and exit evaluator return immediately.
- **Chicago timezone**: All trading-day boundaries use `America/Chicago`. Cron fires both CDT and CST offsets; Python time-gate discards the wrong one.
- **Min-edge filter**: Trades with `EV - fees - slippage < $15` are blocked at both creation time (orchestrator) and execution time (autopilot), preventing fee-dominated trades on small accounts.

## Deprecated Systems

These are archived and no longer written to. Do not revive them.

| System | Replaced by | Reason |
|--------|-------------|--------|
| `v3_go_live_state` (20+ columns) | `go_live_progression` | Single counter replaces 2800-line validation service |
| `paper_streak_days`, `paper_green_days` | `alpaca_paper_green_days` | One counter is sufficient |
| `paper_checkpoint_*`, `paper_fail_fast_*` | Removed | Not needed for 4-green-day gate |
| `validation_eval` job | `daily_progression_eval` | Simpler, single-table evaluation |
| `validation_init_window`, `validation_preflight` | Removed | Not needed for daily tracking |
| Old `strategy_autotune` (threshold mutation) | `walk_forward_autotune` | No out-of-sample validation in old system |
| Plaid integration | Alpaca | Alpaca provides positions, balances, execution |

---

*Private use only.*
