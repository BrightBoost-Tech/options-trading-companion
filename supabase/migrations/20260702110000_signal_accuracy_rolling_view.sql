-- Gap-2 2026-07-02: rolling signal-accuracy telemetry (OBSERVE-ONLY).
-- Live-only (is_paper=false) rolling hit-rate + Brier score per strategy and
-- overall, over the last 20 closes per scope. Sources learning_feedback_loops
-- (typed strategy is populated forward by #1110 and backfilled 07-02).
-- Consumers: ops_health_check surfacing + threshold alert; the gap-1 streak
-- breaker's N will be revisited against these base rates. Modulates NOTHING.
--
-- Apply per docs/migration_procedure.md BEFORE merging the code that reads it.

CREATE OR REPLACE VIEW public.signal_accuracy_rolling AS
WITH live_closes AS (
    SELECT
        COALESCE(strategy, 'UNKNOWN') AS strategy,
        CASE WHEN pnl_realized > 0 THEN 1 ELSE 0 END AS win,
        CASE WHEN details_json->>'predicted_pop' ~ '^-?[0-9]*\.?[0-9]+$'
             THEN (details_json->>'predicted_pop')::numeric
        END AS predicted_pop,
        COALESCE(updated_at, created_at) AS closed_at
    FROM public.learning_feedback_loops
    WHERE outcome_type = 'trade_closed'
      AND is_paper = false
),
scoped AS (
    SELECT
        'overall'::text AS scope,
        win, predicted_pop, closed_at,
        ROW_NUMBER() OVER (ORDER BY closed_at DESC) AS rn
    FROM live_closes
    UNION ALL
    SELECT
        'strategy:' || strategy AS scope,
        win, predicted_pop, closed_at,
        ROW_NUMBER() OVER (PARTITION BY strategy ORDER BY closed_at DESC) AS rn
    FROM live_closes
)
SELECT
    scope,
    COUNT(*)::int AS n,
    SUM(win)::int AS wins,
    ROUND(AVG(win)::numeric, 4) AS hit_rate,
    -- Brier over the rows that carry a prediction-time PoP snapshot only —
    -- never fabricated for rows without one (H9).
    ROUND(
        (AVG(POWER(predicted_pop - win, 2))
             FILTER (WHERE predicted_pop IS NOT NULL))::numeric,
        4
    ) AS brier,
    COUNT(*) FILTER (WHERE predicted_pop IS NOT NULL)::int AS brier_n,
    MIN(closed_at) AS window_start,
    MAX(closed_at) AS window_end
FROM scoped
WHERE rn <= 20
GROUP BY scope;
