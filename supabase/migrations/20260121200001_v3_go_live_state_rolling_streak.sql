-- Phase 2.1.1: Add rolling streak columns to v3_go_live_state
-- Aligns schema with GoLiveValidationService.checkpoint_paper_streak() (PR #559)
--
-- New columns:
--   paper_streak_days: Consecutive passing days (reset on fail)
--   paper_last_checkpoint_at: Timestamp of last daily checkpoint
--   paper_checkpoint_window_days: Rolling window size (default 14 days)

-- Add columns (idempotent)
ALTER TABLE v3_go_live_state ADD COLUMN IF NOT EXISTS paper_streak_days INTEGER DEFAULT 0;
ALTER TABLE v3_go_live_state ADD COLUMN IF NOT EXISTS paper_last_checkpoint_at TIMESTAMPTZ;
ALTER TABLE v3_go_live_state ADD COLUMN IF NOT EXISTS paper_checkpoint_window_days INTEGER DEFAULT 14;

-- Backfill existing rows safely (idempotent)
UPDATE v3_go_live_state
SET paper_streak_days = 0
WHERE paper_streak_days IS NULL;

UPDATE v3_go_live_state
SET paper_checkpoint_window_days = 14
WHERE paper_checkpoint_window_days IS NULL;

-- Note: paper_last_checkpoint_at can remain NULL for existing rows
-- (indicates no checkpoint has been run yet)

-- Index on user_id (primary key already exists, but ensure lookup is fast)
-- Skipped: user_id is already the primary key
