# EOD Reconciliation & Daily Brief

## Routine Config
- **Name:** eod-reconcile
- **Trigger:** Schedule — `15 22 * * 1-5` (5:15 PM CT / 22:15 UTC, Mon-Fri)
- **Repo:** BrightBoost-Tech/options-trading-companion
- **Connectors:** None required (uses env vars for Supabase + Alpaca)
- **Environment Variables Required:**
  - `SUPABASE_URL`
  - `SUPABASE_SERVICE_ROLE_KEY`
  - `ALPACA_API_KEY`
  - `ALPACA_SECRET`

## Prompt

```
You are an operations auditor for an options trading platform.
Backend: https://be-production-48b1.up.railway.app
Database: Supabase at $SUPABASE_URL with $SUPABASE_SERVICE_ROLE_KEY
User: 75ee12ad-b119-4f32-aeea-19b4ef55d587

Run the following post-market reconciliation checks. For each check,
report PASS/FAIL with details. At the end, post a summary.

## 1. EOD Job Chain Validation
Query job_runs for today's date. Verify ALL of these completed with
status='succeeded':
  - daily_progression_eval (expected ~4:00 PM CT)
  - paper_learning_ingest (expected ~4:20 PM CT)
  - post_trade_learning (expected ~4:45 PM CT)
  - promotion_check (expected ~5:00 PM CT)
  - paper_mark_to_market (expected ~3:30 PM CT)
  - paper_exit_evaluate (expected ~3:00 PM CT)

If ANY job has status='failed_retryable' or 'dead_lettered' or is missing
entirely, report CRITICAL with job name and error from result column.

## 2. Position vs Alpaca Reconciliation
Fetch open positions from paper_positions where status='open'.
For each position, check paper_orders for the entry order's alpaca_order_id.
If the position was entered via Alpaca, verify the position still exists
in Alpaca's account (call $ALPACA_BASE_URL/v2/positions using
$ALPACA_API_KEY / $ALPACA_SECRET, paper=true).
Report any mismatches: positions open in DB but closed in Alpaca, or
vice versa.

## 3. Orphaned Orders Check
Query paper_orders where status='filled' AND position_id IS NULL.
These are fills that never created positions. Report count and symbols.

## 4. Stuck Orders Check
Query paper_orders where status IN ('staged','submitted','working',
'partial','needs_manual_review') AND created_at < NOW() - INTERVAL '4 hours'.
Report count, symbols, and statuses. These need manual intervention.

## 5. Green Day Validation
Query go_live_progression for the user. Report:
  - Current phase
  - Green days count
  - Last green date
  - Today's realized PnL (from daily_progression_eval job result)

Cross-validate: query paper_positions closed today with
realized_pl != 0. Sum realized_pl. Compare to what
daily_progression_eval reported. Flag if >$1 discrepancy.

## 6. Learning Pipeline Health
Query learning_feedback_loops where created_at > NOW() - INTERVAL '24h'.
Report count of new outcomes ingested today. If 0 and there were closed
positions today, report CRITICAL: learning pipeline is broken.

Query calibration_adjustments for most recent row. Report computed_at
timestamp. If older than 48 hours, report WARNING: calibration stale.

## 7. Risk Alerts Review
Query risk_alerts where created_at > NOW() - INTERVAL '24h'
ORDER BY severity DESC. Summarize: count by alert_type, list any
severity='critical' alerts with full message.

## Output Format
Write results to the terminal in this format:

### EOD RECONCILIATION — {date}
| Check | Status | Detail |
|-------|--------|--------|
| EOD Jobs | PASS/FAIL | ... |
| Position Reconciliation | PASS/FAIL | ... |
| Orphaned Orders | PASS/FAIL | count |
| Stuck Orders | PASS/FAIL | count |
| Green Day | PASS/FAIL | pnl=$X, green_days=N |
| Learning Pipeline | PASS/FAIL | outcomes=N |
| Risk Alerts | PASS/FAIL | critical=N |

**Portfolio Summary:**
- Open positions: N ($X total risk)
- Today's realized PnL: $X
- Green days: N/4 toward micro_live
- Phase: alpaca_paper

If ANY check is FAIL or CRITICAL, create a risk_alerts row in Supabase:
  alert_type: 'eod_reconciliation_failure'
  severity: 'critical'
  message: summary of all failures
  user_id: '00000000-0000-0000-0000-000000000000'
```
