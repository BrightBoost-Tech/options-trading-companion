-- Regime Snapshots: Global and Symbol-level regime state tracking
-- Canonical migration (consolidated from duplicate versions)

-- Create regime_snapshots table (Global)
CREATE TABLE IF NOT EXISTS regime_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    as_of_ts TIMESTAMPTZ NOT NULL,
    state TEXT NOT NULL,
    risk_score FLOAT NOT NULL,
    risk_scaler FLOAT NOT NULL,
    components JSONB NOT NULL DEFAULT '{}'::jsonb,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    engine_version TEXT NOT NULL DEFAULT 'v3',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_regime_snapshots_ts ON regime_snapshots(as_of_ts DESC);

-- Create symbol_regime_snapshots table (Symbol-level)
CREATE TABLE IF NOT EXISTS symbol_regime_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol TEXT NOT NULL,
    as_of_ts TIMESTAMPTZ NOT NULL,
    state TEXT NOT NULL,
    score FLOAT NOT NULL,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    quality_flags JSONB NOT NULL DEFAULT '{}'::jsonb,
    engine_version TEXT NOT NULL DEFAULT 'v3',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_symbol_regime_snapshots_ts ON symbol_regime_snapshots(as_of_ts DESC);
CREATE INDEX IF NOT EXISTS idx_symbol_regime_snapshots_symbol ON symbol_regime_snapshots(symbol);
CREATE INDEX IF NOT EXISTS idx_symbol_regime_snapshots_composite ON symbol_regime_snapshots(symbol, as_of_ts DESC);
