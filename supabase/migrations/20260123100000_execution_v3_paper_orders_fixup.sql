-- Migration: 20260123100000_execution_v3_paper_orders_fixup.sql
-- Purpose: Apply execution_v3 columns to paper_orders AFTER paper_trading migration creates the table.
-- This migration is idempotent and safe for all environments.

-- Add execution v3 columns to paper_orders (IF NOT EXISTS for idempotency)
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

-- Add indexes (IF NOT EXISTS for idempotency)
CREATE INDEX IF NOT EXISTS idx_paper_orders_trace_id ON paper_orders(trace_id);
CREATE INDEX IF NOT EXISTS idx_paper_orders_status ON paper_orders(status);
CREATE INDEX IF NOT EXISTS idx_paper_orders_filled_at ON paper_orders(filled_at);

-- Ensure fees_usd has DEFAULT 0 if it was added without default
DO $$
BEGIN
  -- Set default if not already set
  ALTER TABLE paper_orders ALTER COLUMN fees_usd SET DEFAULT 0;
EXCEPTION
  WHEN others THEN NULL;
END $$;
