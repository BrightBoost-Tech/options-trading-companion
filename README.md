# Options Trading Companion

Personal options trading companion with AI-powered scouting, backtesting, and go-live validation guardrails.

## Architecture

| Component | Location | Description |
|-----------|----------|-------------|
| **Frontend** | `apps/web/` | Next.js 14 + Shadcn UI, runs on `http://localhost:3000` |
| **Backend** | `packages/quantum/` | FastAPI Python service for optimization, market data, validation. Runs on `http://127.0.0.1:8000` |
| **Database** | `supabase/` | PostgreSQL via Supabase with migrations |
| **Infra** | `infra/` | Deployment scripts and env checks |

API Documentation (Swagger): `http://127.0.0.1:8000/docs`

## Prerequisites

- Node.js 18+ and pnpm 8+
- Python 3.9+
- Supabase CLI (for local database)

## Quickstart

```bash
# 1. Install Node dependencies
pnpm install

# 2. Start Supabase (local PostgreSQL)
supabase start
supabase db reset  # First time or after schema changes

# 3. Start Backend
cd packages/quantum
python -m venv venv
# Mac/Linux: source venv/bin/activate
# Windows: venv\Scripts\activate
pip install -r requirements.txt
./run_server.sh  # or .\run_server.bat on Windows

# 4. Start Frontend (new terminal)
pnpm --filter "./apps/web" dev
```

**Windows One-Click:** Run `start.bat` from the repo root to launch both backend and frontend.

## Environment Variables

### Root / Frontend (`.env` or `.env.local`)

Copy `.env.example` to `.env`:

| Variable | Purpose |
|----------|---------|
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase API URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase anon/public key |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase service role key (secret) |

### Backend (`packages/quantum/.env`)

Copy `packages/quantum/.env.example`:

| Variable | Purpose |
|----------|---------|
| `SUPABASE_URL` | Supabase API URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role key for DB access |
| `ENCRYPTION_KEY` | Fernet key for credential encryption |
| `APP_ENV` | `development` enables test-mode auth |
| `TASK_SIGNING_SECRET` | Secret for internal task endpoints |
| `POLYGON_API_KEY` | (Optional) Polygon.io market data |
| `PLAID_*` | (Optional) Plaid integration |

Generate encryption key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

## Core Commands

### Backend (from `packages/quantum/`)

```bash
# Run API server
./run_server.sh  # or .\run_server.bat

# Run tests
python -m pytest tests/ -q

# Run specific test file
python -m pytest tests/test_historical_training_loop.py -v
```

### Frontend (from repo root)

```bash
pnpm --filter "./apps/web" dev    # Development
pnpm --filter "./apps/web" build  # Production build
pnpm --filter "./apps/web" lint   # Lint
```

### Monorepo

```bash
pnpm dev      # Start all apps in parallel
pnpm build    # Build all packages and apps
pnpm test     # Run vitest
pnpm lint     # ESLint
```

## Historical Validation / Backtesting

The validation system tests trading strategies against historical data before going live.

### API Endpoint

```bash
POST /validation/run
```

### Example: Run Historical Validation (Stock)

```bash
curl -X POST "http://127.0.0.1:8000/validation/run" \
  -H "X-Test-Mode-User: 75ee12ad-b119-4f32-aeea-19b4ef55d587" \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "historical",
    "historical": {
      "symbol": "SPY",
      "window_days": 90,
      "concurrent_runs": 3,
      "goal_return_pct": 10.0
    }
  }'
```

### Example: Run Historical Validation (Options)

```bash
curl -X POST "http://127.0.0.1:8000/validation/run" \
  -H "X-Test-Mode-User: 75ee12ad-b119-4f32-aeea-19b4ef55d587" \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "historical",
    "historical": {
      "symbol": "SPY",
      "instrument_type": "option",
      "option_right": "call",
      "option_dte": 60,
      "option_moneyness": "itm_5pct",
      "use_rolling_contracts": true,
      "strict_option_mode": true,
      "segment_tolerance_pct": 1.5,
      "window_days": 90,
      "concurrent_runs": 3,
      "goal_return_pct": 10.0
    }
  }'
```

### Training Mode (Self-Learning Loop)

```bash
curl -X POST "http://127.0.0.1:8000/validation/run" \
  -H "X-Test-Mode-User: 75ee12ad-b119-4f32-aeea-19b4ef55d587" \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "historical",
    "historical": {
      "symbol": "SPY",
      "instrument_type": "option",
      "train": true,
      "train_target_streak": 3,
      "train_max_attempts": 20
    }
  }'
```

## Authentication

### Production
- Header: `Authorization: Bearer <SUPABASE_JWT>`

### Development (when `APP_ENV != production`)
- Header: `X-Test-Mode-User: <UUID>`
- Default test user: `75ee12ad-b119-4f32-aeea-19b4ef55d587`

## Task Endpoints

Protected by `X-Cron-Secret` header:

| Endpoint | Purpose |
|----------|---------|
| `/tasks/morning-brief` | Morning exit logic |
| `/tasks/midday-scan` | Scanner and sizing |
| `/tasks/weekly-report` | Weekly performance |
| `/tasks/universe/sync` | Update scanner universe |

## Database

Migrations in `supabase/migrations/`. Apply with:

```bash
supabase db reset  # Warning: wipes local data
```

## Repo Structure

```
options-trading-companion/
├── apps/
│   └── web/              # Next.js frontend
├── packages/
│   └── quantum/          # FastAPI backend
│       ├── services/     # Core business logic
│       ├── jobs/         # Background job handlers
│       ├── tests/        # Pytest tests
│       └── api.py        # Main API routes
├── supabase/
│   └── migrations/       # Database migrations
├── infra/
│   └── scripts/          # Deployment helpers
├── docs/                 # Documentation
├── scripts/              # Dev scripts
│   └── win/              # Windows launchers
└── .github/
    └── workflows/        # CI/CD
```

## Troubleshooting

**Backend won't start:**
- Missing `ENCRYPTION_KEY` in `packages/quantum/.env`
- Generate with: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

**401 on task endpoints:**
- Check `TASK_SIGNING_SECRET` / `X-Cron-Secret` header match

**Database connection errors:**
- Ensure `supabase start` is running
- Check `SUPABASE_URL` and keys in `.env`

---
*Private use only.*
