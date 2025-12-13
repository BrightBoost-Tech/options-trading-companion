-- Create regime_snapshots table (Global)
CREATE TABLE IF NOT EXISTS regime_snapshots (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    as_of_ts TIMESTAMPTZ NOT NULL,
    state TEXT NOT NULL,
    risk_score NUMERIC NOT NULL,
    risk_scaler NUMERIC NOT NULL,
    features JSONB NOT NULL DEFAULT '{}'::jsonb,
    engine_version TEXT NOT NULL DEFAULT 'v3',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_regime_snapshots_ts ON regime_snapshots(as_of_ts DESC);

-- Create symbol_regime_snapshots table (Symbol)
CREATE TABLE IF NOT EXISTS symbol_regime_snapshots (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    symbol TEXT NOT NULL,
    as_of_ts TIMESTAMPTZ NOT NULL,
    state TEXT NOT NULL,
    symbol_score NUMERIC NOT NULL,
    features JSONB NOT NULL DEFAULT '{}'::jsonb,
    quality_flags JSONB NOT NULL DEFAULT '{}'::jsonb,
    engine_version TEXT NOT NULL DEFAULT 'v3',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_symbol_regime_snapshots_ts ON symbol_regime_snapshots(as_of_ts DESC);
CREATE INDEX IF NOT EXISTS idx_symbol_regime_snapshots_symbol ON symbol_regime_snapshots(symbol);
CREATE INDEX IF NOT EXISTS idx_symbol_regime_snapshots_composite ON symbol_regime_snapshots(symbol, as_of_ts DESC);
