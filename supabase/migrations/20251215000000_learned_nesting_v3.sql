-- Migration: Learned Nesting v3 schema discipline

-- A) Create new table: model_governance_states
CREATE TABLE IF NOT EXISTS model_governance_states (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES auth.users(id),
    model_name text NOT NULL,
    strategy text,
    window text,
    regime text,
    state_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    sample_size integer NOT NULL DEFAULT 0,
    trained_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(user_id, model_name, strategy, window, regime)
);

CREATE INDEX IF NOT EXISTS idx_model_governance_retrieval
    ON model_governance_states(user_id, model_name, updated_at DESC);

-- Trigger to auto-update updated_at for model_governance_states
CREATE OR REPLACE FUNCTION update_model_governance_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS trg_model_governance_updated_at ON model_governance_states;
CREATE TRIGGER trg_model_governance_updated_at
    BEFORE UPDATE ON model_governance_states
    FOR EACH ROW
    EXECUTE PROCEDURE update_model_governance_updated_at();


-- B) Alter paper_positions to carry traceability
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS trace_id uuid;
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS suggestion_id uuid;
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS model_version text;
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS features_hash text;
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS strategy text;
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS window text;
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS regime text;

-- Add FK: suggestion_id -> trade_suggestions(id)
-- Using DO block to check constraint existence safely
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_paper_positions_suggestion') THEN
        ALTER TABLE paper_positions
        ADD CONSTRAINT fk_paper_positions_suggestion
        FOREIGN KEY (suggestion_id) REFERENCES trade_suggestions(id);
    END IF;
END $$;

-- Add indexes for paper_positions
CREATE INDEX IF NOT EXISTS idx_paper_positions_trace_id ON paper_positions(trace_id);
CREATE INDEX IF NOT EXISTS idx_paper_positions_suggestion_id ON paper_positions(suggestion_id);


-- Supplemental: Alter paper_orders (Required for view learning_contract_violations_v3)
ALTER TABLE paper_orders ADD COLUMN IF NOT EXISTS trace_id uuid;


-- Supplemental: Alter trade_suggestions (Required for view learning_trade_outcomes_v3)
ALTER TABLE trade_suggestions ADD COLUMN IF NOT EXISTS trace_id uuid;
ALTER TABLE trade_suggestions ADD COLUMN IF NOT EXISTS model_version text;
ALTER TABLE trade_suggestions ADD COLUMN IF NOT EXISTS features_hash text;
-- Note: 'regime' might be missing too, adding it just in case
ALTER TABLE trade_suggestions ADD COLUMN IF NOT EXISTS regime text;


-- Supplemental: Alter learning_feedback_loops (Required for view learning_trade_outcomes_v3)
ALTER TABLE learning_feedback_loops ADD COLUMN IF NOT EXISTS trace_id uuid;
ALTER TABLE learning_feedback_loops ADD COLUMN IF NOT EXISTS model_version text;
ALTER TABLE learning_feedback_loops ADD COLUMN IF NOT EXISTS features_hash text;
ALTER TABLE learning_feedback_loops ADD COLUMN IF NOT EXISTS regime text;
ALTER TABLE learning_feedback_loops ADD COLUMN IF NOT EXISTS execution_id uuid;


-- C) Create v3 learning views

-- 1) View: learning_trade_outcomes_v3
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


-- 2) View: learning_performance_summary_v3
CREATE OR REPLACE VIEW learning_performance_summary_v3 AS
SELECT
    user_id,
    strategy,
    window,
    regime,
    count(*) AS total_trades,
    avg(CASE WHEN pnl_realized > 0 THEN 1 ELSE 0 END) AS win_rate,
    avg(pnl_realized) AS avg_realized_pnl,
    avg(ev_predicted) AS avg_predicted_ev,
    avg(pnl_realized - ev_predicted) AS avg_ev_leakage,
    stddev_samp(pnl_realized) AS std_realized_pnl,
    max(closed_at) AS last_trade_at
FROM learning_trade_outcomes_v3
GROUP BY user_id, strategy, window, regime;


-- 3) View: learning_contract_violations_v3
CREATE OR REPLACE VIEW learning_contract_violations_v3 AS
SELECT
    'trade_suggestions'::text AS table_name,
    id::text AS record_id,
    created_at,
    ARRAY_REMOVE(ARRAY[
        CASE WHEN trace_id IS NULL THEN 'trace_id' END,
        CASE WHEN model_version IS NULL THEN 'model_version' END,
        CASE WHEN features_hash IS NULL THEN 'features_hash' END,
        CASE WHEN strategy IS NULL THEN 'strategy' END,
        CASE WHEN window IS NULL THEN 'window' END
    ], NULL) AS missing_fields,
    'Missing core learning fields'::text AS notes
FROM trade_suggestions
WHERE trace_id IS NULL
   OR model_version IS NULL
   OR features_hash IS NULL
   OR strategy IS NULL
   OR window IS NULL

UNION ALL

SELECT
    'paper_orders'::text AS table_name,
    id::text AS record_id,
    created_at,
    ARRAY['trace_id'] AS missing_fields,
    'Paper order linked to suggestion but missing trace_id'::text AS notes
FROM paper_orders
WHERE suggestion_id IS NOT NULL AND trace_id IS NULL

UNION ALL

SELECT
    'learning_feedback_loops'::text AS table_name,
    id::text AS record_id,
    created_at,
    ARRAY_REMOVE(ARRAY[
        CASE WHEN suggestion_id IS NULL THEN 'suggestion_id' END,
        CASE WHEN pnl_realized IS NULL THEN 'pnl_realized' END,
        CASE WHEN pnl_predicted IS NULL THEN 'pnl_predicted' END,
        CASE WHEN trace_id IS NULL THEN 'trace_id' END
    ], NULL) AS missing_fields,
    'Outcome missing link or PnL data'::text AS notes
FROM learning_feedback_loops
WHERE outcome_type IN ('trade_closed', 'individual_trade')
  AND (suggestion_id IS NULL OR pnl_realized IS NULL OR pnl_predicted IS NULL OR trace_id IS NULL);
