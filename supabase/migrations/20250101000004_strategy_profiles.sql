CREATE TABLE IF NOT EXISTS strategy_configs (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL,
    name TEXT NOT NULL,
    version INT NOT NULL DEFAULT 1,
    description TEXT,
    params JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, name, version)
);

CREATE TABLE IF NOT EXISTS strategy_backtests (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL,
    strategy_name TEXT NOT NULL,
    version INT NOT NULL,
    param_hash TEXT,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    ticker TEXT NOT NULL,
    trades_count INT,
    win_rate FLOAT,
    max_drawdown FLOAT,
    avg_roi FLOAT,
    total_pnl FLOAT,
    metrics JSONB,
    status TEXT DEFAULT 'pending',
    batch_id UUID,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
