-- Tier 1B convenience view: per-symbol trade outcomes.
--
-- Surfaces win rate, P&L distribution, and strategy diversity per
-- symbol over a rolling 90-day window. Helps answer the
-- learning-mode question "which symbols produce reliable patterns
-- vs noise?" without ad-hoc SQL.
--
-- Source: learning_trade_outcomes_v3 (which is itself a view joining
-- learning_feedback_loops + trade_suggestions, filtered to
-- outcome_type IN ('trade_closed', 'individual_trade')).
-- Note that learning_trade_outcomes_v3 uses `ticker` (not symbol) and
-- `strategy` (not strategy_type) — the field names differ from
-- paper_positions, an artifact of the existing analytics-side schema.
--
-- See CLAUDE.md `### Operating mode — learning-mode at micro tier`.

CREATE OR REPLACE VIEW public.symbol_performance AS
SELECT
  ticker,
  COUNT(*) AS total_trades,
  COUNT(*) FILTER (WHERE pnl_realized > 0) AS wins,
  COUNT(*) FILTER (WHERE pnl_realized <= 0) AS losses,
  ROUND(
    COUNT(*) FILTER (WHERE pnl_realized > 0)::numeric
    / NULLIF(COUNT(*), 0)::numeric
    * 100,
    1
  ) AS win_rate_pct,
  ROUND(SUM(pnl_realized)::numeric, 2) AS cumulative_pnl,
  ROUND(AVG(pnl_realized)::numeric, 2) AS avg_pnl,
  ROUND(AVG(pnl_realized) FILTER (WHERE pnl_realized > 0)::numeric, 2) AS avg_win,
  ROUND(AVG(pnl_realized) FILTER (WHERE pnl_realized <= 0)::numeric, 2) AS avg_loss,
  MIN(closed_at) AS first_close,
  MAX(closed_at) AS last_close,
  COUNT(DISTINCT strategy) AS strategies_traded
FROM learning_trade_outcomes_v3
WHERE closed_at >= NOW() - INTERVAL '90 days'
GROUP BY ticker
ORDER BY total_trades DESC, cumulative_pnl DESC;

COMMENT ON VIEW public.symbol_performance IS
  'Per-symbol trade outcomes over last 90 days. Surfaces win rate, '
  'P&L distribution, strategy diversity. Helps answer: which symbols '
  'produce reliable patterns vs noise? See learning-mode codification '
  'in CLAUDE.md Active focus. Source: learning_trade_outcomes_v3.';
