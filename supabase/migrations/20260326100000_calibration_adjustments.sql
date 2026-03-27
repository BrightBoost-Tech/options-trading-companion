-- Calibration adjustments cache — precomputed by scheduled job,
-- read at suggestion scoring time for fast lookup.

CREATE TABLE IF NOT EXISTS calibration_adjustments (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid NOT NULL,
  adjustments jsonb NOT NULL DEFAULT '{}',
  total_outcomes int NOT NULL DEFAULT 0,
  computed_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_calibration_adjustments_user
  ON calibration_adjustments(user_id, computed_at DESC);

-- RLS
ALTER TABLE calibration_adjustments ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own calibration"
  ON calibration_adjustments FOR SELECT
  USING (auth.uid() = user_id);

CREATE POLICY "Service role full access calibration"
  ON calibration_adjustments FOR ALL
  USING (auth.role() = 'service_role');

NOTIFY pgrst, 'reload schema';
