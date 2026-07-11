-- PR-B (2026-07-11): restore COALESCE(ev_raw, ev) → ev_predicted (and pop) in
-- learning_trade_outcomes_v3. The guard was added 2026-04-11
-- (20260411000000, comment: "Calibration was training against its own
-- calibrated output (self-referential)") and SILENTLY REVERTED 2026-06-23
-- (20260623010000:58-59) back to bare ts.ev. Masked only by raw mode; the
-- instant calibration leaves raw mode the prequential validator + the live
-- calibrator would train on their OWN calibrated output (circular). Restoring
-- the coalesce heals it: ev_predicted = the RAW pre-calibration EV.
-- Drift-guarded by test_ev_raw_coalesce_drift_guard.py — a fourth revert is loud.
CREATE OR REPLACE VIEW learning_trade_outcomes_v3 AS
 SELECT lfl.user_id,
    COALESCE(lfl.updated_at, lfl.created_at) AS closed_at,
    lfl.trace_id,
    lfl.suggestion_id,
    lfl.execution_id,
    COALESCE(lfl.is_paper, (lfl.details_json ->> 'is_paper'::text)::boolean, false) AS is_paper,
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
    lfl.pnl_realized - lfl.pnl_predicted AS pnl_alpha,
    (lfl.details_json ->> 'pnl_execution_drag'::text)::numeric AS pnl_execution_drag,
    (lfl.details_json ->> 'fees_total'::text)::numeric AS fees_total,
    (lfl.details_json ->> 'entry_mid'::text)::numeric AS entry_mid,
    (lfl.details_json ->> 'exit_mid'::text)::numeric AS exit_mid,
    lfl.details_json -> 'reason_codes'::text AS reason_codes,
    lfl.entry_iv_rv_spread,
    lfl.realized_vol_over_hold,
    lfl.entry_ts
   FROM learning_feedback_loops lfl
     JOIN trade_suggestions ts ON lfl.suggestion_id = ts.id
  WHERE lfl.outcome_type = ANY (ARRAY['trade_closed'::text, 'individual_trade'::text]);
