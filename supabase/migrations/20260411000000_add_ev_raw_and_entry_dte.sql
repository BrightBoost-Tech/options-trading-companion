-- Add ev_raw / pop_raw to trade_suggestions for calibration learning loop.
-- Calibration was training against its own calibrated output (self-referential).
-- ev_raw stores the pre-calibration EV so the learning view can measure
-- raw prediction quality independently of calibration adjustments.

ALTER TABLE trade_suggestions ADD COLUMN IF NOT EXISTS ev_raw numeric;
ALTER TABLE trade_suggestions ADD COLUMN IF NOT EXISTS pop_raw numeric;

-- Add entry_dte to paper_positions for time-scaled profit targets.
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS entry_dte integer;

-- Add sector to paper_positions and trade_suggestions for risk concentration checks.
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS sector text DEFAULT 'unknown';
ALTER TABLE trade_suggestions ADD COLUMN IF NOT EXISTS sector text DEFAULT 'unknown';

-- Update the learning view to use raw EV when available.
-- COALESCE ensures backward compatibility with existing rows.
CREATE OR REPLACE VIEW learning_trade_outcomes_v3 AS
SELECT
    lfl.user_id,
    COALESCE(lfl.updated_at, lfl.created_at) AS closed_at,
    lfl.trace_id,
    lfl.suggestion_id,
    lfl.execution_id,
    COALESCE((lfl.details_json->>'is_paper')::boolean, false) AS is_paper,
    COALESCE(lfl.model_version, ts.model_version) AS model_version,
    COALESCE(lfl.features_hash, ts.features_hash) AS features_hash,
    COALESCE(lfl.strategy, ts.strategy) AS strategy,
    COALESCE(lfl."window", ts."window") AS "window",
    COALESCE(lfl.regime, ts.regime) AS regime,
    ts.ticker,
    COALESCE(ts.ev_raw, ts.ev) AS ev_predicted,
    COALESCE(ts.pop_raw, ts.probability_of_profit) AS pop_predicted,
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
