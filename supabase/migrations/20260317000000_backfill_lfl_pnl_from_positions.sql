-- Backfill learning_feedback_loops.pnl_realized with correct trade P&L
-- from paper_positions.realized_pl.
--
-- Root cause: paper_learning_ingest was computing execution slippage
-- (fill_price - requested_price) * qty instead of actual trade P&L
-- (exit_price - entry_price) * abs(qty) * 100. The exit evaluator writes
-- the correct value to paper_positions.realized_pl, so we copy it here.
--
-- Join path: learning_feedback_loops.source_event_id → paper_orders.id
--            paper_orders.position_id → paper_positions.id

UPDATE learning_feedback_loops lfl
SET
    pnl_realized = pp.realized_pl,
    updated_at   = pp.closed_at
FROM paper_orders po
JOIN paper_positions pp ON pp.id = po.position_id
WHERE lfl.source_event_id = po.id
  AND lfl.is_paper = true
  AND lfl.outcome_type = 'trade_closed'
  AND pp.status = 'closed'
  AND pp.realized_pl IS NOT NULL;
