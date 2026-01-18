-- v4 Observability Migration: Cryptographic Lineage & Audit Log
-- Adds immutable audit logging, XAI attributions, and lineage verification

-- =============================================================================
-- 1. Extend trade_suggestions with lineage verification fields
-- =============================================================================

ALTER TABLE trade_suggestions
ADD COLUMN IF NOT EXISTS lineage_hash text NULL,
ADD COLUMN IF NOT EXISTS lineage_sig text NULL,
ADD COLUMN IF NOT EXISTS lineage_version text NOT NULL DEFAULT 'v4',
ADD COLUMN IF NOT EXISTS code_sha text NULL,
ADD COLUMN IF NOT EXISTS data_hash text NULL;

-- Index for integrity verification queries
CREATE INDEX IF NOT EXISTS idx_suggestions_lineage_hash ON trade_suggestions (lineage_hash);

-- =============================================================================
-- 2. Create decision_audit_events table (append-only immutable audit log)
-- =============================================================================

CREATE TABLE IF NOT EXISTS decision_audit_events (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at timestamptz DEFAULT now() NOT NULL,
    user_id uuid NOT NULL,
    trace_id uuid NOT NULL,
    suggestion_id uuid REFERENCES trade_suggestions(id) ON DELETE SET NULL,
    event_name text NOT NULL,
    payload jsonb NOT NULL,
    payload_hash text NOT NULL,
    payload_sig text NOT NULL,
    prev_hash text NULL,  -- For future chaining: sha256(prev_row.payload_hash) for tamper-evident linked list
    strategy text NULL,
    regime text NULL
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_audit_trace_id ON decision_audit_events (trace_id);
CREATE INDEX IF NOT EXISTS idx_audit_suggestion_id ON decision_audit_events (suggestion_id);
CREATE INDEX IF NOT EXISTS idx_audit_created_at ON decision_audit_events (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_event_name ON decision_audit_events (event_name, created_at DESC);

-- =============================================================================
-- 3. Create xai_attributions table (explainability/why)
-- =============================================================================

CREATE TABLE IF NOT EXISTS xai_attributions (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    suggestion_id uuid REFERENCES trade_suggestions(id) ON DELETE CASCADE NOT NULL,
    trace_id uuid NOT NULL,
    computed_at timestamptz DEFAULT now(),
    drivers_regime jsonb NULL,       -- {global: "normal", local: "elevated", effective: "elevated"}
    drivers_risk jsonb NULL,         -- {budget_used_pct: 45, remaining: 1500, status: "ok"}
    drivers_constraints jsonb NULL,  -- {active: {...}, vetoed: [...]}
    drivers_agents jsonb NULL        -- [{name: "SizingAgent", score: 72, ...}, ...]
    -- Future: drivers_shap jsonb NULL for SHAP values
);

CREATE INDEX IF NOT EXISTS idx_xai_suggestion_id ON xai_attributions (suggestion_id);
CREATE INDEX IF NOT EXISTS idx_xai_trace_id ON xai_attributions (trace_id);

-- =============================================================================
-- 4. Immutability Enforcement for decision_audit_events
-- =============================================================================

-- Enable RLS
ALTER TABLE decision_audit_events ENABLE ROW LEVEL SECURITY;

-- Allow users to view their own audit events
CREATE POLICY "Users can view their own audit events"
ON decision_audit_events FOR SELECT
USING (auth.uid() = user_id);

-- Allow authenticated users to insert audit events (for their own user_id)
CREATE POLICY "Users can insert their own audit events"
ON decision_audit_events FOR INSERT
WITH CHECK (auth.uid() = user_id);

-- Allow service role to insert any audit events (for background jobs)
CREATE POLICY "Service role can insert audit events"
ON decision_audit_events FOR INSERT
TO service_role
WITH CHECK (true);

-- Allow service role to select all audit events
CREATE POLICY "Service role can select audit events"
ON decision_audit_events FOR SELECT
TO service_role
USING (true);

-- Trigger to prevent UPDATE/DELETE (immutability)
CREATE OR REPLACE FUNCTION prevent_audit_modification()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'decision_audit_events is immutable: % operation not allowed', TG_OP;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS enforce_audit_immutability ON decision_audit_events;

CREATE TRIGGER enforce_audit_immutability
BEFORE UPDATE OR DELETE ON decision_audit_events
FOR EACH ROW
EXECUTE FUNCTION prevent_audit_modification();

-- =============================================================================
-- 5. RLS for xai_attributions
-- =============================================================================

ALTER TABLE xai_attributions ENABLE ROW LEVEL SECURITY;

-- Users can view XAI for suggestions they own (via join)
CREATE POLICY "Users can view their own XAI attributions"
ON xai_attributions FOR SELECT
USING (
    EXISTS (
        SELECT 1 FROM trade_suggestions ts
        WHERE ts.id = xai_attributions.suggestion_id
        AND ts.user_id = auth.uid()
    )
);

-- Allow service role full access for background writes
CREATE POLICY "Service role can manage xai_attributions"
ON xai_attributions FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

-- =============================================================================
-- 6. View for trace lifecycle (convenience)
-- =============================================================================

CREATE OR REPLACE VIEW trace_lifecycle_v4 AS
SELECT
    ts.trace_id,
    ts.id AS suggestion_id,
    ts.user_id,
    ts.created_at AS suggestion_time,
    ts.ticker,
    ts.strategy,
    ts.window,
    ts.regime,
    ts.model_version,
    ts.features_hash,
    ts.lineage_hash,
    ts.lineage_sig,
    ts.lineage_version,
    ts.code_sha,
    ts.decision_lineage,
    ts.ev AS predicted_ev,
    xa.id AS attribution_id,
    xa.drivers_regime,
    xa.drivers_risk,
    xa.drivers_constraints,
    xa.drivers_agents,
    (SELECT COUNT(*) FROM decision_audit_events dae WHERE dae.trace_id = ts.trace_id) AS audit_event_count
FROM trade_suggestions ts
LEFT JOIN xai_attributions xa ON ts.id = xa.suggestion_id;
