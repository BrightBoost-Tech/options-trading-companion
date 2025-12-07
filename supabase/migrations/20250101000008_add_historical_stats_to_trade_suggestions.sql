-- Add historical_stats column for morning suggestions analytics
ALTER TABLE IF EXISTS trade_suggestions
ADD COLUMN IF NOT EXISTS historical_stats JSONB;
