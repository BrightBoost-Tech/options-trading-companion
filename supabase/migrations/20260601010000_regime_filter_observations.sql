-- D4 regime_filter — OBSERVATION-ONLY shadow comparison table.
--
-- One row per regime cycle (when REGIME_FILTER_OBSERVE_ENABLED): the cross-asset
-- regime_filter's WOULD-BE throttle/sizing (from the existing TLT/HYG proxies;
-- VIX excluded as not-live per the Step-0 gate) alongside the LIVE regime
-- engine's ACTUAL decision that cycle, so divergences (where the filter would
-- have throttled/sized differently than the live engine did) are queryable.
--
-- This table RECORDS; it changes NO live decision. The regime_filter does not
-- alter the live regime classification, throttle, or sizing in this build —
-- graduating it to ACT is a separate future decision, gated on this record
-- showing agreement with reality. Forward-only.
--
-- Apply per docs/migration_procedure.md (migrations do not auto-apply on merge).

CREATE TABLE IF NOT EXISTS regime_filter_observations (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at      timestamptz NOT NULL DEFAULT now(),
    cycle_ts        text,

    -- regime_filter WOULD-BE (from proxies)
    rf_applicable           boolean NOT NULL DEFAULT true,
    rf_reason               text,
    rf_state                text,       -- SUPPRESSED/NORMAL/ELEVATED/SHOCK
    rf_scaler               numeric,    -- would-be sizing scaler (0.5–1.2)
    rf_would_hold           boolean,
    cross_asset_risk_score  numeric,
    rates_return_5d         numeric,    -- raw proxy reads (TLT)
    rates_rv                numeric,
    credit_return_5d        numeric,    -- raw proxy reads (HYG)
    credit_rv               numeric,
    vix_status              text,       -- 'absent_not_live' (Step-0 gate)

    -- live regime engine ACTUAL (v3) — what actually drove throttle/sizing
    live_state              text,
    live_risk_score         numeric,
    live_scaler             numeric,
    live_would_hold         boolean,

    -- divergence: rf vs live differed on state or would-hold (NULL when N/A)
    diverged                boolean,

    assumptions             jsonb       -- the FLAGGED guessed magnitudes, for calibration
);

CREATE INDEX IF NOT EXISTS idx_regime_filter_obs_diverged
    ON regime_filter_observations (diverged, created_at);
