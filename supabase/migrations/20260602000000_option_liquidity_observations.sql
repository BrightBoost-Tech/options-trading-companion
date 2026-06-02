-- Option-liquidity weighting — OBSERVATION-FIRST surface.
--
-- The 2026-06-02 post-#1012 re-derivation found the OPTION spread gate
-- (liquidity) is the dominant entry wall, and the universe's existing
-- liquidity_score is EQUITY-liquidity (market cap / share volume) — it ranks
-- liquid-stock / wide-option names (SNAP/NIO/AAL/LYFT) high, diluting scan
-- effort. This records a per-symbol OPTION-liquidity score (ATM bid-ask
-- relative spread, from the scan-time chain) so its prediction of the
-- spread-gate outcome is queryable BEFORE the score ever weights live
-- selection (the graduation criterion).
--
-- (1) one row per symbol per scan cycle: the score + the would-be weight.
--     The spread-gate OUTCOME side is correlated via suggestion_rejections
--     (per-symbol spread_too_wide* + spread_debug) and trade_suggestions
--     (per-symbol emissions) joined on symbol + cycle date.
-- (2) a rolling option_liquidity_score on scanner_universe so the weighting
--     (flag-gated, default OFF) can re-order the universe by it.
--
-- Apply per docs/migration_procedure.md (migrations do not auto-apply on merge).

CREATE TABLE IF NOT EXISTS option_liquidity_observations (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at      timestamptz NOT NULL DEFAULT now(),
    cycle_ts        text,
    symbol          text NOT NULL,
    underlying_price numeric,

    atm_rel_spread  numeric,    -- the raw signal (mean ATM call+put bid-ask rel spread)
    liquidity_score numeric,    -- 0-100 (high = tight = liquid); NULL when no NBBO
    would_be_weight numeric,    -- ranking priority multiplier (0.5-1.0); never a hard drop
    weighting_enabled boolean NOT NULL DEFAULT false,  -- was the flag ON this cycle

    assumptions     jsonb       -- the FLAGGED guessed thresholds, for calibration
);

CREATE INDEX IF NOT EXISTS idx_option_liq_obs_symbol_created
    ON option_liquidity_observations (symbol, created_at);
CREATE INDEX IF NOT EXISTS idx_option_liq_obs_created
    ON option_liquidity_observations (created_at);

-- Rolling per-symbol option-liquidity score (additive; NULL until first scan
-- populates it). Used ONLY when LIQUIDITY_WEIGHTING_ENABLED — the universe
-- ordering blends it with the existing equity liquidity_score. When the flag
-- is OFF this column is written (observe) but never read for ordering, so
-- selection stays byte-identical.
ALTER TABLE scanner_universe
    ADD COLUMN IF NOT EXISTS option_liquidity_score numeric;
