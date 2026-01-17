-- =============================================================================
-- Task Nonces Table for Replay Protection (Security v4)
-- =============================================================================
-- This table stores used nonces to prevent replay attacks on /tasks/* endpoints.
-- Each nonce is associated with a scope and timestamp, with automatic cleanup.

CREATE TABLE IF NOT EXISTS task_nonces (
    -- Composite primary key: nonce + scope (same nonce can be used for different scopes)
    nonce TEXT NOT NULL,
    scope TEXT NOT NULL,

    -- Metadata
    ts BIGINT NOT NULL,           -- Unix timestamp when nonce was used
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,

    PRIMARY KEY (nonce, scope)
);

-- Index for cleanup queries
CREATE INDEX IF NOT EXISTS idx_task_nonces_expires_at ON task_nonces(expires_at);

-- Index for scope-based queries (useful for monitoring)
CREATE INDEX IF NOT EXISTS idx_task_nonces_scope ON task_nonces(scope);

-- =============================================================================
-- Automatic Cleanup Function
-- =============================================================================
-- Removes expired nonces. Should be called periodically via pg_cron or similar.

CREATE OR REPLACE FUNCTION cleanup_expired_task_nonces()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM task_nonces
    WHERE expires_at < NOW();

    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- =============================================================================
-- RLS Policies
-- =============================================================================
-- This table is service-role only - no user access.

ALTER TABLE task_nonces ENABLE ROW LEVEL SECURITY;

-- No policies = no access for anon/authenticated roles
-- Only service_role can insert/select (bypasses RLS)

-- =============================================================================
-- Comments
-- =============================================================================

COMMENT ON TABLE task_nonces IS 'Stores used nonces for HMAC request signing replay protection (Security v4)';
COMMENT ON COLUMN task_nonces.nonce IS 'Unique nonce value (hex string, typically 32 chars)';
COMMENT ON COLUMN task_nonces.scope IS 'Scope string the nonce was used for (e.g., tasks:suggestions_open)';
COMMENT ON COLUMN task_nonces.ts IS 'Unix timestamp from the request';
COMMENT ON COLUMN task_nonces.expires_at IS 'When this nonce record can be safely deleted';
