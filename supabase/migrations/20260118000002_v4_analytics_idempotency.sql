-- v4 Observability Wave 1.2: Analytics Events Idempotency
-- Mirrors decision_audit_events idempotency from Wave 1.1

-- =============================================================================
-- 1. ANALYTICS EVENT IDEMPOTENCY: Add event_key column with unique constraint
-- =============================================================================

-- Add event_key column (nullable first for backfill)
ALTER TABLE analytics_events
ADD COLUMN IF NOT EXISTS event_key text;

-- Backfill existing rows with deterministic event_key:
-- Priority: suggestion_id:event_name > trace_id:event_name:timestamp > id:event_name
UPDATE analytics_events
SET event_key = CASE
    WHEN suggestion_id IS NOT NULL THEN
        encode(sha256((suggestion_id::text || ':' || event_name)::bytea), 'hex')
    WHEN trace_id IS NOT NULL THEN
        encode(sha256((trace_id::text || ':' || event_name || ':' || COALESCE(timestamp::text, created_at::text, id::text))::bytea), 'hex')
    ELSE
        encode(sha256((id::text || ':' || event_name)::bytea), 'hex')
END
WHERE event_key IS NULL;

-- Now make it NOT NULL
ALTER TABLE analytics_events
ALTER COLUMN event_key SET NOT NULL;

-- Add unique index on event_key for idempotency
CREATE UNIQUE INDEX IF NOT EXISTS idx_analytics_event_key_unique
ON analytics_events(event_key);

-- Supporting index for common lookups
CREATE INDEX IF NOT EXISTS idx_analytics_suggestion_event
ON analytics_events(suggestion_id, event_name);

CREATE INDEX IF NOT EXISTS idx_analytics_trace_event
ON analytics_events(trace_id, event_name);

-- =============================================================================
-- 2. COMMENT: Document Wave 1.2 constraints
-- =============================================================================

COMMENT ON COLUMN analytics_events.event_key IS 'Wave 1.2: Idempotency key computed as sha256(suggestion_id:event_name) for suggestion-scoped events, or sha256(trace_id:event_name:timestamp) for trace-scoped events';
COMMENT ON INDEX idx_analytics_event_key_unique IS 'Wave 1.2: Ensures idempotent analytics event insertion';
