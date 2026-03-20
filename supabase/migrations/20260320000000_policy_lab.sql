-- Policy Lab: parallel paper trading cohorts with different risk policies
-- Each cohort shares the same forecast/scoring stack but applies different
-- sizing, filtering, and exit parameters.

-- 1. Add cohort_name to trade_suggestions for tagging
ALTER TABLE trade_suggestions ADD COLUMN IF NOT EXISTS cohort_name text;

-- 2. Cohort definitions and their policy configs
CREATE TABLE IF NOT EXISTS policy_lab_cohorts (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         uuid NOT NULL,
  cohort_name     text NOT NULL,
  portfolio_id    uuid NOT NULL REFERENCES paper_portfolios(id),
  policy_config   jsonb NOT NULL DEFAULT '{}',
  is_active       boolean DEFAULT true,
  promoted_at     timestamptz,
  created_at      timestamptz DEFAULT now(),
  UNIQUE(user_id, cohort_name)
);

CREATE INDEX IF NOT EXISTS idx_policy_lab_cohorts_user
  ON policy_lab_cohorts(user_id) WHERE is_active = true;

-- 3. Daily performance snapshot per cohort
CREATE TABLE IF NOT EXISTS policy_lab_daily_results (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  cohort_id       uuid NOT NULL REFERENCES policy_lab_cohorts(id),
  eval_date       date NOT NULL,
  positions_opened int DEFAULT 0,
  positions_closed int DEFAULT 0,
  realized_pl     numeric DEFAULT 0,
  unrealized_pl   numeric DEFAULT 0,
  total_pl        numeric DEFAULT 0,
  win_rate        numeric,
  max_drawdown    numeric,
  sharpe_estimate numeric,
  risk_budget_used numeric,
  capital_deployed numeric,
  created_at      timestamptz DEFAULT now(),
  UNIQUE(cohort_id, eval_date)
);

CREATE INDEX IF NOT EXISTS idx_policy_lab_results_cohort_date
  ON policy_lab_daily_results(cohort_id, eval_date DESC);

-- 4. Promotion audit log
CREATE TABLE IF NOT EXISTS policy_lab_promotions (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         uuid NOT NULL,
  promoted_cohort text NOT NULL,
  demoted_cohort  text,
  reason          text,
  metrics_snapshot jsonb,
  auto_promoted   boolean DEFAULT false,
  confirmed_by    text,
  created_at      timestamptz DEFAULT now()
);

-- 5. RLS policies (match existing paper trading pattern)
ALTER TABLE policy_lab_cohorts ENABLE ROW LEVEL SECURITY;
ALTER TABLE policy_lab_daily_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE policy_lab_promotions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own cohorts"
  ON policy_lab_cohorts FOR SELECT
  USING (auth.uid() = user_id);

CREATE POLICY "Service role full access cohorts"
  ON policy_lab_cohorts FOR ALL
  USING (auth.role() = 'service_role');

CREATE POLICY "Service role full access results"
  ON policy_lab_daily_results FOR ALL
  USING (auth.role() = 'service_role');

CREATE POLICY "Service role full access promotions"
  ON policy_lab_promotions FOR ALL
  USING (auth.role() = 'service_role');
