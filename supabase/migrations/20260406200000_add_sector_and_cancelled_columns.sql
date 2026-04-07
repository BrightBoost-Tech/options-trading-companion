-- Add sector column to paper_positions for risk envelope concentration checks.
-- The risk envelope queries this column to enforce sector concentration limits.
ALTER TABLE paper_positions
ADD COLUMN IF NOT EXISTS sector TEXT DEFAULT NULL;

COMMENT ON COLUMN paper_positions.sector IS 'GICS sector for concentration checks in risk envelope';

-- Add cancelled_reason and cancelled_detail to job_runs.
-- Used by promotion_check to detect go_live_gate cancellations and by
-- create_or_get_cancelled() to record why a job was blocked.
ALTER TABLE job_runs
ADD COLUMN IF NOT EXISTS cancelled_reason TEXT DEFAULT NULL;

ALTER TABLE job_runs
ADD COLUMN IF NOT EXISTS cancelled_detail TEXT DEFAULT NULL;

CREATE INDEX IF NOT EXISTS idx_job_runs_cancelled_reason
ON job_runs (cancelled_reason) WHERE cancelled_reason IS NOT NULL;

COMMENT ON COLUMN job_runs.cancelled_reason IS 'Why job was cancelled (go_live_gate, global_ops_pause, manual_approval_required)';
COMMENT ON COLUMN job_runs.cancelled_detail IS 'Additional detail for cancelled jobs';
