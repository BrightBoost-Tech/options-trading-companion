-- Shadow-to-expiry THESIS TRACKER (I5, 2026-07-11) — OBSERVE-ONLY.
-- One row per tracked closed position, scoring the ENTRY THESIS against the
-- underlying's price at the ORIGINAL expiry, independent of fills / P&L. This
-- converts every force-close into a completed counterfactual. Own table (NOT
-- LFL details_json) because only 13/83 closed positions carry a joinable
-- position_id on their LFL row — riding LFL would strand 70. Keyed on the
-- paper_positions PK (present on all). Writes nothing else; modulates nothing.
CREATE TABLE IF NOT EXISTS position_thesis_outcomes (
    position_id          uuid PRIMARY KEY,
    user_id              text,
    symbol               text,
    routing_mode         text,        -- live_eligible | shadow_only (cohort book)
    execution_mode       text,        -- closing order's mode (alpaca_live vs paper/internal) for the live/legacy split
    structure            text,        -- iron_condor | credit_vertical | debit_vertical | directional | unknown
    original_expiry      date,
    entry_date           date,
    close_reason         text,        -- coarse enum, if known (post-#1162; NULL for legacy)
    realized_pl          numeric,
    underlying_at_expiry numeric,     -- scored underlying close (NULL when unknown / in_progress)
    thesis_outcome       text NOT NULL,  -- hit | miss | unknown | in_progress
    thesis_basis         text,        -- human-readable scoring rationale
    scored_at            timestamptz NOT NULL DEFAULT now(),
    created_at           timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_position_thesis_outcome
    ON position_thesis_outcomes (thesis_outcome, original_expiry);
