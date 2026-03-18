-- Paper Green Day State Fields
-- Adds realized-only daily P&L tracking independent of paper_consecutive_passes.
-- paper_green_days counts trading days with positive realized P&L.
-- Idempotency: paper_last_green_day_evaluated_at stores the last evaluated
-- trading date string (YYYY-MM-DD) so re-runs on the same day are no-ops.

ALTER TABLE v3_go_live_state
  ADD COLUMN IF NOT EXISTS paper_green_days INTEGER DEFAULT 0;

ALTER TABLE v3_go_live_state
  ADD COLUMN IF NOT EXISTS paper_last_green_day_date DATE;

ALTER TABLE v3_go_live_state
  ADD COLUMN IF NOT EXISTS paper_last_daily_realized_pnl NUMERIC;

ALTER TABLE v3_go_live_state
  ADD COLUMN IF NOT EXISTS paper_last_green_day_evaluated_at TEXT;
