-- Migration to enhance trade_executions with trade_suggestions linkage and execution context

-- 1. Handle the transition from suggestion_logs to trade_suggestions
--    We rename the existing suggestion_id to suggestion_log_id to preserve legacy links.
ALTER TABLE trade_executions DROP CONSTRAINT IF EXISTS trade_executions_suggestion_id_fkey;
-- Check if column exists before renaming (idempotency)
DO $$
BEGIN
  IF EXISTS(SELECT 1 FROM information_schema.columns WHERE table_name='trade_executions' AND column_name='suggestion_id') THEN
    ALTER TABLE trade_executions RENAME COLUMN suggestion_id TO suggestion_log_id;
  END IF;
END $$;

-- Add FK for legacy log id if not exists
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints WHERE constraint_name = 'fk_trade_executions_suggestion_log') THEN
    ALTER TABLE trade_executions ADD CONSTRAINT fk_trade_executions_suggestion_log FOREIGN KEY (suggestion_log_id) REFERENCES suggestion_logs(id);
  END IF;
END $$;

-- 2. Add new fields
ALTER TABLE trade_executions ADD COLUMN IF NOT EXISTS suggestion_id uuid REFERENCES trade_suggestions(id);
ALTER TABLE trade_executions ADD COLUMN IF NOT EXISTS trace_id uuid;
ALTER TABLE trade_executions ADD COLUMN IF NOT EXISTS "window" text;
ALTER TABLE trade_executions ADD COLUMN IF NOT EXISTS strategy text;
ALTER TABLE trade_executions ADD COLUMN IF NOT EXISTS model_version text;
ALTER TABLE trade_executions ADD COLUMN IF NOT EXISTS features_hash text;
ALTER TABLE trade_executions ADD COLUMN IF NOT EXISTS regime text;
ALTER TABLE trade_executions ADD COLUMN IF NOT EXISTS mid_price_at_submission numeric;
ALTER TABLE trade_executions ADD COLUMN IF NOT EXISTS target_price numeric;
ALTER TABLE trade_executions ADD COLUMN IF NOT EXISTS order_json jsonb;

-- 3. Create index for trace_id lookups
CREATE INDEX IF NOT EXISTS idx_trade_executions_trace_id ON trade_executions(trace_id);
