-- v3 Observability & Model Governance Migration

-- 1. Extend analytics_events with typed columns for telemetry
ALTER TABLE analytics_events
ADD COLUMN IF NOT EXISTS suggestion_id uuid NULL,
ADD COLUMN IF NOT EXISTS execution_id uuid NULL,
ADD COLUMN IF NOT EXISTS model_version text NULL,
ADD COLUMN IF NOT EXISTS "window" text NULL,
ADD COLUMN IF NOT EXISTS strategy text NULL,
ADD COLUMN IF NOT EXISTS regime text NULL,
ADD COLUMN IF NOT EXISTS features_hash text NULL,
ADD COLUMN IF NOT EXISTS is_paper boolean NOT NULL DEFAULT false;

-- Ensure analytics_events.created_at exists (base table uses timestamp)
ALTER TABLE analytics_events
ADD COLUMN IF NOT EXISTS created_at timestamptz;

-- Backfill created_at from timestamp where missing
UPDATE analytics_events
SET created_at = COALESCE(timestamp, now())
WHERE created_at IS NULL;

-- Make created_at default now() for new rows
ALTER TABLE analytics_events
ALTER COLUMN created_at SET DEFAULT now();

-- Add indexes for performance
CREATE INDEX IF NOT EXISTS idx_analytics_trace_id ON analytics_events (trace_id);
CREATE INDEX IF NOT EXISTS idx_analytics_suggestion_id ON analytics_events (suggestion_id);
CREATE INDEX IF NOT EXISTS idx_analytics_model_context ON analytics_events (model_version, strategy, "window", regime);
CREATE INDEX IF NOT EXISTS idx_analytics_event_time ON analytics_events (event_name, created_at);

-- 2. Extend trade_suggestions with traceability fields
ALTER TABLE trade_suggestions
ADD COLUMN IF NOT EXISTS trace_id uuid NOT NULL DEFAULT gen_random_uuid(),
ADD COLUMN IF NOT EXISTS model_version text NOT NULL DEFAULT 'v2',
ADD COLUMN IF NOT EXISTS features_hash text NOT NULL DEFAULT 'unknown',
ADD COLUMN IF NOT EXISTS regime text NULL;

CREATE INDEX IF NOT EXISTS idx_suggestions_trace_id ON trade_suggestions (trace_id);
CREATE INDEX IF NOT EXISTS idx_suggestions_model_context ON trade_suggestions ("window", strategy, regime, model_version);

-- 3. Extend paper_orders (ensure traceability)
ALTER TABLE paper_orders ADD COLUMN IF NOT EXISTS trace_id uuid NULL;
CREATE INDEX IF NOT EXISTS idx_paper_orders_trace_id ON paper_orders (trace_id);

-- 4. Extend learning_feedback_loops for per-trade attribution
ALTER TABLE learning_feedback_loops
ADD COLUMN IF NOT EXISTS suggestion_id uuid NULL,
ADD COLUMN IF NOT EXISTS execution_id uuid NULL,
ADD COLUMN IF NOT EXISTS model_version text NULL,
ADD COLUMN IF NOT EXISTS features_hash text NULL,
ADD COLUMN IF NOT EXISTS is_paper boolean DEFAULT false,
ADD COLUMN IF NOT EXISTS pnl_realized numeric NULL,
ADD COLUMN IF NOT EXISTS pnl_predicted numeric NULL,
ADD COLUMN IF NOT EXISTS trace_id uuid NULL;

-- Ensure strategy, window, regime exist (additive if missing)
DO $$
BEGIN
    BEGIN
        ALTER TABLE learning_feedback_loops ADD COLUMN strategy text NULL;
    EXCEPTION
        WHEN duplicate_column THEN NULL;
    END;
    BEGIN
        ALTER TABLE learning_feedback_loops ADD COLUMN "window" text NULL;
    EXCEPTION
        WHEN duplicate_column THEN NULL;
    END;
    BEGIN
        ALTER TABLE learning_feedback_loops ADD COLUMN regime text NULL;
    EXCEPTION
        WHEN duplicate_column THEN NULL;
    END;
END $$;

-- 5. Create SQL Views

-- trade_attribution_v3 (row-per-trade view)
CREATE OR REPLACE VIEW trade_attribution_v3 AS
SELECT
    ts.trace_id,
    ts.id AS suggestion_id,
    ts.created_at AS suggestion_time,
    ts.ticker,
    ts.strategy,
    ts."window",
    ts.regime,
    ts.model_version,
    ts.features_hash,
    ts.ev AS predicted_ev,
    po.id AS execution_id,
    po.filled_at AS execution_time,
    po.status AS execution_status,
    lfl.pnl_realized,
    lfl.updated_at AS outcome_time,
    COALESCE(lfl.is_paper, false) AS is_paper
FROM trade_suggestions ts
LEFT JOIN paper_orders po ON ts.trace_id = po.trace_id
LEFT JOIN learning_feedback_loops lfl ON ts.id = lfl.suggestion_id;

-- ev_leakage_by_bucket_v3 (aggregate view)
CREATE OR REPLACE VIEW ev_leakage_by_bucket_v3 AS
SELECT
    model_version,
    strategy,
    "window",
    regime,
    COUNT(ts.id) AS suggestion_count,
    COUNT(po.id) AS execution_count,
    AVG(ts.ev) AS avg_predicted_ev,
    AVG(lfl.pnl_realized) AS avg_realized_pnl,
    (AVG(COALESCE(lfl.pnl_realized, 0)) - AVG(COALESCE(ts.ev, 0))) AS ev_leakage
FROM trade_suggestions ts
LEFT JOIN paper_orders po ON ts.trace_id = po.trace_id
LEFT JOIN learning_feedback_loops lfl ON ts.id = lfl.suggestion_id
GROUP BY model_version, strategy, "window", regime;
