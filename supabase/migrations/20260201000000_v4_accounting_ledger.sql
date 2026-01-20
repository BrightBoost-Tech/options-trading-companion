-- =============================================================================
-- v4 Portfolio Accounting & Reconciliation Ledger
-- Phase 1: Schema for canonical position tracking with multi-leg strategy support
-- =============================================================================
--
-- Tables:
--   position_groups    - Strategy-level position grouping (e.g., iron condor as 1 group)
--   position_legs      - Individual leg-level positions within a group
--   fills              - Execution fills linked to legs
--   position_events    - Append-only event log (FILL, ASSIGNMENT, EXERCISE, EXPIRATION, etc.)
--   reconciliation_breaks - Discrepancies between ledger and broker snapshot
--
-- Principles:
--   - Additive only (does not modify existing tables)
--   - Idempotent (safe to re-run)
--   - RLS for user-scoped access, service_role bypasses for background jobs
--   - legs_fingerprint used for consistent multi-leg grouping
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. ENUMS
-- -----------------------------------------------------------------------------

-- Position group status
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'position_group_status') THEN
        CREATE TYPE position_group_status AS ENUM ('OPEN', 'CLOSED', 'ASSIGNED', 'EXPIRED');
    END IF;
END $$;

-- Position event types
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'position_event_type') THEN
        CREATE TYPE position_event_type AS ENUM (
            'FILL',
            'ASSIGNMENT',
            'EXERCISE',
            'EXPIRATION',
            'CASH_ADJ',
            'CORP_ACTION'
        );
    END IF;
END $$;

-- Reconciliation break types
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'reconciliation_break_type') THEN
        CREATE TYPE reconciliation_break_type AS ENUM (
            'QTY_MISMATCH',
            'MISSING_IN_LEDGER',
            'MISSING_IN_BROKER',
            'PRICE_MISMATCH'
        );
    END IF;
END $$;

-- Fill source
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'fill_source') THEN
        CREATE TYPE fill_source AS ENUM ('LIVE', 'PAPER', 'BACKFILL', 'MANUAL');
    END IF;
END $$;

-- Leg side
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'leg_side') THEN
        CREATE TYPE leg_side AS ENUM ('LONG', 'SHORT');
    END IF;
END $$;

-- Option right
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'option_right') THEN
        CREATE TYPE option_right AS ENUM ('C', 'P', 'S');  -- Call, Put, Stock/Share
    END IF;
END $$;

-- -----------------------------------------------------------------------------
-- 2. POSITION_GROUPS TABLE
-- -----------------------------------------------------------------------------
-- Strategy-level grouping (e.g., all legs of an iron condor = 1 group)

CREATE TABLE IF NOT EXISTS position_groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

    -- Grouping keys
    strategy_key TEXT,                          -- e.g., "AAPL_iron_condor"
    legs_fingerprint TEXT,                      -- Hash of leg symbols for consistent grouping
    underlying TEXT NOT NULL,                   -- e.g., "AAPL"

    -- Traceability (from suggestion/execution context)
    trace_id UUID,
    features_hash TEXT,
    model_version TEXT,
    window TEXT,                                -- e.g., "earnings_pre", "paper"
    strategy TEXT,                              -- e.g., "iron_condor", "vertical_call"
    regime TEXT,                                -- Market regime at open

    -- Status
    status position_group_status NOT NULL DEFAULT 'OPEN',
    opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at TIMESTAMPTZ,

    -- Materialized P&L (updated on fill/event)
    realized_pnl NUMERIC,                       -- Net realized P&L after closes
    gross_pnl NUMERIC,                          -- Gross before fees
    fees_paid NUMERIC DEFAULT 0,                -- Cumulative fees

    -- Metadata
    meta_json JSONB DEFAULT '{}'::jsonb,

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes for position_groups
CREATE INDEX IF NOT EXISTS idx_position_groups_user_id ON position_groups(user_id);
CREATE INDEX IF NOT EXISTS idx_position_groups_status ON position_groups(user_id, status);
CREATE INDEX IF NOT EXISTS idx_position_groups_trace_id ON position_groups(trace_id);
CREATE INDEX IF NOT EXISTS idx_position_groups_fingerprint ON position_groups(user_id, legs_fingerprint) WHERE legs_fingerprint IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_position_groups_strategy_key ON position_groups(user_id, strategy_key, underlying) WHERE status = 'OPEN';
CREATE INDEX IF NOT EXISTS idx_position_groups_underlying ON position_groups(user_id, underlying);

-- Updated_at trigger for position_groups
CREATE OR REPLACE FUNCTION update_position_groups_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_position_groups_updated_at_trigger ON position_groups;
CREATE TRIGGER update_position_groups_updated_at_trigger
    BEFORE UPDATE ON position_groups
    FOR EACH ROW
    EXECUTE FUNCTION update_position_groups_updated_at();

COMMENT ON TABLE position_groups IS 'v4 Accounting: Strategy-level position groups with multi-leg support';

-- -----------------------------------------------------------------------------
-- 3. POSITION_LEGS TABLE
-- -----------------------------------------------------------------------------
-- Individual legs within a position group

CREATE TABLE IF NOT EXISTS position_legs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id UUID NOT NULL REFERENCES position_groups(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

    -- Instrument identification
    symbol TEXT NOT NULL,                       -- Full option symbol (e.g., "AAPL240119C00150000")
    underlying TEXT NOT NULL,                   -- e.g., "AAPL"
    right option_right NOT NULL DEFAULT 'S',    -- C=Call, P=Put, S=Stock
    strike NUMERIC,                             -- Strike price (NULL for stock)
    expiry DATE,                                -- Expiration date (NULL for stock)
    multiplier INTEGER NOT NULL DEFAULT 100,    -- Contract multiplier

    -- Position tracking
    side leg_side NOT NULL,                     -- LONG or SHORT
    qty_opened INTEGER NOT NULL DEFAULT 0,      -- Total opened (always positive)
    qty_closed INTEGER NOT NULL DEFAULT 0,      -- Total closed (always positive)
    qty_current INTEGER GENERATED ALWAYS AS (
        CASE
            WHEN side = 'LONG' THEN qty_opened - qty_closed
            ELSE -(qty_opened - qty_closed)
        END
    ) STORED,                                   -- Signed current quantity

    -- Cost basis
    avg_cost_open NUMERIC,                      -- Average cost per unit
    avg_cost_close NUMERIC,                     -- Average close price per unit

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes for position_legs
CREATE INDEX IF NOT EXISTS idx_position_legs_group_id ON position_legs(group_id);
CREATE INDEX IF NOT EXISTS idx_position_legs_user_id ON position_legs(user_id);
CREATE INDEX IF NOT EXISTS idx_position_legs_symbol ON position_legs(user_id, symbol);
CREATE INDEX IF NOT EXISTS idx_position_legs_underlying ON position_legs(user_id, underlying);

-- Updated_at trigger for position_legs
CREATE OR REPLACE FUNCTION update_position_legs_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_position_legs_updated_at_trigger ON position_legs;
CREATE TRIGGER update_position_legs_updated_at_trigger
    BEFORE UPDATE ON position_legs
    FOR EACH ROW
    EXECUTE FUNCTION update_position_legs_updated_at();

COMMENT ON TABLE position_legs IS 'v4 Accounting: Individual legs within position groups';

-- -----------------------------------------------------------------------------
-- 4. FILLS TABLE
-- -----------------------------------------------------------------------------
-- Execution fills linked to legs

CREATE TABLE IF NOT EXISTS fills (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    group_id UUID NOT NULL REFERENCES position_groups(id) ON DELETE CASCADE,
    leg_id UUID NOT NULL REFERENCES position_legs(id) ON DELETE CASCADE,

    -- Linkage to trade_executions (optional, may be NULL for broker-imported fills)
    trade_execution_id UUID REFERENCES trade_executions(id) ON DELETE SET NULL,

    -- Broker fill identification (for idempotency)
    broker_exec_id TEXT,                        -- Broker's execution ID (unique per broker fill)

    -- Fill details
    side leg_side NOT NULL,                     -- BUY or SELL (maps to LONG/SHORT)
    qty INTEGER NOT NULL,                       -- Quantity filled (always positive)
    price NUMERIC NOT NULL,                     -- Fill price per unit
    fee NUMERIC DEFAULT 0,                      -- Fees for this fill

    -- Timing
    filled_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Source
    source fill_source NOT NULL DEFAULT 'LIVE',

    -- Metadata
    meta_json JSONB DEFAULT '{}'::jsonb,

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes for fills
CREATE INDEX IF NOT EXISTS idx_fills_user_id ON fills(user_id);
CREATE INDEX IF NOT EXISTS idx_fills_group_id ON fills(group_id);
CREATE INDEX IF NOT EXISTS idx_fills_leg_id ON fills(leg_id);
CREATE INDEX IF NOT EXISTS idx_fills_trade_execution_id ON fills(trade_execution_id);
CREATE INDEX IF NOT EXISTS idx_fills_filled_at ON fills(user_id, filled_at DESC);

-- Unique constraint for broker fill idempotency (only when broker_exec_id is set)
CREATE UNIQUE INDEX IF NOT EXISTS idx_fills_broker_exec_id_unique
    ON fills(user_id, broker_exec_id)
    WHERE broker_exec_id IS NOT NULL;

COMMENT ON TABLE fills IS 'v4 Accounting: Execution fills linked to position legs';

-- -----------------------------------------------------------------------------
-- 5. POSITION_EVENTS TABLE (APPEND-ONLY)
-- -----------------------------------------------------------------------------
-- Immutable event log for all position changes

CREATE TABLE IF NOT EXISTS position_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    group_id UUID NOT NULL REFERENCES position_groups(id) ON DELETE CASCADE,

    -- Optional linkage to fill (NULL for non-fill events like EXPIRATION)
    fill_id UUID REFERENCES fills(id) ON DELETE SET NULL,
    leg_id UUID REFERENCES position_legs(id) ON DELETE SET NULL,

    -- Event details
    event_type position_event_type NOT NULL,

    -- Financial impact
    amount_cash NUMERIC,                        -- Cash impact (negative = outflow)
    qty_delta INTEGER,                          -- Quantity change (signed)

    -- Idempotency key (unique per event)
    event_key TEXT,                             -- e.g., "fill:{execution_id}:{symbol}:{ts}:{qty}:{price}"

    -- Metadata
    meta_json JSONB DEFAULT '{}'::jsonb,

    -- Timestamp (append-only, no updated_at)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes for position_events
CREATE INDEX IF NOT EXISTS idx_position_events_user_id ON position_events(user_id);
CREATE INDEX IF NOT EXISTS idx_position_events_group_id ON position_events(group_id);
CREATE INDEX IF NOT EXISTS idx_position_events_fill_id ON position_events(fill_id);
CREATE INDEX IF NOT EXISTS idx_position_events_event_type ON position_events(user_id, event_type);
CREATE INDEX IF NOT EXISTS idx_position_events_created_at ON position_events(user_id, created_at DESC);

-- Unique constraint for event idempotency
CREATE UNIQUE INDEX IF NOT EXISTS idx_position_events_event_key_unique
    ON position_events(user_id, event_key)
    WHERE event_key IS NOT NULL;

-- Immutability enforcement (append-only)
CREATE OR REPLACE FUNCTION prevent_position_event_modification()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'position_events is append-only: % operation not allowed', TG_OP;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS enforce_position_events_immutability ON position_events;
CREATE TRIGGER enforce_position_events_immutability
    BEFORE UPDATE OR DELETE ON position_events
    FOR EACH ROW
    EXECUTE FUNCTION prevent_position_event_modification();

COMMENT ON TABLE position_events IS 'v4 Accounting: Append-only event log for position changes';

-- -----------------------------------------------------------------------------
-- 6. RECONCILIATION_BREAKS TABLE
-- -----------------------------------------------------------------------------
-- Records discrepancies between canonical ledger and broker snapshot

CREATE TABLE IF NOT EXISTS reconciliation_breaks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

    -- Reconciliation run metadata
    run_id UUID NOT NULL,                       -- Groups breaks from same reconciliation run
    run_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Break details
    break_type reconciliation_break_type NOT NULL,
    symbol TEXT NOT NULL,
    underlying TEXT,

    -- Quantities
    ledger_qty INTEGER,                         -- Quantity in canonical ledger
    broker_qty INTEGER,                         -- Quantity in broker snapshot
    qty_diff INTEGER,                           -- Difference (ledger - broker)

    -- Linked entities (optional)
    group_id UUID REFERENCES position_groups(id) ON DELETE SET NULL,
    leg_id UUID REFERENCES position_legs(id) ON DELETE SET NULL,

    -- Resolution
    resolved_at TIMESTAMPTZ,
    resolution_notes TEXT,

    -- Metadata
    meta_json JSONB DEFAULT '{}'::jsonb,

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes for reconciliation_breaks
CREATE INDEX IF NOT EXISTS idx_reconciliation_breaks_user_id ON reconciliation_breaks(user_id);
CREATE INDEX IF NOT EXISTS idx_reconciliation_breaks_run_id ON reconciliation_breaks(run_id);
CREATE INDEX IF NOT EXISTS idx_reconciliation_breaks_symbol ON reconciliation_breaks(user_id, symbol);
CREATE INDEX IF NOT EXISTS idx_reconciliation_breaks_unresolved ON reconciliation_breaks(user_id)
    WHERE resolved_at IS NULL;

COMMENT ON TABLE reconciliation_breaks IS 'v4 Accounting: Reconciliation discrepancies between ledger and broker';

-- -----------------------------------------------------------------------------
-- 7. ROW LEVEL SECURITY (RLS)
-- -----------------------------------------------------------------------------

-- Enable RLS on all tables
ALTER TABLE position_groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE position_legs ENABLE ROW LEVEL SECURITY;
ALTER TABLE fills ENABLE ROW LEVEL SECURITY;
ALTER TABLE position_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconciliation_breaks ENABLE ROW LEVEL SECURITY;

-- Position Groups policies
CREATE POLICY "Users can view own position_groups"
    ON position_groups FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own position_groups"
    ON position_groups FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own position_groups"
    ON position_groups FOR UPDATE
    USING (auth.uid() = user_id);

-- Position Legs policies
CREATE POLICY "Users can view own position_legs"
    ON position_legs FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own position_legs"
    ON position_legs FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own position_legs"
    ON position_legs FOR UPDATE
    USING (auth.uid() = user_id);

-- Fills policies
CREATE POLICY "Users can view own fills"
    ON fills FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own fills"
    ON fills FOR INSERT
    WITH CHECK (auth.uid() = user_id);

-- Position Events policies (append-only, no update/delete)
CREATE POLICY "Users can view own position_events"
    ON position_events FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own position_events"
    ON position_events FOR INSERT
    WITH CHECK (auth.uid() = user_id);

-- Reconciliation Breaks policies
CREATE POLICY "Users can view own reconciliation_breaks"
    ON reconciliation_breaks FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own reconciliation_breaks"
    ON reconciliation_breaks FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own reconciliation_breaks"
    ON reconciliation_breaks FOR UPDATE
    USING (auth.uid() = user_id);

-- Service role policies (for background jobs like reconciliation)
-- Note: service_role bypasses RLS by default in Supabase, but explicit policies
-- can be added for documentation purposes if needed.

-- -----------------------------------------------------------------------------
-- 8. HELPER FUNCTIONS
-- -----------------------------------------------------------------------------

-- Function to check if all legs of a group are closed
CREATE OR REPLACE FUNCTION check_position_group_closed(p_group_id UUID)
RETURNS BOOLEAN AS $$
DECLARE
    v_open_legs INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_open_legs
    FROM position_legs
    WHERE group_id = p_group_id
      AND (qty_opened - qty_closed) > 0;

    RETURN v_open_legs = 0;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION check_position_group_closed(UUID) IS 'v4 Accounting: Check if all legs of a position group are closed';

-- -----------------------------------------------------------------------------
-- END OF MIGRATION
-- -----------------------------------------------------------------------------
