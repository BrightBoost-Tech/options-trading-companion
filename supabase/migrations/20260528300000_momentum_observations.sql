-- D2 Phase 1: momentum / extended-move OBSERVE harness.
--
-- Logs, per suggestion per cycle, the momentum/extended-move signals (run-up,
-- distance-from-SMA, RSI, direction-alignment) and what a candidate EV-temper
-- WOULD do, alongside the suggestion's ACTUAL (unchanged) EV/score/rank.
-- OBSERVATION-ONLY: nothing here feeds selection or ranking. It is the evidence
-- to later test whether momentum-following entries underperform — and whether
-- any temper magnitude would have helped — before changing selection.
-- Queryable DB-side (no worker-log dependency). Forward-only; no backfill.

CREATE TABLE IF NOT EXISTS momentum_observations (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id            UUID,
    suggestion_id      UUID,          -- join key to realized outcomes later
    ticker             TEXT,
    cycle_date         DATE,
    direction          TEXT,          -- bullish | bearish | neutral
    signals            JSONB,         -- run_up_{5,10,20}d, dist_from_sma{20,50}, rsi, signed_run_up_in_direction, momentum_following
    actual_ev          NUMERIC,       -- the EV the ranker actually used (unchanged)
    actual_score       NUMERIC,
    actual_risk_adjusted_ev NUMERIC,
    actual_status      TEXT,          -- pending / NOT_EXECUTABLE / ... (selection outcome)
    tempers            JSONB,         -- {T1:{would_be_ev,would_be_score,driver,haircut}, T2:..., T3:..., T4:...}
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_momentum_observations_suggestion
    ON momentum_observations(suggestion_id);
CREATE INDEX IF NOT EXISTS idx_momentum_observations_cycle
    ON momentum_observations(cycle_date DESC);

NOTIFY pgrst, 'reload schema';
