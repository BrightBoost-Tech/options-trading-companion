-- Tier 1B convenience view: full decision audit trail per closed
-- position in the last 30 days.
--
-- One row per closed position. Joins paper_positions (close-side
-- audit) with trade_suggestions (entry-side decision context) and
-- learning_feedback_loops (predicted vs realized analytics).
--
-- Helps answer the learning-mode question "what was the full
-- decision chain for this trade?" without ad-hoc JOIN-heavy SQL.
--
-- All JOINs are LEFT so missing relationships don't drop rows.
-- learning_feedback_loops join uses suggestion_id (no position_id
-- exists on that table); filtered to outcome_type IN ('trade_closed',
-- 'individual_trade') to match learning_trade_outcomes_v3's lens.
--
-- Schema notes:
--   - paper_positions uses `symbol` + `strategy_key` (not ticker /
--     strategy_type).
--   - trade_suggestions has `sizing_metadata` jsonb that carries
--     `score`; no top-level score column.
--   - learning_feedback_loops has `pnl_alpha` and `pnl_execution_drag`
--     as top-level columns plus `drift_tags` array.
--
-- See CLAUDE.md `### Operating mode — learning-mode at micro tier`.

CREATE OR REPLACE VIEW public.recent_closes_audit AS
SELECT
  pp.id AS position_id,
  pp.symbol,
  pp.strategy_key,
  pp.created_at AS entry_time,
  pp.closed_at  AS exit_time,
  ROUND(
    (EXTRACT(EPOCH FROM (pp.closed_at - pp.created_at)) / 3600.0)::numeric,
    2
  ) AS hold_hours,
  pp.close_reason,
  pp.realized_pl,
  pp.fill_source,
  pp.suggestion_id,
  pp.trace_id,
  pp.regime AS position_regime,
  pp.entry_dte,
  pp.model_version,
  pp.window,
  -- Decision context from suggestion (LEFT JOIN — may be NULL on
  -- positions that were created without a linked suggestion)
  (ts.sizing_metadata ->> 'score')::numeric AS entry_score,
  ts.regime AS entry_regime,
  ts.agent_summary AS entry_rationale,
  ts.decision_lineage AS entry_decision_chain,
  ts.marketdata_quality AS entry_marketdata_quality,
  ts.ev AS entry_ev,
  ts.probability_of_profit AS entry_pop,
  -- Learning loop data (LEFT JOIN — may be NULL until the feedback
  -- loop has processed this position)
  lfl.pnl_predicted,
  lfl.pnl_alpha,
  lfl.pnl_execution_drag,
  lfl.drift_tags,
  lfl.learning_processed
FROM paper_positions pp
LEFT JOIN trade_suggestions ts
  ON pp.suggestion_id = ts.id
LEFT JOIN learning_feedback_loops lfl
  ON lfl.suggestion_id = pp.suggestion_id
 AND lfl.outcome_type IN ('trade_closed', 'individual_trade')
WHERE pp.status = 'closed'
  AND pp.closed_at >= NOW() - INTERVAL '30 days'
ORDER BY pp.closed_at DESC;

COMMENT ON VIEW public.recent_closes_audit IS
  'Last 30 days of closed positions with full decision audit trail. '
  'Joins entry suggestion + close outcome + learning loop data. '
  'One row per closed position. Helps answer: what was the full '
  'decision chain for this trade? See learning-mode codification '
  'in CLAUDE.md Active focus.';
