-- =============================================================================
-- v4 Accounting Fix: Fill Action Semantics
-- Additive migration to correct fill action vs leg orientation model
-- =============================================================================
--
-- Problem:
--   Original schema mapped BUY→LONG and SELL→SHORT, conflating fill action
--   with leg orientation. This caused closing trades to create phantom legs.
--
-- Solution:
--   - Add fill_action enum (BUY, SELL) for per-execution action
--   - Add fills.action column to store the actual trade action
--   - Leg orientation (LONG/SHORT) remains stable property of position_legs.side
--   - Code will resolve legs by (group_id, symbol) only, not by side
--
-- Principles:
--   - Additive only (does not modify original ledger migration)
--   - Safe to re-run (idempotent)
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. CREATE FILL_ACTION ENUM
-- -----------------------------------------------------------------------------

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'fill_action') THEN
        CREATE TYPE fill_action AS ENUM ('BUY', 'SELL');
    END IF;
END $$;

-- -----------------------------------------------------------------------------
-- 2. ADD ACTION COLUMN TO FILLS TABLE
-- -----------------------------------------------------------------------------

-- Add action column with default 'BUY' (safe for existing rows)
-- The default allows existing NULL rows to be backfilled
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'fills' AND column_name = 'action'
    ) THEN
        ALTER TABLE fills ADD COLUMN action fill_action;
    END IF;
END $$;

-- -----------------------------------------------------------------------------
-- 3. BACKFILL EXISTING FILLS (if any)
-- -----------------------------------------------------------------------------
-- Map existing fills.side to action:
--   LONG -> BUY (opening a long = buying)
--   SHORT -> SELL (opening a short = selling)
-- Note: This is a best-effort backfill for any existing data.
-- New code will set action explicitly.

UPDATE fills
SET action = CASE
    WHEN side = 'LONG' THEN 'BUY'::fill_action
    WHEN side = 'SHORT' THEN 'SELL'::fill_action
    ELSE 'BUY'::fill_action
END
WHERE action IS NULL;

-- -----------------------------------------------------------------------------
-- 4. SET DEFAULT AND NOT NULL (after backfill)
-- -----------------------------------------------------------------------------

-- Set default for new inserts
ALTER TABLE fills ALTER COLUMN action SET DEFAULT 'BUY'::fill_action;

-- Make column NOT NULL (safe after backfill)
DO $$
BEGIN
    -- Check if column is already NOT NULL
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'fills'
        AND column_name = 'action'
        AND is_nullable = 'YES'
    ) THEN
        ALTER TABLE fills ALTER COLUMN action SET NOT NULL;
    END IF;
END $$;

-- -----------------------------------------------------------------------------
-- 5. ADD INDEX ON ACTION (optional, for filtering)
-- -----------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_fills_action ON fills(action);

-- -----------------------------------------------------------------------------
-- 6. ADD COMMENT
-- -----------------------------------------------------------------------------

COMMENT ON COLUMN fills.action IS 'Fill action: BUY or SELL. Distinct from position_legs.side which indicates leg orientation (LONG/SHORT).';

-- -----------------------------------------------------------------------------
-- END OF MIGRATION
-- -----------------------------------------------------------------------------
