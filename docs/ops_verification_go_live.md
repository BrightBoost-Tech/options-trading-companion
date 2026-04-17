# Go-Live Ops Verification Queries

Quick-reference SQL for verifying readiness and green-day state after the
daily checkpoint (typically 6:30 PM Chicago / after `validation_eval` runs).

## Current State for a User

The canonical phase/green-day source is `go_live_progression`.
`v3_go_live_state` is a legacy readiness table still written by
`validation_shadow_eval` for shadow checkpoints; queries below use the
current table for phase + green-day state.

```sql
SELECT
  user_id,
  current_phase,
  alpaca_paper_green_days,
  alpaca_paper_green_days_required,
  alpaca_paper_last_green_date,
  alpaca_paper_started_at,
  alpaca_paper_completed_at,
  updated_at
FROM go_live_progression
WHERE user_id = '<USER_ID>';
```

## All Users — Streak + Green Day Summary

```sql
SELECT
  user_id,
  paper_consecutive_passes  AS streak,
  paper_ready,
  paper_green_days,
  paper_last_green_day_date AS last_green,
  paper_last_daily_realized_pnl AS last_pnl,
  paper_last_green_day_evaluated_at AS last_eval
FROM v3_go_live_state
ORDER BY paper_green_days DESC;
```

## Today's Paper Realized P&L (Chicago day)

Replace the timestamps with today's Chicago midnight boundaries
(CST = 06:00 UTC, CDT = 05:00 UTC).

```sql
SELECT
  user_id,
  SUM(pnl_realized) AS daily_realized_pnl,
  COUNT(*)           AS trade_count
FROM learning_trade_outcomes_v3
WHERE is_paper = true
  AND closed_at >= '2026-03-18T06:00:00+00:00'   -- Chicago midnight (CST)
  AND closed_at <  '2026-03-19T06:00:00+00:00'
GROUP BY user_id;
```

## Recent Checkpoint Runs (Audit Trail)

```sql
SELECT
  user_id,
  mode,
  passed,
  return_pct,
  pnl_total,
  fail_reason,
  details_json,
  created_at
FROM v3_go_live_runs
WHERE user_id = '<USER_ID>'
ORDER BY created_at DESC
LIMIT 10;
```

## Verify Green Day Was Not Double-Counted

If `paper_last_green_day_evaluated_at` equals today's Chicago date, the
evaluation already ran. Re-running `validation_eval` will not increment
`paper_green_days` again.

```sql
SELECT
  user_id,
  paper_green_days,
  paper_last_green_day_evaluated_at
FROM v3_go_live_state
WHERE paper_last_green_day_evaluated_at = '2026-03-18';
```

## validation_eval Response Shape (Paper Mode)

After the handler runs, the result payload contains:

```json
{
  "status": "completed",
  "timing_ms": 142.5,
  "result": {
    "checkpoint_status": "pass",
    "paper_consecutive_passes": 6,
    "paper_ready": false,
    "reason": null,
    "return_pct": 3.2,
    "pnl_realized": 3000.0,
    "pnl_unrealized": 200.0,
    "target_return_now": 2.5,
    "progress": 0.45,
    "max_drawdown_pct": -0.5,
    "bucket": "2024-01-10",
    "streak_before": 5,
    "window_start": "2024-01-01T06:00:00+00:00",
    "window_end": "2024-01-22T06:00:00+00:00",
    "outcome_count": 7,
    "evaluated_trading_date": "2024-01-10",
    "daily_realized_pnl": 150.0,
    "green_day": true,
    "paper_green_days": 4,
    "paper_last_green_day_date": "2024-01-10",
    "green_day_available": true,
    "checkpoint": { "...full checkpoint result..." },
    "green_day_detail": { "...full green-day result..." }
  }
}
```
