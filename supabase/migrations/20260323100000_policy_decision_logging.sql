-- Policy Lab decision logging: tracks every accept/reject for every
-- (cohort, suggestion) pair. Enables learning from decisions that
-- DIDN'T happen, not just filled trades.

-- 1. Per-decision log
CREATE TABLE IF NOT EXISTS policy_decisions (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  cohort_id         uuid NOT NULL REFERENCES policy_lab_cohorts(id),
  suggestion_id     uuid NOT NULL,
  user_id           uuid NOT NULL,
  decision          text NOT NULL CHECK (decision IN ('accepted', 'rejected', 'filtered')),
  rank_at_decision  int,
  reason_codes      jsonb DEFAULT '[]',
  features_snapshot jsonb DEFAULT '{}',
  event_flags       jsonb DEFAULT '{}',
  simulated_fill    jsonb DEFAULT '{}',
  realized_outcome  jsonb,            -- backfilled by learning ingest
  created_at        timestamptz DEFAULT now(),
  UNIQUE(cohort_id, suggestion_id)    -- one decision per cohort per suggestion
);

CREATE INDEX IF NOT EXISTS idx_policy_decisions_user
  ON policy_decisions(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_policy_decisions_suggestion
  ON policy_decisions(suggestion_id);

CREATE INDEX IF NOT EXISTS idx_policy_decisions_cohort_decision
  ON policy_decisions(cohort_id, decision);

-- 2. Daily cohort utility scores
CREATE TABLE IF NOT EXISTS policy_daily_scores (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  cohort_id           uuid NOT NULL REFERENCES policy_lab_cohorts(id),
  trade_date          date NOT NULL,
  utility_score       numeric,
  realized_pnl        numeric DEFAULT 0,
  unrealized_pnl      numeric DEFAULT 0,
  max_drawdown_pct    numeric,
  expected_shortfall  numeric,
  execution_quality   numeric,
  calibration_quality numeric,
  trade_count         int DEFAULT 0,
  win_rate            numeric,
  avg_winner          numeric,
  avg_loser           numeric,
  regime_at_close     text,
  symbols_traded      jsonb DEFAULT '[]',
  created_at          timestamptz DEFAULT now(),
  UNIQUE(cohort_id, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_policy_daily_scores_cohort_date
  ON policy_daily_scores(cohort_id, trade_date DESC);

-- 3. RLS
ALTER TABLE policy_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE policy_daily_scores ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access policy_decisions"
  ON policy_decisions FOR ALL
  USING (auth.role() = 'service_role');

CREATE POLICY "Users can view own decisions"
  ON policy_decisions FOR SELECT
  USING (auth.uid() = user_id);

CREATE POLICY "Service role full access policy_daily_scores"
  ON policy_daily_scores FOR ALL
  USING (auth.role() = 'service_role');
