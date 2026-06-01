-- Paper-shadow executor — paired-experiment state machine + D6 realized record.
--
-- ONE row per signal/candidate per cycle. The row is BOTH:
--   (1) the executor's idempotent state machine (pair_state / arm_*_state), and
--   (2) the D6 realized A/B record (arm A premium-% vs arm B geometry: each
--       arm's entry/exit/realized P&L + which rule closed it + when).
--
-- Idempotency: UNIQUE(user_id, cycle_date, signal_key) → a candidate already
-- running in a cycle cannot be re-opened. State transitions are one-way
-- (pending_open → open → closing → closed → recorded); each loop action is
-- gated on state so re-running a cycle changes nothing it shouldn't.
--
-- Segregation: this is paper-regime OBSERVATION data (regime_tag, the synthetic
-- tier capital it was sized at, and a fill-optimism caveat). It is for D6
-- analysis ONLY and must NOT be ingested into live post_trade_learning — it
-- lives in its own table, never in learning_feedback_loops / paper_positions
-- learning views.
--
-- Apply per docs/migration_procedure.md (migrations do not auto-apply on merge).

CREATE TABLE IF NOT EXISTS paper_shadow_pairs (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         text NOT NULL,
    portfolio_id    text,
    cycle_date      date NOT NULL,
    signal_key      text NOT NULL,

    pair_state      text NOT NULL DEFAULT 'pending_open'
                    CHECK (pair_state IN ('pending_open','open','closing','closed','recorded')),

    -- arm A — premium-% champion exit
    arm_a_order_id      text,
    arm_a_position_id   text,
    arm_a_state         text NOT NULL DEFAULT 'pending_open'
                        CHECK (arm_a_state IN ('pending_open','open','closing','closed')),
    arm_a_entry_price   numeric,
    arm_a_exit_price    numeric,
    arm_a_realized_pl   numeric,
    arm_a_close_reason  text,
    arm_a_closed_at     timestamptz,

    -- arm B — canonical geometry exit
    arm_b_order_id      text,
    arm_b_position_id   text,
    arm_b_state         text NOT NULL DEFAULT 'pending_open'
                        CHECK (arm_b_state IN ('pending_open','open','closing','closed')),
    arm_b_entry_price   numeric,
    arm_b_exit_price    numeric,
    arm_b_realized_pl   numeric,
    arm_b_close_reason  text,
    arm_b_closed_at     timestamptz,

    -- D6 tags (paper-regime; relative-comparison valid, absolute fill optimistic)
    regime_tag          text NOT NULL DEFAULT 'paper_shadow',
    synthetic_capital   numeric NOT NULL,
    fill_caveat         text NOT NULL DEFAULT 'relative-comparison-valid; absolute-fill-optimistic',

    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),

    UNIQUE (user_id, cycle_date, signal_key)
);

CREATE INDEX IF NOT EXISTS idx_paper_shadow_pairs_state
    ON paper_shadow_pairs (user_id, pair_state);
