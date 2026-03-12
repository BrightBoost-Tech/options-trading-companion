-- Restore paper_positions deleted by _commit_fill when it used .delete()
-- instead of .update(status='closed').
--
-- Data sources:
--   - paper_orders: has position_id, order_json (with symbol, legs, strategy),
--     avg_fill_price, filled_qty, side, portfolio_id, suggestion_id, trace_id
--   - The entry order (first filled order for the position) has the
--     avg_entry_price; the exit order (last filled order) has the exit price.
--
-- Strategy:
--   1. Find all position_ids referenced by paper_orders that no longer exist
--      in paper_positions (orphaned references = deleted positions).
--   2. For each, reconstruct the position from entry + exit order data.
--   3. Insert with status='closed', quantity=0, realized_pl computed from
--      entry and exit prices.
--
-- IMPORTANT: Run this ONCE. It is idempotent (uses ON CONFLICT DO NOTHING).

-- Step 1: Replace the unique constraint so closed + open positions with the
-- same strategy_key can coexist. The old constraint was:
--   UNIQUE(portfolio_id, strategy_key)
-- The new constraint only applies to open positions.
ALTER TABLE paper_positions DROP CONSTRAINT IF EXISTS paper_positions_portfolio_id_strategy_key_key;

CREATE UNIQUE INDEX IF NOT EXISTS uq_paper_positions_open_strategy
    ON paper_positions (portfolio_id, strategy_key)
    WHERE status = 'open';

-- Step 2: Reconstruct deleted positions from their paper_orders history.
-- Each deleted position has at least two orders: an entry and an exit.
INSERT INTO paper_positions (
    id,
    portfolio_id,
    user_id,
    strategy_key,
    symbol,
    quantity,
    avg_entry_price,
    status,
    close_reason,
    closed_at,
    realized_pl,
    legs,
    suggestion_id,
    trace_id,
    max_credit,
    nearest_expiry,
    created_at,
    updated_at
)
SELECT
    orphan.position_id                                      AS id,
    entry_order.portfolio_id                                AS portfolio_id,
    entry_order.user_id                                     AS user_id,
    -- Derive strategy_key from order_json
    COALESCE(
        entry_order.order_json->>'symbol', 'UNKNOWN'
    ) || '_' || COALESCE(
        entry_order.order_json->>'strategy_type', 'custom'
    )                                                       AS strategy_key,
    COALESCE(entry_order.order_json->>'symbol', 'UNKNOWN')  AS symbol,
    0                                                       AS quantity,
    COALESCE(entry_order.avg_fill_price, 0)                 AS avg_entry_price,
    'closed'                                                AS status,
    'target_profit'                                         AS close_reason,
    exit_order.filled_at                                    AS closed_at,
    -- realized_pl: for credit (short) positions: (entry - exit) * qty * 100
    -- for debit (long) positions: (exit - entry) * qty * 100
    CASE
        WHEN entry_order.side = 'sell' THEN
            (COALESCE(entry_order.avg_fill_price, 0) - COALESCE(exit_order.avg_fill_price, 0))
            * COALESCE(entry_order.filled_qty, 0) * 100
        ELSE
            (COALESCE(exit_order.avg_fill_price, 0) - COALESCE(entry_order.avg_fill_price, 0))
            * COALESCE(entry_order.filled_qty, 0) * 100
    END
    - COALESCE(entry_order.fees_usd, 0)
    - COALESCE(exit_order.fees_usd, 0)                     AS realized_pl,
    entry_order.order_json->'legs'                          AS legs,
    -- suggestion_id: try source_ref_id from order_json, fall back to order's suggestion_id
    COALESCE(
        (entry_order.order_json->>'source_ref_id')::uuid,
        entry_order.suggestion_id
    )                                                       AS suggestion_id,
    entry_order.trace_id                                    AS trace_id,
    entry_order.avg_fill_price                              AS max_credit,
    -- nearest_expiry: extract from first leg
    (entry_order.order_json->'legs'->0->>'expiry')::date    AS nearest_expiry,
    entry_order.filled_at                                   AS created_at,
    exit_order.filled_at                                    AS updated_at
FROM (
    -- Find position_ids that exist in paper_orders but not in paper_positions
    SELECT DISTINCT po.position_id
    FROM paper_orders po
    WHERE po.position_id IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM paper_positions pp WHERE pp.id = po.position_id
      )
) orphan
-- Join entry order: the first filled order for this position (earliest filled_at)
JOIN LATERAL (
    SELECT *
    FROM paper_orders
    WHERE position_id = orphan.position_id
      AND status = 'filled'
    ORDER BY filled_at ASC
    LIMIT 1
) entry_order ON true
-- Join exit order: the last filled order for this position (latest filled_at)
JOIN LATERAL (
    SELECT *
    FROM paper_orders
    WHERE position_id = orphan.position_id
      AND status = 'filled'
    ORDER BY filled_at DESC
    LIMIT 1
) exit_order ON true
-- Only reconstruct if we have at least 2 orders (entry + exit)
WHERE entry_order.id != exit_order.id
ON CONFLICT (id) DO NOTHING;
