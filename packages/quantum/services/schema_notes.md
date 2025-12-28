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
| `trace_id` | uuid | Link to inference log |
| `model_version` | text | Version of the model used |
| `features_hash` | text | Hash of input features for reproducibility |
| `agent_signals` | jsonb | Quant Agents v3: Raw signals/reasoning |
| `agent_summary` | jsonb | Quant Agents v3: Human-readable summary |

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

### `suggestion_logs` (New)

Logs suggestion creation context and lifecycle for analysis.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | Primary Key |
| `user_id` | uuid | Foreign Key |
| `regime_context` | jsonb | Snapshot of market regime at creation |
| `symbol` | text | Ticker |
| `strategy_type` | text | e.g. "vertical_spread" |
| `confidence_score` | numeric | Algorithm score |
| `was_accepted` | boolean | True if executed |
| `trade_execution_id` | uuid | Link to execution |

### `trade_executions` (New)

Logs actual executions, linked to suggestions or standalone.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | Primary Key |
| `user_id` | uuid | Foreign Key |
| `symbol` | text | Ticker |
| `fill_price` | numeric | Executed price |
| `quantity` | integer | Executed quantity |
| `suggestion_id` | uuid | Optional link to suggestion |
| `realized_pnl` | numeric | P&L after exit |

### `weekly_snapshots` (New)

Aggregated weekly progress metrics.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | Primary Key |
| `week_id` | text | e.g. "2025-W48" |
| `user_metrics` | jsonb | Adherence, Risk Compliance, Efficiency |
| `system_metrics` | jsonb | Win Rate, Regime Stability |
| `synthesis` | jsonb | Headline & Action Items |

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

### `model_governance_states` (New - Learned Nesting v3)

Stores per-user model governance states (calibration + conviction multipliers).

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | Primary Key |
| `user_id` | uuid | Foreign Key |
| `model_name` | text | e.g. 'calibration_v3', 'conviction_v3' |
| `strategy` | text | Optional filter |
| `window` | text | Optional filter |
| `regime` | text | Optional filter |
| `state_json` | jsonb | Calibration/conviction parameters |
| `sample_size` | integer | Number of samples used |
| `trained_at` | timestamptz | When it was last trained |
| `created_at` | timestamptz | Creation time |
| `updated_at` | timestamptz | Auto-updated |

### Learned Nesting v3 Views

The following views are created for v3 learning surfaces:

- **`learning_trade_outcomes_v3`**: Joins `trade_suggestions` and `learning_feedback_loops` to provide a flattened view of trade outcomes with traceability.
- **`learning_performance_summary_v3`**: Aggregates trade outcomes by user, strategy, window, and regime. **This is the preferred source for conviction multipliers going forward.**
- **`learning_contract_violations_v3`**: Identifies data integrity issues in the learning pipeline (missing traces, IDs, etc.).

## Migration Status

**Do not attempt automatic migrations.**
These tables should be created via the Supabase Dashboard SQL Editor or Migration tool.
The backend code assumes these tables exist or handles errors if they are missing.
