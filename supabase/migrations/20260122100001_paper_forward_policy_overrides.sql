-- Paper Forward Policy Overrides (v4-L1E)
--
-- Adds per-user policy override fields to v3_go_live_state.
-- These fields allow autopromote to configure checkpoint parameters
-- without changing the base go-live state schema.

-- Add policy override columns
ALTER TABLE v3_go_live_state
ADD COLUMN IF NOT EXISTS paper_forward_policy JSONB DEFAULT '{}'::jsonb;

ALTER TABLE v3_go_live_state
ADD COLUMN IF NOT EXISTS paper_forward_policy_source TEXT;

ALTER TABLE v3_go_live_state
ADD COLUMN IF NOT EXISTS paper_forward_policy_set_at TIMESTAMPTZ;

ALTER TABLE v3_go_live_state
ADD COLUMN IF NOT EXISTS paper_forward_policy_cohort TEXT;

COMMENT ON COLUMN v3_go_live_state.paper_forward_policy IS 'JSONB overrides for paper checkpoint params (paper_window_days, target_return_pct, fail_fast_*)';
COMMENT ON COLUMN v3_go_live_state.paper_forward_policy_source IS 'Source of policy: auto_promote, manual, or null (defaults)';
COMMENT ON COLUMN v3_go_live_state.paper_forward_policy_set_at IS 'When the policy was last updated';
COMMENT ON COLUMN v3_go_live_state.paper_forward_policy_cohort IS 'Name of the cohort whose params were promoted';
