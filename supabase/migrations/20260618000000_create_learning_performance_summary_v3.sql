-- Migration: create learning_performance_summary_v3 (conviction multiplier source; #1043 / P2#1)
--
-- Gate A: ship epoch-filtered + DARK. No code flip ships with this — conviction
-- (analytics/conviction_service.py:283) already queries this view first and only falls
-- back to DEGRADED-legacy because it's absent. Creating it AUTO-flips conviction to v3;
-- the [CONVICTION] … DEGRADED line stops on the next worker recycle once it returns >=1
-- row. At current data depth every (strategy,window,regime) bucket has <20 trades, so
-- _compute_v3_multipliers returns all-1.0 — the view is live but inert (dark).
--
-- is_paper = false (live-only): this view drives LIVE entry ranking and MUST match the
-- live-applied calibration's training surface. As of 2026-06-18 calibration trains
-- live-only behind CALIBRATION_TRAIN_LIVE_ONLY (default ON) — see
-- analytics/calibration_service.py._train_live_only_enabled. Shipping the conviction view
-- is_paper-blind would re-introduce exactly the shadow-outvote class the calibration fix
-- removes (the 06-18 LONG_PUT ×1.5 incident: shadow NFLX outcomes outvoting the lone live
-- trade). One posture for both surfaces.
--
-- EPOCH/CORRUPTION HYGIENE BAKED IN: a Postgres view cannot read CALIBRATION_EV_EPOCH from
-- env. The relearn (calibration_service._fetch_outcomes) applies this wall in Python over
-- the epoch-UNFILTERED learning_trade_outcomes_v3; this view must mirror it or conviction
-- would train on the pre-#1051 sign-flipped rows the relearn excludes.
--   ⚠ LOCKSTEP: the two literals below duplicate calibration_service.py's
--   CALIBRATION_EV_EPOCH ("2026-06-11…") and CALIBRATION_PNL_FLOOR_DATE/CORRUPTED_PNL_FLOOR
--   ("2026-04-16…") defaults. If either env default changes, update this view via
--   CREATE OR REPLACE in the same change. A drift-guard test
--   (tests/test_calibration_live_only_v3.py) pins the epoch literal here == the source
--   default and fails the build if they diverge. Cross-ref comments live at both source
--   definition sites.

CREATE VIEW learning_performance_summary_v3 AS
SELECT
    user_id,
    strategy,
    "window",
    regime,
    count(*)                  AS total_trades,
    avg(pnl_realized)         AS avg_realized_pnl,
    stddev_samp(pnl_realized) AS std_realized_pnl,
    avg(pnl_predicted)        AS avg_predicted_ev,   -- $ basis, unit-matched to leakage
    avg(pnl_alpha)            AS avg_ev_leakage      -- pnl_alpha = pnl_realized - pnl_predicted
FROM learning_trade_outcomes_v3
WHERE closed_at >= GREATEST(
        '2026-06-11T00:00:00+00:00'::timestamptz,    -- = CALIBRATION_EV_EPOCH default
        '2026-04-16T00:00:00+00:00'::timestamptz)    -- = CORRUPTED_PNL_FLOOR default
  AND is_paper = false
GROUP BY user_id, strategy, "window", regime;
