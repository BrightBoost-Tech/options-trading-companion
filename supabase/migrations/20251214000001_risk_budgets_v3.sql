-- Migration: Risk & Capital Management v3
-- Supports risk budgeting and drawdown-aware sizing.

-- 1. Create risk_budget_policies table
CREATE TABLE IF NOT EXISTS risk_budget_policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    effective_from TIMESTAMPTZ NOT NULL DEFAULT now(),
    policy_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_risk_budget_policies_user_effective
    ON risk_budget_policies(user_id, effective_from DESC);

-- 2. Create risk_state table
CREATE TABLE IF NOT EXISTS risk_state (
    user_id UUID PRIMARY KEY,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    drawdown_30d NUMERIC NULL,
    consecutive_losses INT NULL,
    regime TEXT NULL,
    risk_multiplier NUMERIC NULL,
    state_json JSONB NULL
);

-- 3. Extend portfolio_snapshots
-- If table exists, add column; else create minimal table.
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    net_liquidity NUMERIC NULL,
    risk_metrics JSONB NULL
);

ALTER TABLE portfolio_snapshots ADD COLUMN IF NOT EXISTS risk_metrics JSONB NULL;

-- 4. Extend trade_suggestions
ALTER TABLE trade_suggestions ADD COLUMN IF NOT EXISTS risk_budget JSONB NULL;
ALTER TABLE trade_suggestions ADD COLUMN IF NOT EXISTS risk_multiplier NUMERIC NULL;
ALTER TABLE trade_suggestions ADD COLUMN IF NOT EXISTS max_loss_total NUMERIC NULL;
ALTER TABLE trade_suggestions ADD COLUMN IF NOT EXISTS capital_required NUMERIC NULL;

CREATE INDEX IF NOT EXISTS idx_suggestions_user_created
    ON trade_suggestions(user_id, created_at DESC);
