-- Tier 1C companion view: per (symbol, reason) rejection patterns
-- over a rolling 30-day window. Helps answer learning-mode questions
-- about persistent rejection patterns ("which symbols are repeatedly
-- rejected for the same reason?") without ad-hoc SQL.
--
-- Returns 0 rows initially — forward-only data from 2026-05-13.
-- Populates as suggestion_rejections rows accumulate.
--
-- See suggestion_rejections table for the row-level source.

CREATE OR REPLACE VIEW public.rejection_patterns AS
SELECT
  sr.symbol,
  sr.reason,
  COUNT(*) AS total_rejections,
  COUNT(DISTINCT sr.cycle_date) AS days_with_rejections,
  COUNT(DISTINCT sr.strategy_key) FILTER (WHERE sr.strategy_key IS NOT NULL)
    AS distinct_strategies,
  MIN(sr.cycle_date) AS first_rejection_date,
  MAX(sr.cycle_date) AS last_rejection_date,
  -- Most-recent spread_debug per (symbol, reason) for context.
  -- Correlated subquery is fine here — view is computed on demand,
  -- N(symbol, reason) is small.
  (
    SELECT spread_debug
    FROM public.suggestion_rejections sr2
    WHERE sr2.symbol = sr.symbol
      AND sr2.reason = sr.reason
    ORDER BY sr2.created_at DESC
    LIMIT 1
  ) AS last_spread_debug
FROM public.suggestion_rejections sr
WHERE sr.cycle_date >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY sr.symbol, sr.reason
ORDER BY total_rejections DESC, last_rejection_date DESC;

COMMENT ON VIEW public.rejection_patterns IS
  'Per (symbol, reason) rejection patterns over rolling 30 days. '
  'Surfaces which symbols are repeatedly rejected for the same '
  'reason (false-negative analysis for learning mode). Forward-only '
  'data from 2026-05-13.';
