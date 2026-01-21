-- v4-L1 Paper Forward Checkpoint Schema
-- Extends v3_go_live_state to support configurable paper window duration,
-- checkpoint target count, and fail-fast tracking.

-- Add configurable paper window duration (2-4 weeks, default 21 days / 3 weeks)
ALTER TABLE v3_go_live_state
ADD COLUMN IF NOT EXISTS paper_window_days INTEGER DEFAULT 21;

-- Add checkpoint target (number of passing checkpoints to "win")
ALTER TABLE v3_go_live_state
ADD COLUMN IF NOT EXISTS paper_checkpoint_target INTEGER DEFAULT 10;

-- Add last checkpoint run timestamp
ALTER TABLE v3_go_live_state
ADD COLUMN IF NOT EXISTS paper_checkpoint_last_run_at TIMESTAMPTZ;

-- Add fail-fast tracking
ALTER TABLE v3_go_live_state
ADD COLUMN IF NOT EXISTS paper_fail_fast_triggered BOOLEAN DEFAULT FALSE;

ALTER TABLE v3_go_live_state
ADD COLUMN IF NOT EXISTS paper_fail_fast_reason TEXT;

-- Clarify semantics of paper_consecutive_passes
COMMENT ON COLUMN v3_go_live_state.paper_consecutive_passes IS 'Counts consecutive passing CHECKPOINTS, not windows.';
