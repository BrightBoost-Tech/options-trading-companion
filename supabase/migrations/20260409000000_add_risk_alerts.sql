-- Risk Alerts table for intraday risk monitoring
-- Created by Loss Minimization Agent (Phase 1)

CREATE TABLE IF NOT EXISTS risk_alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    user_id UUID REFERENCES auth.users(id),
    alert_type TEXT NOT NULL,       -- 'force_close' | 'warn' | 'correlation' | 'drift'
    severity TEXT NOT NULL,         -- 'critical' | 'high' | 'medium'
    position_id UUID,               -- nullable, links to paper_positions
    symbol TEXT,
    message TEXT NOT NULL,
    resolved BOOLEAN DEFAULT FALSE,
    resolved_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}'
);

-- Index for common queries
CREATE INDEX IF NOT EXISTS idx_risk_alerts_user_created
    ON risk_alerts (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_risk_alerts_unresolved
    ON risk_alerts (user_id, resolved) WHERE resolved = FALSE;

-- RLS: users can only see their own alerts
ALTER TABLE risk_alerts ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users see own alerts" ON risk_alerts
    FOR ALL USING (auth.uid() = user_id);

-- Service role bypass for agent writes
CREATE POLICY "Service role full access" ON risk_alerts
    FOR ALL TO service_role USING (true);
