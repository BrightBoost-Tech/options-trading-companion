-- Migration: Ensure portfolio_snapshots columns (holdings, data_source, buying_power)

-- Ensure 'holdings' column exists as JSONB with default '[]'
ALTER TABLE portfolio_snapshots
ADD COLUMN IF NOT EXISTS holdings JSONB NOT NULL DEFAULT '[]'::jsonb;

-- Ensure 'data_source' column exists for tracking origin (e.g., 'plaid', 'manual')
ALTER TABLE portfolio_snapshots
ADD COLUMN IF NOT EXISTS data_source TEXT;

-- Ensure 'buying_power' column exists for cash tracking
ALTER TABLE portfolio_snapshots
ADD COLUMN IF NOT EXISTS buying_power NUMERIC;
