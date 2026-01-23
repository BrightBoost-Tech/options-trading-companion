-- Shadow Cohort Daily Winners Table (v4-L1E)
--
-- Persists daily cohort evaluation winners for autopromote decision-making.
-- One row per user per UTC date bucket.

CREATE TABLE IF NOT EXISTS shadow_cohort_daily (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    bucket_date DATE NOT NULL,  -- UTC date
    winner_cohort TEXT NOT NULL,
    winner_return_pct DOUBLE PRECISION NOT NULL,
    winner_margin_to_target DOUBLE PRECISION NOT NULL,
    winner_max_drawdown_pct DOUBLE PRECISION NOT NULL,
    winner_would_fail_fast BOOLEAN NOT NULL DEFAULT false,
    winner_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Unique constraint for idempotency
    CONSTRAINT shadow_cohort_daily_user_bucket_unique UNIQUE (user_id, bucket_date)
);

-- Index for efficient lookups of recent history
CREATE INDEX IF NOT EXISTS idx_shadow_cohort_daily_user_bucket
ON shadow_cohort_daily (user_id, bucket_date DESC);

-- RLS policies
ALTER TABLE shadow_cohort_daily ENABLE ROW LEVEL SECURITY;

-- Service role can do anything
CREATE POLICY "Service role full access on shadow_cohort_daily"
ON shadow_cohort_daily
FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

-- Users can read their own records
CREATE POLICY "Users can read own shadow_cohort_daily"
ON shadow_cohort_daily
FOR SELECT
TO authenticated
USING (auth.uid()::text = user_id);

COMMENT ON TABLE shadow_cohort_daily IS 'Daily shadow cohort evaluation winners for autopromote guardrail (v4-L1E)';
COMMENT ON COLUMN shadow_cohort_daily.bucket_date IS 'UTC date bucket for idempotency';
COMMENT ON COLUMN shadow_cohort_daily.winner_cohort IS 'Name of the winning cohort for this day';
COMMENT ON COLUMN shadow_cohort_daily.winner_return_pct IS 'Return percentage achieved (as pct, e.g., 1.5 means 1.5%)';
COMMENT ON COLUMN shadow_cohort_daily.winner_would_fail_fast IS 'Whether this winner triggered fail-fast conditions';
