-- Phase 2.1.1: Add structured event columns to paper_ledger
-- Aligns schema with PaperLedgerService (PR #559)
--
-- New columns:
--   event_type: Structured event type (deposit, withdraw, fill, partial_fill, close, fee, etc.)
--   order_id: Link to paper_orders.id
--   position_id: Link to paper_positions.id
--   trace_id: Trace ID for observability
--   metadata: JSONB for structured context (side, qty, price, symbol, fees, etc.)

-- Add columns (idempotent)
ALTER TABLE paper_ledger ADD COLUMN IF NOT EXISTS event_type TEXT;
ALTER TABLE paper_ledger ADD COLUMN IF NOT EXISTS order_id UUID;
ALTER TABLE paper_ledger ADD COLUMN IF NOT EXISTS position_id UUID;
ALTER TABLE paper_ledger ADD COLUMN IF NOT EXISTS trace_id TEXT;
ALTER TABLE paper_ledger ADD COLUMN IF NOT EXISTS metadata JSONB;

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_paper_ledger_portfolio_created_at
    ON paper_ledger(portfolio_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_paper_ledger_event_type
    ON paper_ledger(event_type)
    WHERE event_type IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_paper_ledger_order_id
    ON paper_ledger(order_id)
    WHERE order_id IS NOT NULL;
