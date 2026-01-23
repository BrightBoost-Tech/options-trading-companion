-- Migration: 20250101000011_execution_v3.sql
-- Re-versioned to run AFTER paper_trading (000009) creates paper_orders
-- All operations are idempotent (IF NOT EXISTS / ADD COLUMN IF NOT EXISTS)

-- 1. Alter paper_orders (now exists since paper_trading ran first)
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
  ADD COLUMN IF NOT EXISTS position_id UUID,
  ADD COLUMN IF NOT EXISTS trace_id UUID;

-- Add indexes
CREATE INDEX IF NOT EXISTS idx_paper_orders_trace_id ON paper_orders(trace_id);
CREATE INDEX IF NOT EXISTS idx_paper_orders_status ON paper_orders(status);
CREATE INDEX IF NOT EXISTS idx_paper_orders_filled_at ON paper_orders(filled_at);

-- 2. Alter learning_feedback_loops (idempotent)
ALTER TABLE learning_feedback_loops
  ADD COLUMN IF NOT EXISTS pnl_alpha NUMERIC,
  ADD COLUMN IF NOT EXISTS pnl_execution_drag NUMERIC,
  ADD COLUMN IF NOT EXISTS pnl_regime_shift NUMERIC,
  ADD COLUMN IF NOT EXISTS fees_total NUMERIC,
  ADD COLUMN IF NOT EXISTS entry_mid NUMERIC,
  ADD COLUMN IF NOT EXISTS entry_fill NUMERIC,
  ADD COLUMN IF NOT EXISTS exit_mid NUMERIC,
  ADD COLUMN IF NOT EXISTS exit_fill NUMERIC;
