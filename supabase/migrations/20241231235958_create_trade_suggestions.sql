-- Migration: 20241231235958_create_trade_suggestions.sql
-- Purpose: Create trade_suggestions table for self-contained schema bootstrap.
-- This runs before rls_hardening and later ALTER TABLE migrations.
-- All operations are idempotent (IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS trade_suggestions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NULL,

    -- Core suggestion fields
    ticker TEXT NULL,
    symbol TEXT NULL,  -- Some code uses symbol, some uses ticker
    strategy TEXT NULL,
    "window" TEXT NULL,
    direction TEXT NULL,
    status TEXT NOT NULL DEFAULT 'pending',

    -- Order details
    order_json JSONB NULL,
    sizing_metadata JSONB NULL,

    -- Analytics fields
    ev NUMERIC NULL,
    probability_of_profit NUMERIC NULL,

    -- Traceability (added by later migrations but included for completeness)
    trace_id UUID NULL,
    model_version TEXT NULL,
    features_hash TEXT NULL,
    regime TEXT NULL
);

-- Primary index for user queries
CREATE INDEX IF NOT EXISTS idx_trade_suggestions_user_created
    ON trade_suggestions(user_id, created_at DESC);

-- Index for trace lookups
CREATE INDEX IF NOT EXISTS idx_trade_suggestions_trace_id
    ON trade_suggestions(trace_id);

-- Index for status filtering
CREATE INDEX IF NOT EXISTS idx_trade_suggestions_status
    ON trade_suggestions(status);
