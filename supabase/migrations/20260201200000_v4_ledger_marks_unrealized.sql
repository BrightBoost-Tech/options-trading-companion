-- =============================================================================
-- v4 Portfolio Accounting: Mark Snapshots & Unrealized PnL
-- Phase 1.1: Add position marking infrastructure for real-time PnL
-- =============================================================================
--
-- Tables:
--   position_leg_marks   - Point-in-time mark snapshots for position legs
--
-- Materialized Columns (position_legs):
--   last_mark_id         - FK to most recent mark
--   last_mark_mid        - Cached mid price from last mark
--   last_mark_at         - Timestamp of last mark
--   unrealized_pnl       - Computed unrealized PnL
--
-- Materialized Columns (position_groups):
--   unrealized_pnl       - Sum of leg unrealized PnL
--   net_liquidation_value - Group-level NLV
--
-- Principles:
--   - Additive only (does not modify existing tables beyond adding columns)
--   - Idempotent (safe to re-run)
--   - RLS for user-scoped access
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. POSITION_LEG_MARKS TABLE
-- -----------------------------------------------------------------------------
-- Stores point-in-time market data snapshots for position legs

CREATE TABLE IF NOT EXISTS position_leg_marks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    group_id UUID NOT NULL REFERENCES position_groups(id) ON DELETE CASCADE,
    leg_id UUID NOT NULL REFERENCES position_legs(id) ON DELETE CASCADE,

    -- Instrument identifier (denormalized for query convenience)
    symbol TEXT NOT NULL,

    -- Mark timestamp
    marked_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Quote data at mark time
    bid NUMERIC,
    ask NUMERIC,
    mid NUMERIC,
    last NUMERIC,

    -- Quality metadata
    quality_score INTEGER,
    freshness_ms NUMERIC,

    -- Source of mark
    source TEXT NOT NULL DEFAULT 'MARKET',  -- MARKET, MANUAL, SETTLEMENT, EOD

    -- Additional metadata
    meta_json JSONB DEFAULT '{}'::jsonb,

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes for position_leg_marks
CREATE INDEX IF NOT EXISTS idx_position_leg_marks_user_id ON position_leg_marks(user_id);
CREATE INDEX IF NOT EXISTS idx_position_leg_marks_leg_id ON position_leg_marks(leg_id);
CREATE INDEX IF NOT EXISTS idx_position_leg_marks_group_id ON position_leg_marks(group_id);
CREATE INDEX IF NOT EXISTS idx_position_leg_marks_symbol ON position_leg_marks(user_id, symbol);
CREATE INDEX IF NOT EXISTS idx_position_leg_marks_marked_at ON position_leg_marks(user_id, marked_at DESC);

-- Composite index for finding latest mark per leg
CREATE INDEX IF NOT EXISTS idx_position_leg_marks_leg_latest
    ON position_leg_marks(leg_id, marked_at DESC);

COMMENT ON TABLE position_leg_marks IS 'v4 Accounting: Point-in-time mark snapshots for position legs';

-- -----------------------------------------------------------------------------
-- 2. ADD MATERIALIZED COLUMNS TO POSITION_LEGS
-- -----------------------------------------------------------------------------
-- Add columns for caching latest mark data and unrealized PnL

-- Last mark reference
ALTER TABLE position_legs
    ADD COLUMN IF NOT EXISTS last_mark_id UUID REFERENCES position_leg_marks(id) ON DELETE SET NULL;

-- Cached mark values (denormalized for fast reads)
ALTER TABLE position_legs
    ADD COLUMN IF NOT EXISTS last_mark_mid NUMERIC;

ALTER TABLE position_legs
    ADD COLUMN IF NOT EXISTS last_mark_at TIMESTAMPTZ;

-- Computed unrealized PnL for this leg
-- Formula: LONG: (mark - avg_cost_open) * qty_current * multiplier
--          SHORT: (avg_cost_open - mark) * abs(qty_current) * multiplier
ALTER TABLE position_legs
    ADD COLUMN IF NOT EXISTS unrealized_pnl NUMERIC;

-- Index for unrealized PnL queries
CREATE INDEX IF NOT EXISTS idx_position_legs_unrealized_pnl
    ON position_legs(user_id, unrealized_pnl)
    WHERE unrealized_pnl IS NOT NULL;

-- -----------------------------------------------------------------------------
-- 3. ADD MATERIALIZED COLUMNS TO POSITION_GROUPS
-- -----------------------------------------------------------------------------
-- Add columns for group-level PnL aggregation

-- Sum of leg unrealized PnL
ALTER TABLE position_groups
    ADD COLUMN IF NOT EXISTS unrealized_pnl NUMERIC;

-- Net liquidation value (realized + unrealized)
ALTER TABLE position_groups
    ADD COLUMN IF NOT EXISTS net_liquidation_value NUMERIC;

-- Last mark refresh timestamp for the group
ALTER TABLE position_groups
    ADD COLUMN IF NOT EXISTS last_marked_at TIMESTAMPTZ;

-- Index for NLV queries
CREATE INDEX IF NOT EXISTS idx_position_groups_nlv
    ON position_groups(user_id, net_liquidation_value)
    WHERE net_liquidation_value IS NOT NULL;

-- -----------------------------------------------------------------------------
-- 4. ROW LEVEL SECURITY FOR POSITION_LEG_MARKS
-- -----------------------------------------------------------------------------

ALTER TABLE position_leg_marks ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own position_leg_marks"
    ON position_leg_marks FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own position_leg_marks"
    ON position_leg_marks FOR INSERT
    WITH CHECK (auth.uid() = user_id);

-- Note: No update policy - marks are append-only snapshots
-- Delete allowed for data cleanup

CREATE POLICY "Users can delete own position_leg_marks"
    ON position_leg_marks FOR DELETE
    USING (auth.uid() = user_id);

-- -----------------------------------------------------------------------------
-- 5. HELPER FUNCTIONS
-- -----------------------------------------------------------------------------

-- Function to compute unrealized PnL for a single leg
CREATE OR REPLACE FUNCTION compute_leg_unrealized_pnl(
    p_side leg_side,
    p_avg_cost_open NUMERIC,
    p_mark_mid NUMERIC,
    p_qty_current INTEGER,
    p_multiplier INTEGER
)
RETURNS NUMERIC AS $$
BEGIN
    IF p_mark_mid IS NULL OR p_avg_cost_open IS NULL OR p_qty_current = 0 THEN
        RETURN NULL;
    END IF;

    -- LONG: (mark - cost) * qty * multiplier
    -- SHORT: (cost - mark) * abs(qty) * multiplier
    IF p_side = 'LONG' THEN
        RETURN (p_mark_mid - p_avg_cost_open) * p_qty_current * p_multiplier;
    ELSE
        RETURN (p_avg_cost_open - p_mark_mid) * ABS(p_qty_current) * p_multiplier;
    END IF;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

COMMENT ON FUNCTION compute_leg_unrealized_pnl(leg_side, NUMERIC, NUMERIC, INTEGER, INTEGER)
    IS 'v4 Accounting: Compute unrealized PnL for a position leg';

-- Function to get latest mark for a leg
CREATE OR REPLACE FUNCTION get_latest_leg_mark(p_leg_id UUID)
RETURNS position_leg_marks AS $$
DECLARE
    v_mark position_leg_marks;
BEGIN
    SELECT * INTO v_mark
    FROM position_leg_marks
    WHERE leg_id = p_leg_id
    ORDER BY marked_at DESC
    LIMIT 1;

    RETURN v_mark;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION get_latest_leg_mark(UUID)
    IS 'v4 Accounting: Get the most recent mark for a position leg';

-- -----------------------------------------------------------------------------
-- END OF MIGRATION
-- -----------------------------------------------------------------------------
