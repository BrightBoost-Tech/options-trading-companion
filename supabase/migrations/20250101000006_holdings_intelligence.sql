-- Migration for Phase 8.1 Holdings Intelligence
-- Add new columns to positions table

ALTER TABLE positions
ADD COLUMN IF NOT EXISTS asset_type text,
ADD COLUMN IF NOT EXISTS sector text,
ADD COLUMN IF NOT EXISTS industry text,
ADD COLUMN IF NOT EXISTS strategy_tag text,
ADD COLUMN IF NOT EXISTS is_locked boolean DEFAULT false,
ADD COLUMN IF NOT EXISTS optimizer_role text DEFAULT 'TARGET';

-- Index for faster sector queries
CREATE INDEX IF NOT EXISTS idx_positions_sector ON positions(sector);
CREATE INDEX IF NOT EXISTS idx_positions_asset_type ON positions(asset_type);
