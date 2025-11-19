-- Initial schema for options trading companion

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Users table (app-level mirror; Supabase auth users live in auth.users)
CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT UNIQUE NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Broker connections
CREATE TABLE connections (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('active','inactive','error')),
  oauth_metadata JSONB,
  linked_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_connections_user_id ON connections(user_id);

-- Positions
CREATE TABLE positions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  symbol TEXT NOT NULL,
  qty NUMERIC NOT NULL,
  avg_price NUMERIC NOT NULL,
  greek_delta NUMERIC,
  greek_theta NUMERIC,
  greek_vega NUMERIC,
  iv_rank NUMERIC,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_positions_user_id ON positions(user_id);
CREATE INDEX idx_positions_symbol  ON positions(symbol);

-- Trades
CREATE TABLE trades (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  symbol TEXT NOT NULL,
  strategy_id TEXT NOT NULL,
  open_ts TIMESTAMPTZ NOT NULL,
  close_ts TIMESTAMPTZ,
  pnl_pct NUMERIC,
  legs_json JSONB NOT NULL,
  thesis_json JSONB,
  market_snapshot_json JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_trades_user_id ON trades(user_id);
CREATE INDEX idx_trades_symbol  ON trades(symbol);
CREATE INDEX idx_trades_open_ts ON trades(open_ts);

-- Guardrail rules
CREATE TABLE rules_guardrails (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  rule_key TEXT NOT NULL,
  rule_text TEXT NOT NULL,
  priority TEXT NOT NULL CHECK (priority IN ('low','medium','high')),
  enabled BOOLEAN DEFAULT TRUE,
  added_ts TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(user_id, rule_key)
);
CREATE INDEX idx_guardrails_user_id ON rules_guardrails(user_id);
CREATE INDEX idx_guardrails_enabled ON rules_guardrails(enabled);

-- Loss reviews
CREATE TABLE loss_reviews (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  trade_id UUID NOT NULL REFERENCES trades(id) ON DELETE CASCADE,
  root_cause TEXT NOT NULL,
  evidence_json JSONB NOT NULL,
  recommended_rule_json JSONB NOT NULL,
  confidence NUMERIC NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_loss_reviews_trade_id  ON loss_reviews(trade_id);
CREATE INDEX idx_loss_reviews_created_at ON loss_reviews(created_at);

-- Alerts
CREATE TABLE alerts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  payload_json JSONB NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('unread','read','archived')),
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_alerts_user_id ON alerts(user_id);
CREATE INDEX idx_alerts_status  ON alerts(status);

-- Settings
CREATE TABLE settings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  quantum_mode BOOLEAN DEFAULT FALSE,
  llm_budget_cents INT DEFAULT 1000,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_settings_user_id ON settings(user_id);

-- Market features (time-series)
CREATE TABLE market_features (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  symbol TEXT NOT NULL,
  spot NUMERIC NOT NULL,
  spread_bps NUMERIC,
  iv_rank NUMERIC,
  iv_percentile NUMERIC,
  rv_1m NUMERIC,
  rv_5m NUMERIC,
  rv_15m NUMERIC,
  vix_level NUMERIC,
  spx_trend NUMERIC,
  smile_slope NUMERIC,
  term_slope NUMERIC,
  days_to_earnings INT,
  oi_median NUMERIC,
  spread_bps_median NUMERIC,
  timestamp TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_market_features_symbol    ON market_features(symbol);
CREATE INDEX idx_market_features_timestamp ON market_features(timestamp);

-- LLM job tracking (optional)
CREATE TABLE llm_jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  job_type TEXT NOT NULL CHECK (job_type IN ('trade_scout','candidate_check','loss_review')),
  status   TEXT NOT NULL CHECK (status   IN ('pending','running','completed','failed')),
  input_json JSONB NOT NULL,
  output_json JSONB,
  cost_cents INT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  completed_at TIMESTAMPTZ
);
CREATE INDEX idx_llm_jobs_user_id ON llm_jobs(user_id);
CREATE INDEX idx_llm_jobs_status  ON llm_jobs(status);
