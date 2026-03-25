-- Alpaca broker integration: extend paper_orders for broker tracking,
-- add approval queue for live trading safety layer.

-- 1. Extend paper_orders with broker fields
ALTER TABLE paper_orders ADD COLUMN IF NOT EXISTS alpaca_order_id text;
ALTER TABLE paper_orders ADD COLUMN IF NOT EXISTS execution_mode text DEFAULT 'internal_paper';
ALTER TABLE paper_orders ADD COLUMN IF NOT EXISTS broker_status text;
ALTER TABLE paper_orders ADD COLUMN IF NOT EXISTS broker_response jsonb;

CREATE INDEX IF NOT EXISTS idx_paper_orders_alpaca_id
  ON paper_orders(alpaca_order_id) WHERE alpaca_order_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_paper_orders_execution_mode
  ON paper_orders(execution_mode);

-- 2. Live trading manual approval queue
CREATE TABLE IF NOT EXISTS live_approval_queue (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         uuid NOT NULL,
  order_id        uuid REFERENCES paper_orders(id),
  suggestion_id   uuid,
  cohort_id       uuid,
  order_details   jsonb NOT NULL DEFAULT '{}',
  safety_checks   jsonb NOT NULL DEFAULT '{}',
  status          text DEFAULT 'pending',
  expires_at      timestamptz NOT NULL,
  approved_at     timestamptz,
  rejected_at     timestamptz,
  rejection_reason text,
  created_at      timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_approval_queue_user_status
  ON live_approval_queue(user_id, status) WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_approval_queue_expires
  ON live_approval_queue(expires_at) WHERE status = 'pending';

-- 3. RLS policies
ALTER TABLE live_approval_queue ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own approvals"
  ON live_approval_queue FOR SELECT
  USING (auth.uid() = user_id);

CREATE POLICY "Service role full access approvals"
  ON live_approval_queue FOR ALL
  USING (auth.role() = 'service_role');
