-- P6: Add config_hash column for strategy configuration fingerprinting
-- Enables deduplication and reproducibility verification for backtests

ALTER TABLE strategy_backtests
ADD COLUMN IF NOT EXISTS config_hash TEXT;

-- Index for dedupe queries (user + strategy + config_hash)
CREATE INDEX IF NOT EXISTS idx_strategy_backtests_config_hash
ON strategy_backtests(user_id, strategy_name, config_hash, created_at DESC);
