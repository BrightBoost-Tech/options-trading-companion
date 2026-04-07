-- Add cohort_id to paper_positions for direct cohort linkage.
--
-- Previously, cohort was resolved indirectly via portfolio_id → policy_lab_cohorts.
-- This broke when positions were created on portfolios not mapped to any cohort,
-- leaving them invisible to cohort-specific exit conditions (stop loss, target profit).

ALTER TABLE paper_positions
  ADD COLUMN IF NOT EXISTS cohort_id uuid REFERENCES policy_lab_cohorts(id);

CREATE INDEX IF NOT EXISTS idx_paper_positions_cohort_id
  ON paper_positions(cohort_id);

-- Backfill existing open positions from portfolio_id → policy_lab_cohorts
UPDATE paper_positions pp
SET cohort_id = plc.id
FROM policy_lab_cohorts plc
WHERE pp.portfolio_id = plc.portfolio_id
  AND pp.cohort_id IS NULL
  AND pp.status = 'open';

NOTIFY pgrst, 'reload schema';
