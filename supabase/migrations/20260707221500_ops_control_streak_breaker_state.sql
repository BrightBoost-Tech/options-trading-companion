-- Edge-trigger breaker amendment (2026-07-07): content-based window
-- fingerprint state for the streak breaker. Stamped by code AT TRIP TIME
-- ({"last_tripped_fingerprint": [row ids], "tripped_at": iso}); read by the
-- edge-trigger suppression check. Additive + nullable: code reads it
-- null-tolerantly — no stamp, a NULL, or an unreadable value all fall back
-- to legacy level-trigger behavior (fail-toward-tripping). The operator's
-- manual un-pause UPDATE never touches this column.
ALTER TABLE ops_control ADD COLUMN IF NOT EXISTS streak_breaker_state jsonb;
