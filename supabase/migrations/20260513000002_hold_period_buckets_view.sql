-- Tier 1B convenience view: hold-period distribution by outcome.
--
-- Bucketizes closed positions by outcome (winner / loser / force_close /
-- manual_close / reconciler / other) and computes hold-period statistics
-- per bucket. Helps answer the learning-mode question "do winners hold
-- longer than losers? Are force-closes firing late?"
--
-- Source: paper_positions directly (NOT learning_trade_outcomes_v3 —
-- that view lacks `created_at` and `close_reason`).
--
-- Bucket mapping based on actual `close_reason` values surveyed
-- 2026-05-13:
--   target_profit_hit              (44)  → winner
--   manual_close_user_initiated     (7)  → manual_close
--   stop_loss_hit                   (7)  → loser
--   alpaca_fill_reconciler_standard (3)  → reconciler
--   alpaca_fill_reconciler_sign_corrected (1) → reconciler
--   envelope_force_close            (1)  → force_close
--   (anything else)                       → other
--
-- See CLAUDE.md `### Operating mode — learning-mode at micro tier`.

CREATE OR REPLACE VIEW public.hold_period_buckets AS
WITH bucketed AS (
  SELECT
    CASE
      WHEN close_reason = 'target_profit_hit'              THEN 'winner'
      WHEN close_reason = 'stop_loss_hit'                  THEN 'loser'
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
    WHEN 'winner'       THEN 1
    WHEN 'loser'        THEN 2
    WHEN 'force_close'  THEN 3
    WHEN 'manual_close' THEN 4
    WHEN 'reconciler'   THEN 5
    WHEN 'other'        THEN 6
  END;

COMMENT ON VIEW public.hold_period_buckets IS
  'Hold-period distribution by outcome bucket over last 90 days. '
  'Helps answer: do winners hold longer than losers? Are force-closes '
  'firing late? Source: paper_positions (close_reason + created_at + '
  'closed_at not surfaced in learning_trade_outcomes_v3). See '
  'learning-mode codification in CLAUDE.md Active focus.';
