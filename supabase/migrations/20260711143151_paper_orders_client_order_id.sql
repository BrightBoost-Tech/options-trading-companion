-- PR2 (2026-07-11): deterministic client_order_id on paper_orders.
-- Enables response-lost resolution — a resubmit under the same
-- client_order_id is a broker-side duplicate REJECT (recoverable by
-- get_order_by_client_id) instead of a phantom second order. The PARTIAL
-- UNIQUE index is a second-line guard against two rows ever sharing an id;
-- mirrors idx_paper_orders_alpaca_id (20260325000000) but unique.
ALTER TABLE paper_orders ADD COLUMN IF NOT EXISTS client_order_id text;

CREATE UNIQUE INDEX IF NOT EXISTS idx_paper_orders_client_order_id
  ON paper_orders(client_order_id) WHERE client_order_id IS NOT NULL;
