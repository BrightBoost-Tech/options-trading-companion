-- Add canonical ranking column to trade_suggestions.
-- Populated at suggestion creation time by canonical_ranker.py.
-- Higher values = better risk-adjusted opportunity.

ALTER TABLE trade_suggestions
  ADD COLUMN IF NOT EXISTS risk_adjusted_ev NUMERIC;

-- Index for sorting by canonical ranking (most queries order desc)
CREATE INDEX IF NOT EXISTS idx_trade_suggestions_risk_adjusted_ev
  ON trade_suggestions(risk_adjusted_ev DESC NULLS LAST);

-- Notify PostgREST to pick up the new column immediately
NOTIFY pgrst, 'reload schema';
