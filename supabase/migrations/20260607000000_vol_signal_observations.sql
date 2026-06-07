-- Stage 1 vol-signal OBSERVE layer — RAW COMPONENTS ONLY.
--
-- One row per trading day (when VOL_SIGNAL_OBSERVE_ENABLED): the in-house
-- synthetic vol-signal components (literal VIX-family data is NOT entitled —
-- 2026-06-06 feasibility read tested all 7 index tickers: NOT_AUTHORIZED).
-- Synthetic equivalents: SPY/QQQ/IWM IV30 from underlying_iv_points
-- (daily since 2026-02-19; VIX/VXN/RVX analogs), skew/term from SPY chains
-- via IVPointService, VIX-futures ETPs + cross-asset ETFs as stocks.
--
-- DELIBERATELY NO COMPOSITE SCORE COLUMN. Which components predict vol
-- expansion, and how to weight them, is DERIVED from this record in the
-- validation stage — persisting a weighted score now would bias that
-- analysis (the external doc's hardcoded weights are exactly what this
-- table exists to replace with evidence).
--
-- This table RECORDS; it changes NO live decision. Mirrors the D4
-- regime_filter_observations pattern (flag-gated, fail-soft, forward-only).
-- Forward-outcome columns are filled LATER by the same job's backfill pass,
-- never at snapshot time.
--
-- Apply per docs/migration_procedure.md (migrations do not auto-apply on merge).

CREATE TABLE IF NOT EXISTS vol_signal_observations (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at      timestamptz NOT NULL DEFAULT now(),
    snapshot_ts     text,
    as_of_date      date NOT NULL,

    -- H14 freshness stamp: how deep the percentile basis is. The synthetic
    -- IV30 series began 2026-02-19, so this grows daily; percentile fields
    -- must be read relative to this window, not as all-history ranks.
    history_window_days     integer,

    -- Vol levels (synthetic VIX/VXN/RVX analogs from underlying_iv_points)
    spy_iv30                numeric,
    spy_iv30_pctl           numeric,    -- percentile rank vs available history
    spy_iv30_chg_1d         numeric,
    spy_iv30_chg_5d         numeric,
    qqq_iv30                numeric,
    qqq_iv30_pctl           numeric,
    qqq_iv30_chg_1d         numeric,
    qqq_iv30_chg_5d         numeric,
    iwm_iv30                numeric,
    iwm_iv30_pctl           numeric,
    iwm_iv30_chg_1d         numeric,
    iwm_iv30_chg_5d         numeric,

    -- Skew / term structure (computed from SPY chains via IVPointService)
    spy_skew_25d            numeric,    -- (25d put IV - 25d call IV) / ATM IV
    spy_term_slope          numeric,    -- IV90 - IV30

    -- VIX-futures ETP proxies (stocks entitlement; futures roll, not spot)
    vxx_close               numeric,
    vxx_ret_1d              numeric,
    vxx_ret_5d              numeric,
    vixy_close              numeric,
    vixy_ret_1d             numeric,
    vixy_ret_5d             numeric,
    uvxy_close              numeric,
    uvxy_ret_1d             numeric,
    uvxy_ret_5d             numeric,
    svxy_close              numeric,
    svxy_ret_1d             numeric,
    svxy_ret_5d             numeric,

    -- Cross-asset returns
    hyg_ret_1d              numeric,
    hyg_ret_5d              numeric,
    tlt_ret_1d              numeric,
    tlt_ret_5d              numeric,
    ief_ret_1d              numeric,
    ief_ret_5d              numeric,
    lqd_ret_1d              numeric,
    lqd_ret_5d              numeric,
    uup_ret_1d              numeric,
    uup_ret_5d              numeric,

    -- Regime context (comparison only — read, never written back)
    live_regime_state       text,
    spy_rv_20d              numeric,    -- realized vol computed from stored spots

    -- Forward outcomes (filled LATER by the backfill pass; NULL at snapshot)
    vol_forward_1d          numeric,    -- SPY IV30(t+1) - IV30(t)
    vol_forward_3d          numeric,    -- SPY IV30(t+3) - IV30(t)
    spy_forward_1d          numeric,    -- SPY spot return t -> t+1
    spy_forward_3d          numeric,    -- SPY spot return t -> t+3
    book_forward_1d         numeric,    -- aggregate book unrealized_pl delta t -> t+1
    forwards_filled_at      timestamptz,

    -- Input provenance per field group: 'live' | 'computed' | 'missing'
    -- (#1015 weighting_enabled state-stamp convention). A missing input is
    -- FLAGGED here and its fields left NULL — never fabricated or defaulted
    -- (the stale-VIX-20.0 anti-pattern this layer exists to avoid).
    input_status            jsonb
);

-- One observation per trading day; the daily job upserts on this key.
CREATE UNIQUE INDEX IF NOT EXISTS idx_vol_signal_obs_as_of_date
    ON vol_signal_observations (as_of_date);

-- Backfill pass scans for unfilled forwards.
CREATE INDEX IF NOT EXISTS idx_vol_signal_obs_forwards_pending
    ON vol_signal_observations (as_of_date)
    WHERE forwards_filled_at IS NULL;
