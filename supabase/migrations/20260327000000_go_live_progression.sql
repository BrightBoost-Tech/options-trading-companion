-- Go-Live Progression: single-source-of-truth state machine.
-- Replaces the 20+ column v3_go_live_state with a clean 3-phase model.
--
-- Phases: alpaca_paper → micro_live → full_auto
-- Gate from alpaca_paper → micro_live: N consecutive green days (default 4)
-- Gate from micro_live → full_auto: manual promotion (for now)

CREATE TABLE IF NOT EXISTS go_live_progression (
    user_id                         uuid PRIMARY KEY,

    -- Current phase
    current_phase                   text NOT NULL DEFAULT 'alpaca_paper'
        CHECK (current_phase IN ('alpaca_paper', 'micro_live', 'full_auto')),

    -- Alpaca Paper gate
    alpaca_paper_green_days         integer NOT NULL DEFAULT 0,
    alpaca_paper_green_days_required integer NOT NULL DEFAULT 4,
    alpaca_paper_last_green_date    date,
    alpaca_paper_started_at         timestamptz,
    alpaca_paper_completed_at       timestamptz,

    -- Micro Live gate (manual promotion for now)
    micro_live_started_at           timestamptz,
    micro_live_completed_at         timestamptz,

    -- Full Auto
    full_auto_started_at            timestamptz,

    -- Metadata
    created_at                      timestamptz DEFAULT now(),
    updated_at                      timestamptz DEFAULT now()
);

-- Append-only audit trail
CREATE TABLE IF NOT EXISTS go_live_progression_log (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL,
    event_type  text NOT NULL,  -- 'green_day', 'red_day', 'promotion', 'manual_override'
    from_phase  text,
    to_phase    text,
    details     jsonb,
    created_at  timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_go_live_progression_log_user
  ON go_live_progression_log(user_id, created_at DESC);

-- RLS
ALTER TABLE go_live_progression ENABLE ROW LEVEL SECURITY;
ALTER TABLE go_live_progression_log ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own progression"
  ON go_live_progression FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Service role full access progression"
  ON go_live_progression FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "Users can view own progression log"
  ON go_live_progression_log FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Service role full access progression log"
  ON go_live_progression_log FOR ALL USING (auth.role() = 'service_role');

-- Seed from existing v3_go_live_state for users that passed paper validation
INSERT INTO go_live_progression (user_id, current_phase, alpaca_paper_started_at)
SELECT user_id, 'alpaca_paper', now()
FROM v3_go_live_state
WHERE paper_ready = true
ON CONFLICT (user_id) DO NOTHING;

NOTIFY pgrst, 'reload schema';
