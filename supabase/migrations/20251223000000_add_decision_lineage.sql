-- Add decision_lineage column to trade_suggestions table
ALTER TABLE trade_suggestions
ADD COLUMN IF NOT EXISTS decision_lineage jsonb;
