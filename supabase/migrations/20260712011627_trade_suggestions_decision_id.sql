-- Replay Phase-1 gap-(c) (2026-07-12): link a trade_suggestion to the
-- DecisionContext (decision_runs.decision_id) that produced it, so a
-- byte-compare decision replay has a left-hand side (the decided output) mapped
-- to the captured inputs/features. Nullable, forward-only; populated only when
-- REPLAY_ENABLE=1 (a DecisionContext is active). NULL for legacy / replay-off.
ALTER TABLE trade_suggestions ADD COLUMN IF NOT EXISTS decision_id uuid;
