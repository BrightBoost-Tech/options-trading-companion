-- V3 Backtest Metrics and Event Tables

-- 1. Alter strategy_backtests to add V3 columns
ALTER TABLE strategy_backtests
ADD COLUMN IF NOT EXISTS sharpe FLOAT,
ADD COLUMN IF NOT EXISTS profit_factor FLOAT,
ADD COLUMN IF NOT EXISTS avg_trade_ev FLOAT,
ADD COLUMN IF NOT EXISTS ev_calibration_error FLOAT,
ADD COLUMN IF NOT EXISTS turnover FLOAT,
ADD COLUMN IF NOT EXISTS slippage_paid FLOAT,
ADD COLUMN IF NOT EXISTS fill_rate FLOAT,
ADD COLUMN IF NOT EXISTS engine_version TEXT DEFAULT 'v2',
ADD COLUMN IF NOT EXISTS run_mode TEXT,
ADD COLUMN IF NOT EXISTS train_days INT,
ADD COLUMN IF NOT EXISTS test_days INT,
ADD COLUMN IF NOT EXISTS step_days INT,
ADD COLUMN IF NOT EXISTS seed INT,
ADD COLUMN IF NOT EXISTS data_hash TEXT,
ADD COLUMN IF NOT EXISTS code_sha TEXT;

-- 2. Create strategy_backtest_folds table
CREATE TABLE IF NOT EXISTS strategy_backtest_folds (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    backtest_id UUID REFERENCES strategy_backtests(id) ON DELETE CASCADE,
    fold_index INT NOT NULL,
    train_start DATE,
    train_end DATE,
    test_start DATE,
    test_end DATE,
    train_metrics JSONB, -- Sharpe, etc. on train
    test_metrics JSONB,  -- Sharpe, etc. on test
    optimized_params JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Create strategy_backtest_trades table
CREATE TABLE IF NOT EXISTS strategy_backtest_trades (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    backtest_id UUID REFERENCES strategy_backtests(id) ON DELETE CASCADE,
    fold_id UUID REFERENCES strategy_backtest_folds(id) ON DELETE CASCADE, -- Nullable if single run
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry_date TIMESTAMP,
    exit_date TIMESTAMP,
    entry_price FLOAT,
    exit_price FLOAT,
    quantity FLOAT,
    pnl FLOAT,
    pnl_pct FLOAT,
    commission_paid FLOAT,
    slippage_paid FLOAT,
    exit_reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 4. Create strategy_backtest_trade_events table
CREATE TABLE IF NOT EXISTS strategy_backtest_trade_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trade_id UUID, -- Can link to strategy_backtest_trades(id) or just be a loose correlation ID
    backtest_id UUID REFERENCES strategy_backtests(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL, -- ENTRY_FILLED, EXIT_FILLED, ADJUSTMENT, etc.
    event_date TIMESTAMP NOT NULL,
    price FLOAT,
    quantity FLOAT,
    details JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_strategy_backtests_user_strategy_v3
ON strategy_backtests(user_id, strategy_name, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_backtest_folds_backtest_id
ON strategy_backtest_folds(backtest_id, fold_index);

CREATE INDEX IF NOT EXISTS idx_backtest_trades_backtest_id
ON strategy_backtest_trades(backtest_id);

CREATE INDEX IF NOT EXISTS idx_backtest_events_trade_id
ON strategy_backtest_trade_events(trade_id, event_date);
