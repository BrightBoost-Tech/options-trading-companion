-- A4: entry-IV-vs-realized-vol-over-hold outcome capture.
--
-- Adds three NULLABLE typed columns to learning_feedback_loops — the table that
-- is BOTH the outcome write target (_create_paper_outcome_record,
-- paper_learning_ingest.py) AND the learning-loop read source
-- (post_trade_learning.py). One ALTER serves both, so the system can finally
-- grade its core edge: did cheap-IV entries realize higher vol over the hold?
--
--   entry_iv_rv_spread     = iv_rv_spread (atm_iv - rv_20d, log-return rv) AT
--                            ENTRY, carried from trade_suggestions over the
--                            existing suggestion_id join. NULL when the entry
--                            suggestion predates the VRP column or it was unset.
--   realized_vol_over_hold = annualized realized vol (log returns, ×√252,
--                            ddof=0) computed AT CLOSE over [entry_ts, closed_at]
--                            from daily closes. Computed ONCE at close, never on
--                            read. NULL for too-short holds or missing price data.
--   entry_ts               = paper_positions.opened_at, copied onto the outcome
--                            row so the hold window is self-contained (no
--                            position re-join needed to interpret the rv).
--
-- All nullable, no default, NO backfill: existing rows and any writer that does
-- not set these are unaffected. Writing NULL never breaks outcome recording
-- (failure-isolated in the handler).
--
-- NOT APPLIED in this session. Apply per docs/migration_procedure.md at the
-- desktop, alongside the still-pending VRP migration
-- (20260623000000_add_vrp_inputs_to_trade_suggestions.sql). entry_iv_rv_spread
-- only populates once that VRP migration is applied AND the scanner has written
-- iv_rv_spread on a fresh suggestion; until then it lands NULL by design.

ALTER TABLE learning_feedback_loops ADD COLUMN IF NOT EXISTS entry_iv_rv_spread numeric;
ALTER TABLE learning_feedback_loops ADD COLUMN IF NOT EXISTS realized_vol_over_hold numeric;
ALTER TABLE learning_feedback_loops ADD COLUMN IF NOT EXISTS entry_ts timestamptz;

-- Optional (low-risk, additive): surface the two grading fields in the v3 view
-- so calibration_service can read them without touching lfl directly. Columns
-- are appended at the end (CREATE OR REPLACE VIEW requires existing columns to
-- keep their position/order). Mirrors the existing view from
-- 20260122000000_fix_learning_trade_outcomes_is_paper.sql.
CREATE OR REPLACE VIEW learning_trade_outcomes_v3 AS
SELECT
    lfl.user_id,
    COALESCE(lfl.updated_at, lfl.created_at) AS closed_at,
    lfl.trace_id,
    lfl.suggestion_id,
    lfl.execution_id,
    COALESCE(
        lfl.is_paper,
        (lfl.details_json->>'is_paper')::boolean,
        false
    ) AS is_paper,
    COALESCE(lfl.model_version, ts.model_version) AS model_version,
    COALESCE(lfl.features_hash, ts.features_hash) AS features_hash,
    COALESCE(lfl.strategy, ts.strategy) AS strategy,
    COALESCE(lfl."window", ts."window") AS "window",
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
    lfl.details_json->'reason_codes' AS reason_codes,
    -- A4 grading fields (appended)
    lfl.entry_iv_rv_spread,
    lfl.realized_vol_over_hold,
    lfl.entry_ts
FROM learning_feedback_loops lfl
JOIN trade_suggestions ts ON lfl.suggestion_id = ts.id
WHERE lfl.outcome_type IN ('trade_closed', 'individual_trade');
