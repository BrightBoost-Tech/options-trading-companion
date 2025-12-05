-- Migration: 20250101000005_analytics_observability.sql

-- 1. Analytics Events Table (UX & System Events)
CREATE TABLE IF NOT EXISTS analytics_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ DEFAULT now(),
    trace_id UUID NULL,         -- Link to inference_log.trace_id if relevant
    user_id UUID NULL,          -- Optional for unauth
    event_name TEXT NOT NULL,   -- e.g., 'suggestion_viewed', 'plaid_link_started'
    category TEXT NOT NULL,     -- 'ux' | 'system' | 'trade' | 'learning'
    session_id TEXT NULL,
    properties JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_analytics_user_time ON analytics_events(user_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_analytics_event_name ON analytics_events(event_name);


-- 2. Learning Feedback Loops Table (Outcomes & Lessons)
CREATE TABLE IF NOT EXISTS learning_feedback_loops (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_event_id UUID NULL,       -- Points to analytics_events.id (e.g., suggestion_shown)
    outcome_event_id UUID NULL,      -- Could point to drift logs or other outcome event
    trace_id UUID NULL,              -- Link to inference_log.trace_id (Optimizer Run)
    user_id UUID NULL,
    outcome_type TEXT NOT NULL,      -- 'disciplined_win', 'impulse_loss', 'historical_win', etc.
    pnl_realized NUMERIC NULL,
    pnl_predicted NUMERIC NULL,      -- EV from optimizer
    drift_tags TEXT[] DEFAULT '{}'::text[],
    details_json JSONB DEFAULT '{}'::jsonb, -- Flexible storage for regimeAtEntry, etc.
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_learning_user_time ON learning_feedback_loops(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_learning_trace ON learning_feedback_loops(trace_id);


-- 3. Views for Metrics

-- View A: Discipline Score (Behavioral Metric)
-- Aggregates counts from execution_drift_logs
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

-- View B: Suggestion Conversion Funnel (UX Metric)
-- Aggregates analytics_events
CREATE OR REPLACE VIEW suggestion_funnel_per_user AS
SELECT
    user_id,
    COUNT(*) FILTER (WHERE event_name = 'suggestion_viewed') AS suggestions_shown,
    COUNT(*) FILTER (WHERE event_name = 'suggestion_staged') AS suggestions_staged,
    CASE
        WHEN COUNT(*) FILTER (WHERE event_name = 'suggestion_viewed') = 0 THEN 0
        ELSE (COUNT(*) FILTER (WHERE event_name = 'suggestion_staged'))::FLOAT /
             (COUNT(*) FILTER (WHERE event_name = 'suggestion_viewed'))
    END AS conversion_rate
FROM analytics_events
GROUP BY user_id;

-- View C: Realized vs Predicted PnL (Learning Metric)
-- Aggregates learning_feedback_loops
CREATE OR REPLACE VIEW pnl_vs_ev AS
SELECT
    user_id,
    AVG(pnl_realized) AS avg_pnl_realized,
    AVG(pnl_predicted) AS avg_pnl_predicted,
    AVG(pnl_realized - COALESCE(pnl_predicted, 0)) AS bias,
    COUNT(*) AS samples
FROM learning_feedback_loops
WHERE pnl_realized IS NOT NULL
GROUP BY user_id;
