-- PRE-migration subset of public.suggestion_rejections (the 20260513000005
-- shape, WITHOUT event_id) so the real-pg harness applies the P1-1 migration
-- (20260723150000) verbatim ON TOP and exercises the ADD COLUMN + partial
-- unique index against a live Postgres. Mirrors the production columns the
-- writer touches; the auth/RLS scaffolding is irrelevant to this migration and
-- omitted (self-contained ephemeral DB).

DROP TABLE IF EXISTS public.suggestion_rejections CASCADE;

CREATE TABLE public.suggestion_rejections (
  id BIGSERIAL PRIMARY KEY,
  symbol TEXT NOT NULL,
  strategy_key TEXT,
  reason TEXT NOT NULL,
  cycle_date DATE NOT NULL,
  job_run_id UUID,
  spread_debug JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT suggestion_rejections_reason_nonempty CHECK (reason <> '')
);
