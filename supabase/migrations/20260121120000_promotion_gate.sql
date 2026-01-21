-- P7: Add promotion gate columns for paper→micro-live→live readiness
-- Enables tracking of backtest promotion eligibility based on metrics thresholds

ALTER TABLE strategy_backtests
ADD COLUMN IF NOT EXISTS eligible_micro_live BOOLEAN,
ADD COLUMN IF NOT EXISTS eligible_live BOOLEAN,
ADD COLUMN IF NOT EXISTS promotion_tier TEXT,
ADD COLUMN IF NOT EXISTS promotion_reasons JSONB;

-- Index for promotion queries (user + promotion status)
CREATE INDEX IF NOT EXISTS idx_strategy_backtests_promotion
ON strategy_backtests(user_id, strategy_name, promotion_tier, eligible_live)
WHERE eligible_micro_live = true OR eligible_live = true;
