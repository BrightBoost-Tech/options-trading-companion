-- Walk-forward autotune history — records every parameter evaluation
-- with train/validate metrics for auditability.

CREATE TABLE IF NOT EXISTS autotune_history (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid NOT NULL,
    parameter_name  text NOT NULL,
    old_value       numeric,
    new_value       numeric,
    improvement_pct numeric,
    confidence      numeric,
    action          text,  -- 'promoted', 'demoted', 'recommended', 'rejected'
    train_trades    int,
    validate_trades int,
    metrics_snapshot jsonb,
    created_at      timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_autotune_history_user
  ON autotune_history(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_autotune_history_action
  ON autotune_history(action) WHERE action = 'promoted';

-- RLS
ALTER TABLE autotune_history ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own autotune history"
  ON autotune_history FOR SELECT
  USING (auth.uid() = user_id);

CREATE POLICY "Service role full access autotune"
  ON autotune_history FOR ALL
  USING (auth.role() = 'service_role');

NOTIFY pgrst, 'reload schema';
