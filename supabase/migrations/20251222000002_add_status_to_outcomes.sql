-- Add status taxonomy to outcomes_log
-- Statuses: COMPLETE, PARTIAL, INCOMPLETE
-- Reason codes: array of text

ALTER TABLE outcomes_log
ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'COMPLETE',
ADD COLUMN IF NOT EXISTS reason_codes TEXT[] DEFAULT '{}';

-- Optional: Create an index for filtering by status
CREATE INDEX IF NOT EXISTS idx_outcomes_log_status ON outcomes_log(status);
