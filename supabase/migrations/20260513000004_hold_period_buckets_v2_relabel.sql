-- Tier 1B v2: hold_period_buckets — reason-accurate stop_loss split.
--
-- v1 (20260513000002) bucketed `close_reason = 'stop_loss_hit'` as
-- 'loser' uniformly. The 2026-05-13 hold-ratio investigation surfaced
-- AMD iron condor (close_reason=stop_loss_hit, pnl=+$1,202) being
-- mislabeled — wing-breach exit on an already-profitable position
-- isn't a "loser" in any business sense.
--
-- v2 splits the stop_loss_hit bucket by P&L sign:
--   stop_loss_hit + pnl > 0   → 'profitable_stop'
--   stop_loss_hit + pnl <= 0  → 'stop_loss_exit' (renamed from 'loser')
-- All other buckets (winner / force_close / manual_close / reconciler /
-- other) unchanged from v1.
--
-- Pre-flight survey (2026-05-13) confirmed close_reason enum unchanged
-- from v1 apply: target_profit_hit (44), manual_close_user_initiated (7),
-- stop_loss_hit (7), alpaca_fill_reconciler_standard (3),
-- alpaca_fill_reconciler_sign_corrected (1), envelope_force_close (1),
-- NULL (1).
--
-- Source: paper_positions (close_reason + created_at + closed_at not
-- in learning_trade_outcomes_v3). See CLAUDE.md
-- `## Operational notes — Exit thresholds (defaults under review)`
-- for context on threshold values + their empirical hold-ratio impact.

CREATE OR REPLACE VIEW public.hold_period_buckets AS
WITH bucketed AS (
  SELECT
    CASE
      WHEN close_reason = 'target_profit_hit'              THEN 'winner'
      -- v2 split: profitable stop_loss exit (e.g., wing breach on
      -- already-profitable iron condor) gets its own bucket so it
      -- isn't mislabeled as a loss.
      WHEN close_reason = 'stop_loss_hit' AND realized_pl > 0
        THEN 'profitable_stop'
      WHEN close_reason = 'stop_loss_hit'                  THEN 'stop_loss_exit'
      WHEN close_reason = 'envelope_force_close'           THEN 'force_close'
      WHEN close_reason = 'manual_close_user_initiated'    THEN 'manual_close'
      WHEN close_reason LIKE 'alpaca_fill_reconciler%'     THEN 'reconciler'
      ELSE 'other'
    END AS outcome_bucket,
    EXTRACT(EPOCH FROM (closed_at - created_at)) / 3600.0 AS hold_hours,
    realized_pl,
    strategy_key,
    symbol,
    closed_at,
    close_reason
  FROM paper_positions
  WHERE status = 'closed'
    AND closed_at >= NOW() - INTERVAL '90 days'
    AND closed_at IS NOT NULL
    AND created_at IS NOT NULL
)
SELECT
  outcome_bucket,
  COUNT(*) AS trade_count,
  ROUND(AVG(hold_hours)::numeric, 2) AS avg_hold_hours,
  ROUND(MIN(hold_hours)::numeric, 2) AS min_hold_hours,
  ROUND(MAX(hold_hours)::numeric, 2) AS max_hold_hours,
  ROUND(
    (PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY hold_hours))::numeric,
    2
  ) AS median_hold_hours,
  ROUND(AVG(realized_pl)::numeric, 2) AS avg_pnl,
  ROUND(SUM(realized_pl)::numeric, 2) AS cumulative_pnl,
  ARRAY_AGG(DISTINCT close_reason ORDER BY close_reason) AS close_reasons_in_bucket,
  ARRAY_AGG(DISTINCT strategy_key ORDER BY strategy_key) AS strategies_in_bucket
FROM bucketed
GROUP BY outcome_bucket
ORDER BY
  CASE outcome_bucket
    WHEN 'winner'           THEN 1
    WHEN 'profitable_stop'  THEN 2
    WHEN 'stop_loss_exit'   THEN 3
    WHEN 'force_close'      THEN 4
    WHEN 'manual_close'     THEN 5
    WHEN 'reconciler'       THEN 6
    WHEN 'other'            THEN 7
  END;

COMMENT ON VIEW public.hold_period_buckets IS
  'Hold-period distribution by outcome bucket over last 90 days. '
  'V2 (2026-05-13): stop_loss_hit closes are split by P&L sign so '
  'profitable wing-breach exits (e.g., iron condor with one wing '
  'tested but overall positive) bucket as ''profitable_stop'' rather '
  'than ''loser''. Pure loss-side stop exits bucket as '
  '''stop_loss_exit'' (was ''loser'' in v1). Source: paper_positions '
  '(close_reason + created_at + closed_at not surfaced in '
  'learning_trade_outcomes_v3). See CLAUDE.md operational note on '
  'exit thresholds for context.';
