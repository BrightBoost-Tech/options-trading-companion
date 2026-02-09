# Options Trading Companion

Personal options trading companion with AI-powered scouting, backtesting, and go-live validation guardrails!

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

**Windows One-Click:** Run `start.bat` from the repo root to launch all services (Redis, Backend, Worker, Frontend). The launcher uses PowerShell scripts (`scripts\win\*.ps1`) for reliable environment loading. See [STARTUP.md](STARTUP.md) for desktop shortcut instructions.

## Environment Variables

### Supabase Configuration

The backend and worker use a unified configuration system that loads env files in priority order:

1. `.env.local` (repo root) - highest priority
2. `.env` (repo root)
3. `packages/quantum/.env.local`
4. `packages/quantum/.env`

**Variable precedence** (backend prefers non-prefixed names):

| Component | URL Variable | Key Variable |
|-----------|--------------|--------------|
| **Backend/Worker** | `SUPABASE_URL` (preferred) | `SUPABASE_SERVICE_ROLE_KEY` (required) |
| **Frontend** | `NEXT_PUBLIC_SUPABASE_URL` | `NEXT_PUBLIC_SUPABASE_ANON_KEY` |

Fallback aliases are supported for compatibility:
- `SUPABASE_URL` ← `NEXT_PUBLIC_SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY` ← `SUPABASE_SERVICE_KEY`
- `SUPABASE_ANON_KEY` ← `NEXT_PUBLIC_SUPABASE_ANON_KEY`

**Key types:**
- **Service Role Key**: Required for backend/worker. Bypasses RLS, can call RPC functions.
- **Anon Key**: Used by frontend. Subject to Row Level Security.

### Root / Frontend (`.env` or `.env.local`)

Copy `.env.example` to `.env`:

| Variable | Purpose |
|----------|---------|
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase API URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase anon/public key |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role key (for server-side operations) |

### Backend (`packages/quantum/.env`)

Copy `packages/quantum/.env.example`:

| Variable | Purpose |
|----------|---------|
| `SUPABASE_URL` | Supabase API URL (preferred over NEXT_PUBLIC_*) |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role key for admin DB access |
| `SUPABASE_ANON_KEY` | Anon key for user-scoped operations |
| `SUPABASE_JWT_SECRET` | JWT secret for token verification |
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

Protected by `X-Cron-Secret` header. See [docs/daily_workflow.md](docs/daily_workflow.md) for details.

### Daily Workflow (Scheduled)

| Endpoint | Time (America/Chicago) | Purpose |
|----------|------------------------|---------|
| `/tasks/suggestions/close` | 8:00 AM | Exit suggestions for existing positions |
| `/tasks/suggestions/open` | 11:00 AM | Entry suggestions for new positions |

### Learning & Maintenance

| Endpoint | Schedule | Purpose |
|----------|----------|---------|
| `/tasks/learning/ingest` | Daily | Map executed trades to suggestions |
| `/tasks/strategy/autotune` | Weekly | Adjust strategy based on outcomes |

### Legacy Endpoints

| Endpoint | Purpose |
|----------|---------|
| `/tasks/morning-brief` | Morning exit logic (deprecated, use suggestions/close) |
| `/tasks/midday-scan` | Scanner and sizing (deprecated, use suggestions/open) |
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
│   └── win/              # Windows launchers (start_all, stop_all, etc.)
└── .github/
    └── workflows/        # CI/CD
```

## Troubleshooting

**Backend won't start:**
- Missing `ENCRYPTION_KEY` in `packages/quantum/.env`
- Generate with: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

**Supabase Startup Validation Failed (401 Invalid API key):**
- This means the backend connected to Supabase but the key was rejected
- Common causes:
  1. **Wrong key type**: Using anon key instead of service role key
  2. **Key mismatch**: Production URL paired with development key (or vice versa)
  3. **Expired/rotated key**: Key was regenerated in Supabase dashboard
- Fix:
  1. Go to Supabase Dashboard → Project Settings → API
  2. Copy the `service_role` key (not anon key)
  3. Set `SUPABASE_SERVICE_ROLE_KEY` in `packages/quantum/.env`
  4. Ensure `SUPABASE_URL` matches the same project
- The backend will show which env files were loaded and key type detected

**Worker fails with "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required":**
- The worker needs environment variables to connect to the database
- Fix:
  1. Copy `.env.example` to `.env` in the repo root
  2. Fill in `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`
  3. For local dev, run `supabase start` and use the local URL/keys
- The worker auto-loads `.env` files from:
  - `.env.local` (highest priority)
  - `.env`
  - `packages/quantum/.env.local`
  - `packages/quantum/.env`
- Accepts both `SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_URL`

**401 on task endpoints:**
- Check `TASK_SIGNING_SECRET` / `X-Cron-Secret` header match

**Database connection errors:**
- Ensure `supabase start` is running
- Check `SUPABASE_URL` and keys in `.env`

## Deployment (Railway)

**Frontend (apps/web):**
- Set `BACKEND_URL` to your backend service URL (e.g., `https://your-backend.railway.app`)
- The frontend will proxy `/api/*` requests to this URL
- If `BACKEND_URL` is not set, it defaults to `http://127.0.0.1:8000` (local dev)

---
*Private use only.*
