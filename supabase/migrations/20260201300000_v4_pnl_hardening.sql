-- =============================================================================
-- v4 Portfolio Accounting: PnL v1.1 Hardening
-- Fixes qty_current type safety (NUMERIC vs INTEGER)
-- =============================================================================
--
-- Changes:
--   1. Replace compute_leg_unrealized_pnl to use NUMERIC for qty parameter
--      (safe for contracts/shares without casting errors)
--
-- Principles:
--   - Additive/safe: uses CREATE OR REPLACE
--   - No table rewrites
--   - v1.1 hardening for type consistency
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. UPDATE compute_leg_unrealized_pnl SIGNATURE (NUMERIC qty)
-- -----------------------------------------------------------------------------
-- v1.1 Hardening: Changed p_qty_current from INTEGER to NUMERIC
-- This ensures compatibility with position_legs.qty_current (computed column)
-- which may have NUMERIC-like behavior depending on operations.

CREATE OR REPLACE FUNCTION compute_leg_unrealized_pnl(
    p_side leg_side,
    p_avg_cost_open NUMERIC,
    p_mark_mid NUMERIC,
    p_qty_current NUMERIC,  -- v1.1: Changed from INTEGER to NUMERIC
    p_multiplier NUMERIC    -- v1.1: Changed from INTEGER to NUMERIC for consistency
)
RETURNS NUMERIC AS $$
BEGIN
    -- Return NULL for invalid inputs
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

COMMENT ON FUNCTION compute_leg_unrealized_pnl(leg_side, NUMERIC, NUMERIC, NUMERIC, NUMERIC)
    IS 'v4 Accounting v1.1: Compute unrealized PnL for a position leg (NUMERIC-safe)';

-- -----------------------------------------------------------------------------
-- END OF MIGRATION
-- -----------------------------------------------------------------------------
