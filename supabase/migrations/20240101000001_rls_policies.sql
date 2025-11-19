-- 20240101000001_rls_policies.sql
-- Enables Row Level Security (RLS) and defines policies.

-- Enable RLS on all tables
ALTER TABLE users            ENABLE ROW LEVEL SECURITY;
ALTER TABLE connections      ENABLE ROW LEVEL SECURITY;
ALTER TABLE positions        ENABLE ROW LEVEL SECURITY;
ALTER TABLE trades           ENABLE ROW LEVEL SECURITY;
ALTER TABLE rules_guardrails ENABLE ROW LEVEL SECURITY;
ALTER TABLE loss_reviews     ENABLE ROW LEVEL SECURITY;
ALTER TABLE alerts           ENABLE ROW LEVEL SECURITY;
ALTER TABLE settings         ENABLE ROW LEVEL SECURITY;
ALTER TABLE llm_jobs         ENABLE ROW LEVEL SECURITY;
ALTER TABLE market_features  ENABLE ROW LEVEL SECURITY;

-- Users
CREATE POLICY "Users can view own profile"
  ON users FOR SELECT
  USING (auth.uid() = id);

-- Connections
CREATE POLICY "Users can view own connections"
  ON connections FOR SELECT
  USING (auth.uid() = user_id);

CREATE POLICY "Users can update own connections"
  ON connections FOR UPDATE
  USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own connections"
  ON connections FOR INSERT
  WITH CHECK (auth.uid() = user_id);

-- Positions
CREATE POLICY "Users can view own positions"
  ON positions FOR SELECT
  USING (auth.uid() = user_id);

CREATE POLICY "Service role can manage positions"
  ON positions FOR ALL
  USING ((auth.jwt()->>'role') = 'service_role');

-- Trades
CREATE POLICY "Users can view own trades"
  ON trades FOR SELECT
  USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own trades"
  ON trades FOR INSERT
  WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Service role can manage trades"
  ON trades FOR ALL
  USING ((auth.jwt()->>'role') = 'service_role');

-- Guardrails
CREATE POLICY "Users can view own guardrails"
  ON rules_guardrails FOR SELECT
  USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own guardrails"
  ON rules_guardrails FOR INSERT
  WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own guardrails"
  ON rules_guardrails FOR UPDATE
  USING (auth.uid() = user_id);

CREATE POLICY "Service role can manage guardrails"
  ON rules_guardrails FOR ALL
  USING ((auth.jwt()->>'role') = 'service_role');

-- Loss reviews
CREATE POLICY "Users can view own loss reviews"
  ON loss_reviews FOR SELECT
  USING (EXISTS (
    SELECT 1 FROM trades
    WHERE trades.id = loss_reviews.trade_id
      AND trades.user_id = auth.uid()
  ));

CREATE POLICY "Service role can manage loss reviews"
  ON loss_reviews FOR ALL
  USING ((auth.jwt()->>'role') = 'service_role');

-- Alerts
CREATE POLICY "Users can view own alerts"
  ON alerts FOR SELECT
  USING (auth.uid() = user_id);

CREATE POLICY "Users can update own alerts"
  ON alerts FOR UPDATE
  USING (auth.uid() = user_id);

CREATE POLICY "Service role can manage alerts"
  ON alerts FOR ALL
  USING ((auth.jwt()->>'role') = 'service_role');

-- Settings
CREATE POLICY "Users can view own settings"
  ON settings FOR SELECT
  USING (auth.uid() = user_id);

CREATE POLICY "Users can update own settings"
  ON settings FOR UPDATE
  USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own settings"
  ON settings FOR INSERT
  WITH CHECK (auth.uid() = user_id);

-- LLM jobs
CREATE POLICY "Users can view own jobs"
  ON llm_jobs FOR SELECT
  USING (auth.uid() = user_id);

CREATE POLICY "Service role can manage jobs"
  ON llm_jobs FOR ALL
  USING ((auth.jwt()->>'role') = 'service_role');

-- Market features (read-only for authenticated users)
CREATE POLICY "Authenticated users can view market features"
  ON market_features FOR SELECT
  USING (auth.role() = 'authenticated');

CREATE POLICY "Service role can manage market features"
  ON market_features FOR ALL
  USING ((auth.jwt()->>'role') = 'service_role');
