-- Fix: unique constraint should only apply to active suggestions.
-- Dismissed suggestions should not block new ones for the same
-- (user, cycle_date, ticker, strategy, legs_fingerprint).

DROP INDEX IF EXISTS unique_suggestion_per_cycle_v2;

CREATE UNIQUE INDEX unique_suggestion_per_cycle_v3
ON trade_suggestions (user_id, "window", cycle_date, ticker, strategy, legs_fingerprint)
WHERE status NOT IN ('dismissed', 'cancelled');

NOTIFY pgrst, 'reload schema';
