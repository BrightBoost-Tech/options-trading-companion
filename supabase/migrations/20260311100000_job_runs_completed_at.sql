-- Add completed_at column to job_runs (may already exist on production)
ALTER TABLE public.job_runs ADD COLUMN IF NOT EXISTS completed_at timestamptz NULL;

-- Update complete_job_run RPC to also set completed_at
CREATE OR REPLACE FUNCTION public.complete_job_run(p_job_id uuid, p_result jsonb)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_started_at timestamptz;
BEGIN
    SELECT started_at INTO v_started_at FROM public.job_runs WHERE id = p_job_id;

    UPDATE public.job_runs
    SET status = 'succeeded',
        finished_at = now(),
        completed_at = now(),
        result = p_result,
        locked_by = NULL,
        locked_at = NULL,
        duration_ms = CASE WHEN v_started_at IS NOT NULL THEN (EXTRACT(EPOCH FROM (now() - v_started_at)) * 1000)::int ELSE NULL END
    WHERE id = p_job_id;
END;
$$;

-- Update dead_letter_job_run RPC to also set completed_at
CREATE OR REPLACE FUNCTION public.dead_letter_job_run(p_job_id uuid, p_error jsonb)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_started_at timestamptz;
BEGIN
    SELECT started_at INTO v_started_at FROM public.job_runs WHERE id = p_job_id;

    UPDATE public.job_runs
    SET status = 'dead_lettered',
        finished_at = now(),
        completed_at = now(),
        error = p_error,
        locked_by = NULL,
        locked_at = NULL,
        duration_ms = CASE WHEN v_started_at IS NOT NULL THEN (EXTRACT(EPOCH FROM (now() - v_started_at)) * 1000)::int ELSE NULL END
    WHERE id = p_job_id;
END;
$$;

-- Backfill: set completed_at = finished_at for existing terminal records
UPDATE public.job_runs
SET completed_at = finished_at
WHERE status IN ('succeeded', 'dead_lettered')
  AND finished_at IS NOT NULL
  AND completed_at IS NULL;
