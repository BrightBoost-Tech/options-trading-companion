-- Backfill migration: populate user_id, max_credit, status on existing paper_positions
-- Runs after 20260310000000_paper_mark_to_market.sql which adds the columns.

-- 1. Backfill user_id from paper_portfolios
UPDATE paper_positions pp
SET user_id = p.user_id
FROM paper_portfolios p
WHERE pp.portfolio_id = p.id
  AND pp.user_id IS NULL;

-- 2. Backfill max_credit from avg_entry_price (best available proxy)
-- avg_entry_price is set to the credit received at entry for short spreads
UPDATE paper_positions
SET max_credit = avg_entry_price
WHERE max_credit IS NULL
  AND avg_entry_price > 0;

-- 3. Backfill status: positions with quantity != 0 are open, others are closed
UPDATE paper_positions
SET status = CASE
    WHEN quantity != 0 THEN 'open'
    ELSE 'closed'
END
WHERE status IS NULL OR status = 'open';
