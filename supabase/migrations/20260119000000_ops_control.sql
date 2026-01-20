-- Migration: 20260119000000_ops_control.sql
-- v4-L5 Ops Console: Global operations control table

-- 1) Create table: public.ops_control
CREATE TABLE IF NOT EXISTS public.ops_control (
    key TEXT PRIMARY KEY DEFAULT 'global',
    mode TEXT NOT NULL DEFAULT 'paper' CHECK (mode IN ('paper', 'micro_live', 'live')),
    paused BOOLEAN NOT NULL DEFAULT TRUE,  -- safe by default
    pause_reason TEXT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by UUID NULL
);

-- 2) Add trigger to auto-update updated_at on update
CREATE OR REPLACE FUNCTION public.update_ops_control_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_ops_control_updated_at_trigger ON public.ops_control;
CREATE TRIGGER update_ops_control_updated_at_trigger
    BEFORE UPDATE ON public.ops_control
    FOR EACH ROW
    EXECUTE FUNCTION public.update_ops_control_updated_at();

-- 3) Seed the global row (UPSERT - insert if missing)
INSERT INTO public.ops_control (key, mode, paused, pause_reason)
VALUES ('global', 'paper', TRUE, 'Initial setup - paused for safety')
ON CONFLICT (key) DO NOTHING;

-- 4) RLS - service role only
ALTER TABLE public.ops_control ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role can manage ops_control"
  ON public.ops_control FOR ALL
  USING ((auth.jwt()->>'role') = 'service_role');

-- 5) Comment for documentation
COMMENT ON TABLE public.ops_control IS
    'v4-L5 Ops Console: Singleton global control for trading operations. '
    'Controls mode (paper/micro_live/live) and pause state.';
