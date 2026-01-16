# Daily Workflow: Holdings Sync, Suggestions, and Learning

This document describes the automated daily workflow for generating trade suggestions and learning from outcomes.

## Overview

The system runs two scheduled tasks daily (Monday-Friday):

| Time (America/Chicago) | Task | Purpose |
|------------------------|------|---------|
| 8:00 AM | `suggestions_close` | Generate exit suggestions for existing positions |
| 11:00 AM | `suggestions_open` | Generate entry suggestions for new positions |

Additionally, there are learning tasks that run periodically:

| Schedule | Task | Purpose |
|----------|------|---------|
| Daily (after market) | `learning_ingest` | Map executed trades to suggestions |
| Weekly (Sunday) | `strategy_autotune` | Adjust strategy config based on outcomes |

## How It Works

### 1. Holdings Sync

Before generating suggestions, the system ensures holdings are up-to-date:

1. Check if user has Plaid connection
2. If holdings are stale (>60 minutes old), sync from Plaid
3. Update `positions` table with current holdings
4. Create `portfolio_snapshots` entry

**No Plaid?** The system uses existing positions from the database.

### 2. Strategy Loading

Each task loads the user's strategy configuration:

- Strategy name: `spy_opt_autolearn_v6` (default)
- Loaded from `strategy_configs` table
- Falls back to default config if not found
- Strategy includes: risk limits, conviction thresholds, exit rules

### 3. Suggestion Generation

**Morning (8 AM) - Close Suggestions:**
- Analyzes existing positions
- Computes EV-based profit targets
- Generates exit limit orders for positions with positive EV
- Suggestions saved with `window='morning_limit'`

**Midday (11 AM) - Open Suggestions:**
- Fetches deployable capital
- Scans market for opportunities
- Applies conviction scoring
- Generates entry suggestions with sizing
- Suggestions saved with `window='midday_entry'`

### 4. Learning Loop

**Daily Outcome Ingestion:**
1. Fetch Plaid investment transactions (past 7 days)
2. Match transactions to suggestions by symbol/direction/date
3. Create `learning_feedback_loops` records with:
   - Realized PnL
   - Predicted EV (from suggestion)
   - Win/loss outcome type

**Weekly Strategy Autotune:**
1. Analyze past 30 days of outcomes
2. Compute win rate and average PnL
3. If performance below threshold:
   - Win rate < 45%: tighten conviction, reduce stop loss
   - Avg PnL < 0: reduce risk exposure, lower take profit
4. Persist new strategy version (never deletes old versions)

## Timezone Handling

All scheduled times are **America/Chicago (CST/CDT)**:

- CST (Nov-Mar): UTC-6
- CDT (Mar-Nov): UTC-5

The GitHub Actions workflow uses UTC cron expressions:
- `0 14 * * 1-5` = 8:00 AM CST (during DST: 9:00 AM CDT)
- `0 17 * * 1-5` = 11:00 AM CST (during DST: 12:00 PM CDT)

**Note:** During daylight saving time, jobs run 1 hour late in local time. This is acceptable since suggestions remain valid for hours.

## API Endpoints

### Task Endpoints (require `X-Cron-Secret` header)

```bash
# 8 AM - Generate close suggestions
POST /tasks/suggestions/close
{
  "strategy_name": "spy_opt_autolearn_v6",  # optional
  "user_id": "uuid",                         # optional, default: all users
  "skip_sync": false                         # optional
}

# 11 AM - Generate open suggestions
POST /tasks/suggestions/open
{
  "strategy_name": "spy_opt_autolearn_v6",
  "user_id": "uuid",
  "skip_sync": false
}

# Daily - Ingest outcomes
POST /tasks/learning/ingest
{
  "user_id": "uuid",
  "lookback_days": 7
}

# Weekly - Auto-tune strategy
POST /tasks/strategy/autotune
{
  "user_id": "uuid",
  "strategy_name": "spy_opt_autolearn_v6",
  "min_samples": 10
}
```

### Manual Trigger (GitHub Actions)

1. Go to Actions tab in GitHub
2. Select "Daily Workflow"
3. Click "Run workflow"
4. Choose task: `all`, `suggestions_close`, `suggestions_open`, etc.

## Database Tables

| Table | Purpose |
|-------|---------|
| `positions` | Current holdings (synced from Plaid) |
| `portfolio_snapshots` | Historical portfolio state |
| `trade_suggestions` | Generated suggestions |
| `strategy_configs` | Versioned strategy parameters |
| `learning_feedback_loops` | Trade outcomes for learning |

## Connecting Plaid

1. Navigate to Settings page in the UI
2. Click "Connect Broker"
3. Complete Plaid Link flow
4. Select Robinhood or other broker
5. Holdings will sync automatically before suggestions

### Robinhood via Plaid

Plaid supports Robinhood for holdings sync. However:
- Transaction history may be limited
- Some account types may not be supported
- Fallback: Manual CSV import (see below)

### Fallback: CSV Import

If Plaid doesn't provide transaction data:

1. Export trades from Robinhood
2. POST to `/api/outcomes/upload-csv` (coming soon)
3. Format: `date,symbol,side,quantity,price,fees`

## Troubleshooting

### Suggestions not generating

1. Check user has positions in `positions` table
2. Verify Plaid connection is active
3. Check job run status in `/jobs/runs`

### Holdings not syncing

1. Verify Plaid access token exists in `user_settings`
2. Check Plaid API status
3. Try manual sync via `/plaid/sync_holdings`

### Learning not working

1. Ensure `learning_feedback_loops` table has data
2. Check Plaid supports investment transactions for your broker
3. Verify suggestions have `trace_id` set

### Wrong timezone

The system uses CST (UTC-6) baseline. During CDT (Mar-Nov), jobs run 1 hour late in local time. For precise DST handling, consider deploying an internal scheduler.

## Environment Variables

```bash
# Required for scheduling
CRON_SECRET=<random-secret>  # Must match GitHub Actions secret
API_URL=https://your-api.com # Backend URL

# Required for Plaid
PLAID_CLIENT_ID=<plaid-client-id>
PLAID_SECRET=<plaid-secret>
PLAID_ENV=sandbox  # or production
```

## Files Reference

| File | Purpose |
|------|---------|
| `.github/workflows/schedule_tasks.yml` | Cron schedule definition |
| `packages/quantum/public_tasks.py` | Task endpoint definitions |
| `packages/quantum/jobs/handlers/suggestions_close.py` | Close suggestion handler |
| `packages/quantum/jobs/handlers/suggestions_open.py` | Open suggestion handler |
| `packages/quantum/jobs/handlers/learning_ingest.py` | Outcome ingestion handler |
| `packages/quantum/jobs/handlers/strategy_autotune.py` | Strategy tuning handler |
| `packages/quantum/services/holdings_sync_service.py` | Holdings sync logic |
| `packages/quantum/services/strategy_loader.py` | Strategy config loading |
| `packages/quantum/services/workflow_orchestrator.py` | Core suggestion generation |
