-- Migration to add decision_logs and outcome attribution fields

CREATE TABLE IF NOT EXISTS decision_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id UUID NOT NULL,
    user_id UUID NOT NULL,
    decision_type VARCHAR(50) NOT NULL, -- 'optimizer_weights', 'sizing', 'manual_override'
    content JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT fk_decision_logs_trace FOREIGN KEY (trace_id) REFERENCES inference_log(trace_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_decision_logs_trace_id ON decision_logs(trace_id);
CREATE INDEX IF NOT EXISTS idx_decision_logs_user_id ON decision_logs(user_id);

-- Enable RLS
ALTER TABLE decision_logs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view their own decision logs"
ON decision_logs FOR SELECT
USING (auth.uid() = user_id);

CREATE POLICY "Users can insert their own decision logs"
ON decision_logs FOR INSERT
WITH CHECK (auth.uid() = user_id);

-- Update outcomes_log to support attribution
ALTER TABLE outcomes_log
ADD COLUMN IF NOT EXISTS attribution_type VARCHAR(50) DEFAULT 'portfolio_snapshot', -- 'portfolio_snapshot', 'execution', 'no_action'
ADD COLUMN IF NOT EXISTS related_id UUID, -- suggestion_id or execution_id
ADD COLUMN IF NOT EXISTS decision_trace_id UUID; -- Redundant but useful for direct joins if trace_id in outcomes_log is unique per outcome

CREATE INDEX IF NOT EXISTS idx_outcomes_log_related_id ON outcomes_log(related_id);
