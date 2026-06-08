-- Layer-1 exit mark-sanity gate — OBSERVE-ONLY corroboration record.
--
-- One row per mark-derived exit fire (target_profit / stop_loss) when
-- EXIT_MARK_SANITY_OBSERVE_ENABLED. Records the mark the monitor ACTED on
-- vs the ACHIEVABLE close from the executable side of live two-sided leg
-- quotes (sell→bid, buy→ask) — the realistic net a close would get now.
-- The 2026-06-08 13:30:02Z NFLX fire acted on a phantom opening-auction
-- mark (+$325) the position never held; the achievable close was ~−$36
-- (P85 bid 4.28 − P79 ask 1.38 = 2.90 vs 3.08 entry, one leg quoting 0.0).
--
-- This table RECORDS; it changes NO exit decision. would_suppress is a
-- LOGGED HYPOTHESIS, never enforced (no exit-path branch reads this table).
-- Asymmetric by design: would_suppress may be TRUE only for target_profit
-- (a phantom-profit fire stages a sell-limit ABOVE the real market that
-- can't fill anyway, so suppressing costs nothing); for stop_loss it is
-- ALWAYS false (a real adverse move looks structurally identical to a
-- phantom — low mark, wide/one-sided quotes — so suppressing would gag the
-- protection exactly when needed; the loss side is Layer-2's fill problem).
--
-- NO score, NO weights — raw components + verdict, same philosophy as the
-- other observe layers. The provisional tolerance is a labeled placeholder,
-- TO-BE-CALIBRATED from the observed divergence distribution; enforcement
-- (target_profit only) is a deferred Stage-2 decision, NOT built here.
--
-- Apply per docs/migration_procedure.md (migrations do not auto-apply).

CREATE TABLE IF NOT EXISTS exit_mark_corroboration_observations (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    observed_at             timestamptz NOT NULL DEFAULT now(),
    job_run_id              text,
    user_id                 text,
    position_id             text,
    symbol                  text,

    exit_type               text NOT NULL,   -- 'target_profit' | 'stop_loss'

    -- What the monitor acted on (the triggering mark)
    triggering_mark         numeric,
    triggering_implied_pl   numeric,

    -- Live per-leg quotes from the staging source (bid/ask/last + missing flags)
    legs_quotes             jsonb,
    quote_complete          boolean,

    -- Achievable close from the EXECUTABLE side (sell→bid, buy→ask)
    achievable_close        numeric,
    achievable_implied_pl   numeric,

    -- Divergence: triggering vs achievable
    divergence_abs          numeric,         -- triggering_implied_pl − achievable_implied_pl ($)
    divergence_frac         numeric,         -- price divergence as a fraction of spread width
    spread_width            numeric,         -- max strike − min strike (NULL for single-leg)

    -- Verdict (recorded, NEVER enforced)
    provisional_tolerance   numeric,         -- the placeholder used, for audit
    would_suppress          boolean NOT NULL DEFAULT false,
    suppress_reason         text,            -- quote_incomplete | divergence_exceeded |
                                             -- corroborated_allow | stop_loss_never_suppress |
                                             -- corroboration_error
    corroboration_error     text             -- nullable; set only on the fail-safe path
);

-- Distribution analysis queries by exit_type + verdict over time.
CREATE INDEX IF NOT EXISTS idx_exit_mark_corrob_type_time
    ON exit_mark_corroboration_observations (exit_type, observed_at);

CREATE INDEX IF NOT EXISTS idx_exit_mark_corrob_would_suppress
    ON exit_mark_corroboration_observations (would_suppress, observed_at);
