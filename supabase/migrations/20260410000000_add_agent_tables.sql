-- Agent infrastructure tables: signal_weight_history, strategy_adjustments, agent_sessions
-- Plus schema additions for learning pipeline processing flags

-- ============================================================================
-- Table 1: signal_weight_history
-- Tracks every time the learning agent adjusts a strategy's signal weight.
-- ============================================================================
CREATE TABLE IF NOT EXISTS signal_weight_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    user_id UUID REFERENCES auth.users(id),
    segment_key TEXT NOT NULL,
    strategy TEXT NOT NULL,
    regime TEXT NOT NULL,
    dte_bucket TEXT NOT NULL,
    old_multiplier NUMERIC NOT NULL,
    new_multiplier NUMERIC NOT NULL,
    trade_count INTEGER NOT NULL,
    realized_win_rate NUMERIC,
    predicted_win_rate NUMERIC,
    alpha_mean NUMERIC,
    trigger TEXT NOT NULL,
    metadata JSONB DEFAULT '{}'
);

-- ============================================================================
-- Table 2: strategy_adjustments
-- Tracks when a strategy's score weight is reduced or flagged.
-- ============================================================================
CREATE TABLE IF NOT EXISTS strategy_adjustments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    user_id UUID REFERENCES auth.users(id),
    strategy TEXT NOT NULL,
    action TEXT NOT NULL,
    old_weight NUMERIC,
    new_weight NUMERIC,
    reason TEXT NOT NULL,
    supporting_data JSONB DEFAULT '{}',
    resolved BOOLEAN DEFAULT FALSE
);

-- ============================================================================
-- Table 3: agent_sessions
-- Tracks every Managed Agent session for observability.
-- ============================================================================
CREATE TABLE IF NOT EXISTS agent_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    agent_name TEXT NOT NULL,
    session_id TEXT,
    status TEXT DEFAULT 'started',
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    summary JSONB DEFAULT '{}',
    error TEXT
);

-- ============================================================================
-- RLS for all three tables
-- ============================================================================
ALTER TABLE signal_weight_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE strategy_adjustments ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_sessions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users see own signal_weight_history" ON signal_weight_history
    FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "Service role signal_weight_history" ON signal_weight_history
    FOR ALL TO service_role USING (true);

CREATE POLICY "Users see own strategy_adjustments" ON strategy_adjustments
    FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "Service role strategy_adjustments" ON strategy_adjustments
    FOR ALL TO service_role USING (true);

CREATE POLICY "Anyone can read agent_sessions" ON agent_sessions
    FOR SELECT USING (true);
CREATE POLICY "Service role agent_sessions" ON agent_sessions
    FOR ALL TO service_role USING (true);

-- ============================================================================
-- Indexes
-- ============================================================================
CREATE INDEX idx_signal_weight_history_segment
    ON signal_weight_history(segment_key, created_at DESC);
CREATE INDEX idx_strategy_adjustments_strategy
    ON strategy_adjustments(strategy, created_at DESC);
CREATE INDEX idx_agent_sessions_name
    ON agent_sessions(agent_name, created_at DESC);

-- ============================================================================
-- Schema additions to existing tables
-- ============================================================================

-- learning_feedback_loops: track which rows have been processed by learning agent
ALTER TABLE learning_feedback_loops
ADD COLUMN IF NOT EXISTS learning_processed BOOLEAN DEFAULT FALSE;

-- paper_positions: track which positions have been ingested to learning
ALTER TABLE paper_positions
ADD COLUMN IF NOT EXISTS learning_ingested BOOLEAN DEFAULT FALSE;
