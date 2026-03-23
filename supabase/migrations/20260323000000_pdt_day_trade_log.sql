-- PDT Day Trade Log
-- Tracks day trades (same-day open+close) for Pattern Day Trading rule compliance.
-- Under $25K accounts are limited to 3 day trades per rolling 5 business days.

CREATE TABLE IF NOT EXISTS pdt_day_trade_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    position_id UUID NOT NULL,
    symbol TEXT NOT NULL,
    opened_at TIMESTAMPTZ NOT NULL,
    closed_at TIMESTAMPTZ NOT NULL,
    trade_date DATE NOT NULL,         -- Chicago-timezone calendar date of the day trade
    realized_pl NUMERIC,              -- P&L of the closed position (for audit)
    close_reason TEXT,                -- exit condition that triggered the close
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(position_id)               -- each position can only be a day trade once
);

CREATE INDEX IF NOT EXISTS idx_pdt_log_user_date ON pdt_day_trade_log(user_id, trade_date);
