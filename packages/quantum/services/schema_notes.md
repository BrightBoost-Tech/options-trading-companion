# Database Schema Notes for Cash-Aware Workflow

This document outlines the expected database schema changes required to support the new cash-aware, time-based workflow.

## Tables

### `trade_suggestions`

Stores generated trade ideas and their lifecycle status.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | Primary Key, default gen_random_uuid() |
| `user_id` | uuid | Foreign Key to auth.users.id |
| `created_at` | timestamptz | Default now() |
| `valid_until` | timestamptz | When the suggestion expires |
| `window` | text | 'morning_limit' or 'midday_entry' |
| `ticker` | text | Asset symbol (e.g. 'AAPL') |
| `strategy` | text | e.g. 'credit_spread', 'limit_sell' |
| `direction` | text | 'long', 'short' |
| `order_json` | jsonb | Details: { "side": "buy", "limit_price": 1.50, "contracts": 1 } |
| `sizing_metadata` | jsonb | Details: { "capital_required": 500.0, "reason": "Risk capped" } |
| `status` | text | 'pending', 'dismissed', 'executed', 'expired' |
| `ev` | numeric | Scalar Expected Value ($) |

### `weekly_trade_reports`

Stores the weekly summary generated for users.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | Primary Key, default gen_random_uuid() |
| `user_id` | uuid | Foreign Key to auth.users.id |
| `week_ending` | date | The Friday date of the week |
| `total_pnl` | numeric | Total P&L for the week |
| `win_rate` | numeric | 0.0 to 1.0 |
| `trade_count` | integer | Number of trades closed this week |
| `missed_opportunities` | jsonb | List of potential missed trades |
| `report_markdown` | text | AI-generated summary text |

### `portfolio_snapshots` (Updates)

Existing table `portfolio_snapshots` should expect these additional fields in the future, though code handles their absence gracefully.

| Column | Type | Notes |
|---|---|---|
| `buying_power` | numeric | Cash available for trading |
| `unsettled_cash` | numeric | Cash tied up in settlement |
| `buying_power` (in `plaid_items`) | numeric | *Existing field often used as fallback* |

### `user_settings` (Updates)

| Column | Type | Notes |
|---|---|---|
| `cash_buffer` | numeric | Amount of cash to keep reserved (default 0) |

## Migration Status

**Do not attempt automatic migrations.**
These tables should be created via the Supabase Dashboard SQL Editor or Migration tool.
The backend code assumes these tables exist or handles errors if they are missing.
