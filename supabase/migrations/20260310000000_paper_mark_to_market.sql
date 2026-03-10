-- Migration: Mark-to-market support for paper trading
-- Adds EOD snapshot table and missing columns on paper_positions.

-- 1. Missing columns on paper_positions (legs, user_id written by code but not in schema)
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS legs jsonb DEFAULT '[]'::jsonb;
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS user_id uuid;

-- 2. New columns for exit evaluation (Phase 2) and mark-to-market tracking
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS max_credit numeric;
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS nearest_expiry date;
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS status text DEFAULT 'open';
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS close_reason text;
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS closed_at timestamptz;
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS realized_pl numeric;

-- 3. EOD snapshot table for daily unrealized P&L tracking
CREATE TABLE IF NOT EXISTS paper_eod_snapshots (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    position_id uuid REFERENCES paper_positions(id) ON DELETE CASCADE,
    user_id uuid NOT NULL,
    portfolio_id uuid NOT NULL,
    snapshot_date date NOT NULL,
    current_mark numeric,
    unrealized_pl numeric DEFAULT 0,
    created_at timestamptz DEFAULT now(),
    UNIQUE(position_id, snapshot_date)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_paper_eod_snapshots_user_date
    ON paper_eod_snapshots(user_id, snapshot_date);
CREATE INDEX IF NOT EXISTS idx_paper_positions_status
    ON paper_positions(status) WHERE status = 'open';
CREATE INDEX IF NOT EXISTS idx_paper_positions_user_id
    ON paper_positions(user_id);

-- RLS for paper_eod_snapshots
ALTER TABLE paper_eod_snapshots ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own snapshots" ON paper_eod_snapshots
    FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "Service can manage snapshots" ON paper_eod_snapshots
    FOR ALL USING (TRUE);
