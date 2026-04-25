# Options Trading Companion

Automated options trading system: scans for opportunities, generates
risk-adjusted trade suggestions, executes paper and live via Alpaca,
and closes the learning loop via calibrated EV/PoP multipliers.

## Current Status

| Metric | Value |
|---|---|
| Phase | `micro_live` (since 2026-04-25 17:10:36Z, audit `82f1c294-19a4-4c66-8a68-0b0811ef5b24`) |
| Account | live Alpaca `211900084` |
| Starting capital | $500 (`v3_go_live_state.paper_baseline_capital`, audit `c9d87caf-24db-4f7f-842a-748620a5c84f`) |
| Open positions | 0 (AMZN closed 2026-04-25 15:56Z with realized_pl +$325.50, audit `b6229d5e-1543-4304-9ab1-6f37e0e869c8`) |
| Universe | 62 symbols (PR #804 added F, BAC, SOFI, T, KO, VZ on 2026-04-25) |
| Phase 2 contract | enforced — canonical 9-value `close_reason` enum + `close_path_required` CHECK |
| Source of truth | `go_live_progression` + `v3_go_live_state` + Alpaca `get_account()` |

For AI-session context, see `CLAUDE.md`. For day-to-day ops SQL and
queries, see the Observability section below.

## Operational Docs

| Doc | Purpose |
|---|---|
| [`docs/micro_live_config.md`](docs/micro_live_config.md) | $500 micro_live runbook, capital scaling rule, Steps A–G apply procedure |
| [`docs/pr6_observation_queries.md`](docs/pr6_observation_queries.md) | Q-CF, Q-CP, Q-Jobs queries — 48h Phase 2 observation window |
| [`docs/pr6_close_path_consolidation.md`](docs/pr6_close_path_consolidation.md) | Close-path rollback procedure if Phase 2 contract breaks |
| [`docs/data_providers_overview.md`](docs/data_providers_overview.md) | Alpaca/Polygon routing reference |
| [`docs/ops_verification_go_live.md`](docs/ops_verification_go_live.md) | Pre-flip verification checklist |

## Risk Profile

Live trades are sized by `SmallAccountCompounder` at
`packages/quantum/services/analytics/small_account_compounder.py:62-115`,
not by cohort `policy_config`. At $500 capital the account sits in the
**micro tier** (capital < $1k):

| Component | Value |
|---|---|
| Tier | micro (capital < $1k) |
| `base_risk_pct` | 0.08 (8%) |
| `score_mult` | 0.8 + (score − 50)/50 × 0.4, clamped [0.8, 1.2]. Score 50→0.80, 75→1.00, 85→1.08, 100→1.20 |
| `regime_mult` | 1.0 normal · 0.9 suppressed · 0.8 elevated · 0.5 shock |
| `compounding_mult` | 1.2 if `COMPOUNDING_MODE=true` AND tier ∈ {micro, small} AND score ≥ 80; else 1.0 |
| Defensive cap | when `COMPOUNDING_MODE=false` AND tier ∈ {micro, small}, `base_risk_pct` is overridden to 0.02 |
| Concentration limit | `RISK_MAX_SYMBOL_PCT=0.40` (Railway BE env) |
| Hard cap per trade | ~$50–60 at $500 capital, score 75–90, normal regime, compounding ON |

Effective risk per trade typically **8–12% of capital**. Worked example
at $500 + score 85 + normal + compounding ON:

```
final_risk_pct = 0.08 × 1.08 × 1.0 × 1.2 = 0.10368  (~10.4%)
risk_budget    = $500 × 0.10368 ≈ $52
```

Cohort `risk_multiplier` (1.08, 1.0, 1.2 in `policy_lab_cohorts`) is a
**separate parameter** that sizes shadow clones at
`packages/quantum/policy_lab/fork.py:196-201`, not live trades. See
CLAUDE.md → "Cohort architecture" for the two-layer split.

## Architecture

```
packages/quantum/          Python 3.11 / FastAPI backend
  services/                Core business logic
  jobs/handlers/           Scheduled task handlers
  brokers/                 Alpaca + Polygon clients
  risk/                    Risk envelope, sector mapping
  analytics/               Regime engine, canonical ranker, surrogates
  tests/                   ~254 pytest files (require Python 3.11)
apps/web/                  Next.js 14 frontend (dashboard)
supabase/migrations/       Postgres schema (84 migrations)
scripts/                   Signed task runner, one-off tools
.github/workflows/         CI + manual-dispatch workflows
```

| Component | Technology |
|---|---|
| Backend | Python 3.11, FastAPI, Pydantic v2 |
| Database | Supabase (managed Postgres) |
| Scheduling | APScheduler in-process (primary); GHA fallback |
| Broker | Alpaca (paper + live; Level 3 options) |
| Market Data | Hybrid — Alpaca primary for snapshot paths via `MarketDataTruthLayer`; Polygon direct (no fallback) for ~63 other call sites pending tiered phase-out (CLAUDE.md → "Polygon dependency status") |
| Frontend | Next.js 14, Shadcn UI |
| Deploy | Railway (BE, FE, worker, Redis) |

## 16 Architecture Layers + 4 Managed Agents

See `CLAUDE.md` for the full list. Headline:
- Layers: Market Data → Regime → Forecast → Capital Allocation → Optimizer →
  Execution → Risk → Learning → Automation → UI.
- Agents: Day Orchestrator (7:30 AM CT), Loss Minimization (every 15 min),
  Self-Learning (4:45 PM CT), Profit Optimization (apply_calibration during
  suggestions).

## Running Locally

Requires Python **3.11** exactly. The sentinel in
`packages/quantum/__init__.py` rejects Python 3.14+ because `qci-client`
lacks wheels for that version.

```bash
git clone https://github.com/BrightBoost-Tech/options-trading-companion.git
cd options-trading-companion

# Backend venv
cd packages/quantum
python3.11 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Env (copy + fill in)
cp .env.example .env
# Required for local dev: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY,
# ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_PAPER, POLYGON_API_KEY,
# TASK_SIGNING_KEYS
# Note: ALPACA_PAPER (BE/worker code) and ALPACA_PAPER_TRADE
# (alpaca-mcp-server) are different vars — both must agree.
# See CLAUDE.md → "Critical env var: paper-vs-live mode".

# Run API (from repo root)
cd ../..
uvicorn packages.quantum.api:app --reload --port 8000

# Frontend
cd apps/web
pnpm install
cp .env.example .env.local   # set NEXT_PUBLIC_SUPABASE_URL / _ANON_KEY
pnpm dev
```

## Deploying

Railway auto-deploys on push to `main`. Services:
- `BE`  — FastAPI + APScheduler
- `FE`  — Next.js
- `worker` — background jobs via RQ/Redis
- `Redis` — queue + cache

Env var discipline:
- BE, FE, worker have DISTINCT variable sets. Always verify which service
  you're changing (`railway link` to the right one first).
- Changes take effect on next deploy. No restart needed — Railway cycles
  the service automatically on env update.
- Rollback: Railway's deployment history → click a previous deploy →
  Redeploy. Takes ~90s.

### Supabase migrations

Supabase schema changes do NOT auto-apply on Railway deploy. A human
operator must apply each migration manually after the code merges
to `main`. Detailed procedure: **CLAUDE.md → "Migration Apply
Procedure"**.

In brief:
1. After merge, re-inspect the SQL file on `main`.
2. Apply via `mcp__supabase__apply_migration` (canonical) or
   Supabase Dashboard SQL editor.
3. Verify via constraint/column query.
4. Log the apply as a `risk_alerts` row with
   `alert_type='migration_apply'`.

Auto-apply wiring and drift reconciliation (329 divergent columns
vs migration history) are planned work — backlog #62. Not available
as of 2026-04-23.

## Daily Operations

Full cron pipeline lives in `packages/quantum/scheduler.py`. Key times
(America/Chicago):

```
5:00 AM  calibration_update
7:30 AM  day_orchestrator (boot check)
8:00 AM  suggestions_close → 8:15 paper_exit_evaluate (morning)
11:00 AM suggestions_open  → 11:30 paper_auto_execute
3:00 PM  paper_exit_evaluate (afternoon) → 3:30 paper_mark_to_market
4:00 PM  daily_progression_eval → 4:10 learning_ingest → 4:20 paper_learning_ingest
4:30 PM  policy_lab_eval → 4:45 post_trade_learning
5:00 PM  promotion_check

Intraday: alpaca_order_sync every 5 min (9-16 CT)
          intraday_risk_monitor every 15 min (9-16 CT)
          ops_health_check at :07, :37 (8-17 CT)
          scheduler_heartbeat every 30 min (8-17 CT)
```

Check job health:
```sql
SELECT job_name, status, finished_at
FROM job_runs
WHERE created_at::date = CURRENT_DATE
ORDER BY finished_at DESC;
```

## Observability

```sql
-- Phase + green-day status
SELECT current_phase, alpaca_paper_green_days, alpaca_paper_last_green_date
FROM go_live_progression;

-- Open positions — MUST match Alpaca get_all_positions() output
SELECT symbol, quantity, avg_entry_price, current_mark, unrealized_pl, status
FROM paper_positions WHERE status = 'open' ORDER BY created_at DESC;

-- Today's risk alerts
SELECT alert_type, severity, symbol, message, created_at
FROM risk_alerts
WHERE created_at > NOW() - INTERVAL '24 hours'
ORDER BY created_at DESC;

-- Calibration blob (per-segment multipliers are in JSONB `adjustments`)
SELECT computed_at, adjustments->'LONG_CALL_DEBIT_SPREAD:normal:0_21'
FROM calibration_adjustments ORDER BY computed_at DESC LIMIT 3;

-- Trade outcomes (filter excludes pre-2026-04-13 corrupted rows)
SELECT COUNT(*) FILTER (WHERE pnl_realized > 0) AS wins,
       COUNT(*) FILTER (WHERE pnl_realized < 0) AS losses,
       ROUND(AVG(pnl_realized), 2) AS avg_pnl
FROM learning_feedback_loops
WHERE outcome_type='trade_closed' AND created_at >= '2026-04-13';
```

## Testing

- **Python 3.11 is required.** The test suite uses import-time guards that
  fail on 3.14+. The `RuntimeError: Quantum stack requires Python 3.11 or
  3.12 due to qci-client compatibility.` message comes from the sentinel in
  `packages/quantum/__init__.py`.
- **Local:** `cd packages/quantum && pytest tests/` (from repo root:
  `pytest packages/quantum/tests/` with `PYTHONPATH=.`).
- **CI:** `.github/workflows/ci-tests.yml` runs on push + PR. No merge
  without green CI — this is a NEVER DO rule in CLAUDE.md.
- **Coverage:** `pytest --cov=packages/quantum --cov-report=term-missing`.
  The `.coveragerc` at the repo root configures source + excludes.
- When fixing a bug, include a regression test in the same PR.
- When removing production code, delete its tests in the same PR. Document
  in the PR description: "Deleted because [surface removed]. No kept
  surface exercised."
- When a test file covers both removed and retained surface, split the
  file before the removal PR.
- **Never add a new `@pytest.mark.skip`** without opening a tracking issue
  with unskip criteria, including the issue number in the reason string,
  and getting reviewer approval. Skip count must trend down over time.

### When a test fails locally

1. Confirm Python 3.11 (`python --version`).
2. Confirm venv matches `packages/quantum/requirements.txt`
   (`pip install -r packages/quantum/requirements.txt` inside the venv).
3. Run the single failing test with full output:
   `pytest packages/quantum/tests/test_X.py::TestClass::test_case -xvs`.
4. If failure references "Quantum stack requires…", env is incomplete —
   check `SUPABASE_URL`, `TASK_SIGNING_KEYS`, and other required env vars
   in `.env.example`. CI uses placeholder values inlined in the workflow;
   local may need real-ish values or explicit mocks.

## Adding a Feature

1. Branch from `main`: `git checkout -b feat/short-description`.
2. Update CLAUDE.md if your change affects: flags, env vars, NEVER DO rules,
   roadmap, or architecture.
3. Write the code + a regression test.
4. Confirm CI green.
5. Open PR → review → merge. No force-pushing to main.

## Common Issues

| Symptom | Cause | Fix |
|---|---|---|
| `needs_manual_review` orders piling up | Retry loop hit 42210000 on duplicate submit | Already fixed in PR #764 — poll path reconciles |
| `loss_weekly` at -190% on a normal week | Pre-83872db: garbage inputs to risk_envelope | Fixed — Alpaca-authoritative equity |
| Ghost positions (DB open, Alpaca empty) | Close orders stuck in `needs_manual_review` | PR #764 Fix A + new ghost_position_sweep |
| `paper_exit_evaluate` 3 PM run missing | Idempotency key collision with 8:15 AM | Fixed 2026-04-10 — key now includes hour |
| 3× position in same symbol same day | Scanner didn't see held positions | Fixed 2026-04-16 — `RANKER_PORTFOLIO_AWARE=1` |
| Close order `held_for_orders` rejection | Pending order on same contracts | Pre-cancel logic ships with PR #764 parent commits |
| Calibration multipliers look wild | pre-2026-04-13 corrupted `pnl_realized` rows | Fixed in PR #3 — date floor filter |

Full chronology in CLAUDE.md `Bugs Fixed` section.

## Project Layout

```
.
├── apps/web/                      # Next.js 14 frontend
├── packages/quantum/              # Python/FastAPI backend
│   ├── api.py                     # FastAPI root
│   ├── scheduler.py               # APScheduler job registrations
│   ├── brokers/                   # Alpaca + Polygon clients
│   ├── services/                  # Business logic
│   ├── jobs/handlers/             # Scheduled task handlers
│   ├── risk/risk_envelope.py      # Portfolio-level envelope
│   ├── analytics/                 # Regime, ranker, surrogates
│   └── tests/                     # pytest suite
├── supabase/migrations/           # DDL — NEVER modify existing; only add
├── scripts/run_signed_task.py     # HMAC-signed task runner for GHA
├── .github/workflows/
│   ├── ci-tests.yml               # pytest + coverage on every PR
│   ├── trading_tasks.yml          # Manual dispatch for task debugging
│   └── security_v4_smoketest.yml  # Signing smoke test
├── CLAUDE.md                      # AI context (loaded every turn)
└── README.md                      # This file
```

## Links

- Supabase project: https://supabase.com/dashboard/project/etdlladeorfgdmsopzmz
- Railway project: `empowering-commitment` (services: BE, FE, worker, Redis)
- Alpaca paper dashboard: https://app.alpaca.markets/paper/dashboard/overview
- Polygon.io dashboard: https://polygon.io/dashboard
- Production BE: https://be-production-48b1.up.railway.app
- Production FE: https://fe-production-d711.up.railway.app
