-- Execution V3 Schema Updates

-- 1. Alter paper_orders (guarded: table may not exist yet if paper_trading migration runs later)
DO $$
BEGIN
  IF to_regclass('public.paper_orders') IS NOT NULL THEN
    ALTER TABLE paper_orders
      ADD COLUMN IF NOT EXISTS staged_at TIMESTAMPTZ,
      ADD COLUMN IF NOT EXISTS submitted_at TIMESTAMPTZ,
      ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMPTZ,
      ADD COLUMN IF NOT EXISTS expired_at TIMESTAMPTZ,
      ADD COLUMN IF NOT EXISTS requested_qty NUMERIC,
      ADD COLUMN IF NOT EXISTS requested_price NUMERIC,
      ADD COLUMN IF NOT EXISTS filled_qty NUMERIC,
      ADD COLUMN IF NOT EXISTS avg_fill_price NUMERIC,
      ADD COLUMN IF NOT EXISTS fees_usd NUMERIC DEFAULT 0,
      ADD COLUMN IF NOT EXISTS side TEXT,
      ADD COLUMN IF NOT EXISTS order_type TEXT,
      ADD COLUMN IF NOT EXISTS time_in_force TEXT DEFAULT 'DAY',
      ADD COLUMN IF NOT EXISTS quote_at_stage JSONB,
      ADD COLUMN IF NOT EXISTS quote_at_fill JSONB,
      ADD COLUMN IF NOT EXISTS tcm JSONB,
      ADD COLUMN IF NOT EXISTS position_id UUID;

    -- Add indexes (only if table exists)
    CREATE INDEX IF NOT EXISTS idx_paper_orders_trace_id ON paper_orders(trace_id);
    CREATE INDEX IF NOT EXISTS idx_paper_orders_status ON paper_orders(status);
    CREATE INDEX IF NOT EXISTS idx_paper_orders_filled_at ON paper_orders(filled_at);
  END IF;
END $$;

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
