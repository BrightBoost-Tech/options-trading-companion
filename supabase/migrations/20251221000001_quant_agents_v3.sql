-- Quant Agents v3: Add agent artifact columns to trade_suggestions

ALTER TABLE trade_suggestions ADD COLUMN IF NOT EXISTS agent_signals JSONB;
ALTER TABLE trade_suggestions ADD COLUMN IF NOT EXISTS agent_summary JSONB;
