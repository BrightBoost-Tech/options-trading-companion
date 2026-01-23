-- Migration: 20260123000000_create_execution_drift_logs.sql
-- Purpose: Repair migration for environments where 20250101000005_analytics_observability.sql
--          already ran but execution_drift_logs table was missing.
-- This migration is idempotent (IF NOT EXISTS) and safe for all environments.

-- Create execution_drift_logs table (required by discipline_score_per_user view)
CREATE TABLE IF NOT EXISTS execution_drift_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    symbol TEXT NULL,
    tag TEXT NOT NULL,
    details_json JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_execution_drift_logs_user_time
    ON execution_drift_logs(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_execution_drift_logs_tag
    ON execution_drift_logs(tag);

-- Recreate the view to ensure it references the now-existing table
CREATE OR REPLACE VIEW discipline_score_per_user AS
SELECT
    user_id,
    COUNT(*) FILTER (WHERE tag = 'disciplined_execution') AS disciplined_count,
    COUNT(*) FILTER (WHERE tag = 'impulse_trade') AS impulse_count,
    COUNT(*) FILTER (WHERE tag = 'size_violation') AS size_violation_count,
    CASE
        WHEN COUNT(*) = 0 THEN 0
        ELSE (COUNT(*) FILTER (WHERE tag = 'disciplined_execution'))::FLOAT / COUNT(*)
    END AS discipline_score
FROM execution_drift_logs
GROUP BY user_id;
