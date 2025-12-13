-- Execution V3 Schema Updates

-- 1. Alter paper_orders
ALTER TABLE paper_orders
ADD COLUMN staged_at TIMESTAMPTZ,
ADD COLUMN submitted_at TIMESTAMPTZ,
ADD COLUMN cancelled_at TIMESTAMPTZ,
ADD COLUMN expired_at TIMESTAMPTZ,
ADD COLUMN requested_qty NUMERIC,
ADD COLUMN requested_price NUMERIC,
ADD COLUMN filled_qty NUMERIC,
ADD COLUMN avg_fill_price NUMERIC,
ADD COLUMN fees_usd NUMERIC DEFAULT 0,
ADD COLUMN side TEXT,
ADD COLUMN order_type TEXT,
ADD COLUMN time_in_force TEXT DEFAULT 'DAY',
ADD COLUMN quote_at_stage JSONB,
ADD COLUMN quote_at_fill JSONB,
ADD COLUMN tcm JSONB,
ADD COLUMN position_id UUID;

-- Add indexes
CREATE INDEX IF NOT EXISTS idx_paper_orders_trace_id ON paper_orders(trace_id);
CREATE INDEX IF NOT EXISTS idx_paper_orders_status ON paper_orders(status);
CREATE INDEX IF NOT EXISTS idx_paper_orders_filled_at ON paper_orders(filled_at);

-- 2. Alter learning_feedback_loops
ALTER TABLE learning_feedback_loops
ADD COLUMN pnl_alpha NUMERIC,
ADD COLUMN pnl_execution_drag NUMERIC,
ADD COLUMN pnl_regime_shift NUMERIC,
ADD COLUMN fees_total NUMERIC,
ADD COLUMN entry_mid NUMERIC,
ADD COLUMN entry_fill NUMERIC,
ADD COLUMN exit_mid NUMERIC,
ADD COLUMN exit_fill NUMERIC;
