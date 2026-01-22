-- Migration: Fix learning_trade_outcomes_v3 is_paper to use canonical lfl.is_paper column
--
-- Problem: The view currently only reads details_json.is_paper, but the canonical
-- source is learning_feedback_loops.is_paper (added in 20251212000000_observability_v3).
--
-- Solution: Update is_paper expression to prefer lfl.is_paper, then fall back to
-- details_json.is_paper for backward compatibility with older rows.

CREATE OR REPLACE VIEW learning_trade_outcomes_v3 AS
SELECT
    lfl.user_id,
    COALESCE(lfl.updated_at, lfl.created_at) AS closed_at,
    lfl.trace_id,
    lfl.suggestion_id,
    lfl.execution_id,
    -- v4-fix: Prefer canonical is_paper column, fall back to details_json for legacy rows
    COALESCE(
        lfl.is_paper,
        (lfl.details_json->>'is_paper')::boolean,
        false
    ) AS is_paper,
    COALESCE(lfl.model_version, ts.model_version) AS model_version,
    COALESCE(lfl.features_hash, ts.features_hash) AS features_hash,
    COALESCE(lfl.strategy, ts.strategy) AS strategy,
    COALESCE(lfl.window, ts.window) AS window,
    COALESCE(lfl.regime, ts.regime) AS regime,
    ts.ticker,
    ts.ev AS ev_predicted,
    ts.probability_of_profit AS pop_predicted,
    lfl.pnl_realized,
    lfl.pnl_predicted,
    (lfl.pnl_realized - lfl.pnl_predicted) AS pnl_alpha,
    (lfl.details_json->>'pnl_execution_drag')::numeric AS pnl_execution_drag,
    (lfl.details_json->>'fees_total')::numeric AS fees_total,
    (lfl.details_json->>'entry_mid')::numeric AS entry_mid,
    (lfl.details_json->>'exit_mid')::numeric AS exit_mid,
    lfl.details_json->'reason_codes' AS reason_codes
FROM learning_feedback_loops lfl
JOIN trade_suggestions ts ON lfl.suggestion_id = ts.id
WHERE lfl.outcome_type IN ('trade_closed', 'individual_trade');
