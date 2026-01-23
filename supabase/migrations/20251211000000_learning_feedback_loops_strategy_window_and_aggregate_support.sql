-- Migration to add support for aggregate columns in learning_feedback_loops
-- Created manually to fix schema mismatch

-- 1. Add missing columns safely
ALTER TABLE public.learning_feedback_loops
    ADD COLUMN IF NOT EXISTS strategy TEXT NULL,
    ADD COLUMN IF NOT EXISTS "window" TEXT NULL,
    ADD COLUMN IF NOT EXISTS total_trades INTEGER NULL,
    ADD COLUMN IF NOT EXISTS wins INTEGER NULL,
    ADD COLUMN IF NOT EXISTS losses INTEGER NULL,
    ADD COLUMN IF NOT EXISTS avg_return NUMERIC NULL,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NULL;

-- 2. Relax outcome_type constraint OR set default
-- We'll set a default to 'aggregate' and drop NOT NULL to be safe
ALTER TABLE public.learning_feedback_loops
    ALTER COLUMN outcome_type DROP NOT NULL,
    ALTER COLUMN outcome_type SET DEFAULT 'aggregate';

-- 3. Add index for faster aggregate lookups
CREATE INDEX IF NOT EXISTS idx_learning_feedback_agg
    ON public.learning_feedback_loops(user_id, strategy, "window", updated_at DESC);
