-- =============================================================================
-- Replay Feature Store v4
-- Content-addressable blob storage + decision context tracking for deterministic replay
-- =============================================================================

-- 1) data_blobs: Content-addressable store for deduplication
-- Stores canonical JSON payloads (gzip compressed) with sha256 hash as primary key
CREATE TABLE IF NOT EXISTS data_blobs (
    hash TEXT PRIMARY KEY,                          -- sha256 of canonical payload bytes
    compression TEXT NOT NULL DEFAULT 'gzip',       -- compression algorithm
    payload BYTEA NOT NULL,                         -- compressed canonical JSON
    size_bytes INTEGER NOT NULL,                    -- uncompressed size for monitoring
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Index for cleanup queries (oldest blobs)
CREATE INDEX IF NOT EXISTS idx_data_blobs_created_at ON data_blobs (created_at);

COMMENT ON TABLE data_blobs IS 'Content-addressable blob store for replay data deduplication';
COMMENT ON COLUMN data_blobs.hash IS 'SHA256 of canonical (sorted, normalized) JSON bytes';
COMMENT ON COLUMN data_blobs.compression IS 'Compression algorithm (gzip default, zstd optional)';
COMMENT ON COLUMN data_blobs.payload IS 'Gzip-compressed canonical JSON bytes';
COMMENT ON COLUMN data_blobs.size_bytes IS 'Uncompressed payload size for monitoring quotas';

-- 2) decision_runs: Header table for each decision cycle
CREATE TABLE IF NOT EXISTS decision_runs (
    decision_id UUID PRIMARY KEY,
    strategy_name TEXT NOT NULL,                    -- e.g., "suggestions_close", "suggestions_open"
    as_of_ts TIMESTAMPTZ NOT NULL,                  -- decision timestamp
    user_id UUID NULL REFERENCES auth.users(id),   -- optional: user context
    git_sha TEXT NULL,                              -- git commit for reproducibility
    status TEXT NOT NULL DEFAULT 'ok',              -- ok|failed
    error_summary TEXT NULL,                        -- error message if failed
    features_hash TEXT NULL,                        -- sha256 of sorted features_hashes
    input_hash TEXT NULL,                           -- sha256 of sorted blob_hashes
    inputs_count INTEGER NOT NULL DEFAULT 0,        -- count of decision_inputs
    features_count INTEGER NOT NULL DEFAULT 0,      -- count of decision_features
    duration_ms INTEGER NULL,                       -- cycle duration for monitoring
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Index for querying by strategy and time (most common query pattern)
CREATE INDEX IF NOT EXISTS idx_decision_runs_strategy_as_of
    ON decision_runs (strategy_name, as_of_ts DESC);

-- Index for user-specific queries
CREATE INDEX IF NOT EXISTS idx_decision_runs_user_id
    ON decision_runs (user_id) WHERE user_id IS NOT NULL;

-- Index for status monitoring
CREATE INDEX IF NOT EXISTS idx_decision_runs_status
    ON decision_runs (status, created_at DESC);

COMMENT ON TABLE decision_runs IS 'Header table for decision cycles enabling deterministic replay';
COMMENT ON COLUMN decision_runs.decision_id IS 'Unique identifier for this decision cycle';
COMMENT ON COLUMN decision_runs.strategy_name IS 'Strategy/job name (suggestions_close, suggestions_open, etc.)';
COMMENT ON COLUMN decision_runs.as_of_ts IS 'Point-in-time timestamp for the decision';
COMMENT ON COLUMN decision_runs.input_hash IS 'SHA256 of pipe-delimited sorted blob hashes (determinism check)';
COMMENT ON COLUMN decision_runs.features_hash IS 'SHA256 of pipe-delimited sorted feature hashes (determinism check)';

-- 3) decision_inputs: Links decision_runs to data_blobs
CREATE TABLE IF NOT EXISTS decision_inputs (
    decision_id UUID NOT NULL REFERENCES decision_runs(decision_id) ON DELETE CASCADE,
    blob_hash TEXT NOT NULL REFERENCES data_blobs(hash),
    key TEXT NOT NULL,                              -- e.g., "SPY:polygon:snapshot_v4"
    snapshot_type TEXT NOT NULL,                    -- quote|chain|surface|rates_divs|bars|regime
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,    -- quality info, timestamps, provider
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (decision_id, key, snapshot_type)
);

-- Index for blob hash lookups (finding which decisions used a blob)
CREATE INDEX IF NOT EXISTS idx_decision_inputs_blob_hash ON decision_inputs (blob_hash);

-- Index for snapshot_type queries (monitoring data types)
CREATE INDEX IF NOT EXISTS idx_decision_inputs_snapshot_type ON decision_inputs (snapshot_type);

COMMENT ON TABLE decision_inputs IS 'Links decision cycles to content-addressable blob inputs';
COMMENT ON COLUMN decision_inputs.key IS 'Canonical input key (e.g., "SPY:polygon:snapshot_v4")';
COMMENT ON COLUMN decision_inputs.snapshot_type IS 'Data type: quote|chain|surface|rates_divs|bars|regime';
COMMENT ON COLUMN decision_inputs.metadata IS 'Quality metadata (score, issues, freshness_ms), timestamps, provider';

-- 4) decision_features: Computed features for each decision
CREATE TABLE IF NOT EXISTS decision_features (
    decision_id UUID NOT NULL REFERENCES decision_runs(decision_id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,                           -- underlying symbol or "__global__" for regime
    namespace TEXT NOT NULL,                        -- feature category
    features JSONB NOT NULL,                        -- feature values
    features_hash TEXT NOT NULL,                    -- sha256 of canonical features JSON
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (decision_id, symbol, namespace)
);

-- Index for symbol lookups
CREATE INDEX IF NOT EXISTS idx_decision_features_symbol ON decision_features (symbol);

-- Index for namespace queries
CREATE INDEX IF NOT EXISTS idx_decision_features_namespace ON decision_features (namespace);

-- Index for features_hash (finding identical feature sets)
CREATE INDEX IF NOT EXISTS idx_decision_features_hash ON decision_features (features_hash);

COMMENT ON TABLE decision_features IS 'Computed features for each decision cycle';
COMMENT ON COLUMN decision_features.symbol IS 'Symbol or "__global__" for market-wide features';
COMMENT ON COLUMN decision_features.namespace IS 'Feature category: symbol_features|chain_features|regime_features|scoring_features';
COMMENT ON COLUMN decision_features.features_hash IS 'SHA256 of canonical features JSON for determinism verification';

-- =============================================================================
-- RLS Policies (if RLS enabled on these tables)
-- =============================================================================

-- Note: These tables are primarily accessed by service-role key from job handlers
-- If user-scoped access is needed later, enable RLS and add policies

-- ALTER TABLE data_blobs ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE decision_runs ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE decision_inputs ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE decision_features ENABLE ROW LEVEL SECURITY;
