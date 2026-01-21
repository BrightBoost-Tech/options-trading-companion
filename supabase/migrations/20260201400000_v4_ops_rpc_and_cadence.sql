-- =============================================================================
-- v4 Accounting PnL v1.2 Ops: RPC + Cadence Hooks
-- =============================================================================
-- This migration adds:
-- 1. rpc_seed_needs_review_v4: Stable RPC function for seed review report
--    (replaces fragile PostgREST JSON-path filtering)
-- =============================================================================

-- =============================================================================
-- RPC Function: rpc_seed_needs_review_v4
-- =============================================================================
-- Returns needs_review position events with enriched leg/group details.
-- Replaces the brittle PostgREST JSON-path filtering approach.
--
-- Parameters:
--   p_user_id: UUID (optional) - filter to single user
--   p_include_resolved: BOOLEAN (default false) - include closed positions
--   p_limit: INT (default 100, capped at 500)
--
-- Returns: TABLE with enriched event data ready for report rendering

CREATE OR REPLACE FUNCTION rpc_seed_needs_review_v4(
    p_user_id UUID DEFAULT NULL,
    p_include_resolved BOOLEAN DEFAULT FALSE,
    p_limit INT DEFAULT 100
)
RETURNS TABLE (
    event_id UUID,
    user_id UUID,
    group_id UUID,
    leg_id UUID,
    created_at TIMESTAMPTZ,
    symbol TEXT,
    underlying TEXT,
    inferred_side TEXT,
    qty_current NUMERIC,
    group_status TEXT,
    strategy_key TEXT,
    opened_at TIMESTAMPTZ,
    side_inference JSONB,
    note TEXT
)
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    v_limit INT;
BEGIN
    -- Cap limit at 500 for safety
    v_limit := LEAST(COALESCE(p_limit, 100), 500);

    RETURN QUERY
    SELECT
        pe.id AS event_id,
        pe.user_id,
        pe.group_id,
        pe.leg_id,
        pe.created_at,
        pl.symbol,
        pl.underlying,
        pl.side AS inferred_side,
        pl.qty_current,
        pg.status AS group_status,
        pg.strategy_key,
        pg.opened_at,
        (pe.meta_json->'side_inference')::JSONB AS side_inference,
        (pe.meta_json->>'note')::TEXT AS note
    FROM
        position_events pe
    LEFT JOIN
        position_legs pl ON pe.leg_id = pl.id
    LEFT JOIN
        position_groups pg ON pe.group_id = pg.id
    WHERE
        -- Filter for seed entries needing review
        (pe.meta_json->>'opening_balance')::TEXT = 'true'
        AND (pe.meta_json->>'needs_review')::TEXT = 'true'
        -- Optional user filter
        AND (p_user_id IS NULL OR pe.user_id = p_user_id)
        -- Optional include_resolved filter (default: only OPEN groups)
        AND (p_include_resolved = TRUE OR pg.status = 'OPEN')
    ORDER BY
        pe.created_at DESC
    LIMIT
        v_limit;
END;
$$;

-- Add comment for documentation
COMMENT ON FUNCTION rpc_seed_needs_review_v4(UUID, BOOLEAN, INT) IS
    'Returns position events requiring manual review due to ambiguous side inference during Seed v2. '
    'Replaces fragile PostgREST JSON-path filtering with stable server-side function.';

-- Grant execute to service role (for job handlers)
-- Note: Supabase automatically grants execute to authenticated role
-- This is a read-only function, safe for direct call from jobs
