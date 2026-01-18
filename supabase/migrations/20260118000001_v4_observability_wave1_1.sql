-- v4 Observability Wave 1.1: Idempotency + Immutability Enforcement
-- Closes gaps for institutional-grade auditability

-- =============================================================================
-- 1. AUDIT EVENT IDEMPOTENCY: Add event_key column with unique constraint
-- =============================================================================

-- Add event_key column (nullable first for backfill)
ALTER TABLE decision_audit_events
ADD COLUMN IF NOT EXISTS event_key text;

-- Backfill existing rows: use payload_hash as event_key (good enough for existing data)
UPDATE decision_audit_events
SET event_key = payload_hash
WHERE event_key IS NULL;

-- Now make it NOT NULL
ALTER TABLE decision_audit_events
ALTER COLUMN event_key SET NOT NULL;

-- Add unique index on event_key for idempotency
CREATE UNIQUE INDEX IF NOT EXISTS idx_audit_event_key_unique
ON decision_audit_events(event_key);

-- Supporting index for common lookups
CREATE INDEX IF NOT EXISTS idx_audit_suggestion_event
ON decision_audit_events(suggestion_id, event_name);

-- =============================================================================
-- 2. TRADE_SUGGESTIONS IMMUTABILITY: Prevent updating integrity fields
-- =============================================================================

-- Create trigger function to protect integrity fields
CREATE OR REPLACE FUNCTION prevent_suggestion_integrity_update()
RETURNS TRIGGER AS $$
BEGIN
    -- Wave 1.1: Protect lineage integrity fields from modification after insert
    -- These fields form the cryptographic audit trail and must be immutable
    IF (NEW.lineage_hash IS DISTINCT FROM OLD.lineage_hash) OR
       (NEW.lineage_sig IS DISTINCT FROM OLD.lineage_sig) OR
       (NEW.decision_lineage IS DISTINCT FROM OLD.decision_lineage) OR
       (NEW.trace_id IS DISTINCT FROM OLD.trace_id) OR
       (NEW.code_sha IS DISTINCT FROM OLD.code_sha) OR
       (NEW.data_hash IS DISTINCT FROM OLD.data_hash)
    THEN
        RAISE EXCEPTION 'trade_suggestions integrity fields are immutable: lineage_hash, lineage_sig, decision_lineage, trace_id, code_sha, data_hash cannot be modified after insert';
    END IF;

    -- Allow updates to other fields (status, sizing_metadata, etc.)
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Drop trigger if exists (for idempotent migration)
DROP TRIGGER IF EXISTS enforce_suggestion_integrity ON trade_suggestions;

-- Create the trigger
CREATE TRIGGER enforce_suggestion_integrity
BEFORE UPDATE ON trade_suggestions
FOR EACH ROW
EXECUTE FUNCTION prevent_suggestion_integrity_update();

-- =============================================================================
-- 3. TRACE_ID UNIQUENESS: Ensure unambiguous trace lookups
-- =============================================================================

-- Add unique index on trace_id (only for non-null values)
-- This ensures GET /observability/trace/{trace_id} returns unambiguous results
CREATE UNIQUE INDEX IF NOT EXISTS idx_trade_suggestions_trace_id_unique
ON trade_suggestions(trace_id)
WHERE trace_id IS NOT NULL;

-- =============================================================================
-- 4. XAI_ATTRIBUTIONS IDEMPOTENCY: One attribution per suggestion
-- =============================================================================

-- Add unique index on suggestion_id (only one XAI record per suggestion)
CREATE UNIQUE INDEX IF NOT EXISTS idx_xai_suggestion_unique
ON xai_attributions(suggestion_id);

-- =============================================================================
-- 5. COMMENT: Document Wave 1.1 constraints
-- =============================================================================

COMMENT ON COLUMN decision_audit_events.event_key IS 'Wave 1.1: Idempotency key computed as sha256(suggestion_id:event_name) or sha256(trace_id:event_name:payload_hash)';
COMMENT ON TRIGGER enforce_suggestion_integrity ON trade_suggestions IS 'Wave 1.1: Prevents modification of lineage integrity fields after insert';
COMMENT ON INDEX idx_trade_suggestions_trace_id_unique IS 'Wave 1.1: Ensures unambiguous trace lookups';
COMMENT ON INDEX idx_xai_suggestion_unique IS 'Wave 1.1: One XAI attribution per suggestion for idempotency';
