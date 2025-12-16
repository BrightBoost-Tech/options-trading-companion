-- Migration: 20251220000001_job_runs_db_queue.sql

-- 1) Create table: public.job_runs
CREATE TABLE IF NOT EXISTS public.job_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_name text NOT NULL,
    idempotency_key text NOT NULL,
    status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'succeeded', 'failed_retryable', 'dead_lettered', 'cancelled')),
    attempt int NOT NULL DEFAULT 0,
    max_attempts int NOT NULL DEFAULT 5,
    scheduled_for timestamptz NOT NULL DEFAULT now(),
    run_after timestamptz NULL,
    started_at timestamptz NULL,
    finished_at timestamptz NULL,
    duration_ms int NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    result jsonb NULL,
    error jsonb NULL,
    locked_by text NULL,
    locked_at timestamptz NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- 3) Add constraints/indexes
ALTER TABLE public.job_runs
    ADD CONSTRAINT job_runs_job_name_idempotency_key_key UNIQUE (job_name, idempotency_key);

CREATE INDEX IF NOT EXISTS idx_job_runs_status_run_after ON public.job_runs (status, run_after);
CREATE INDEX IF NOT EXISTS idx_job_runs_job_name_created_at ON public.job_runs (job_name, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_job_runs_locked_at ON public.job_runs (locked_at);

-- 4) Add trigger to auto-update updated_at on update.
CREATE OR REPLACE FUNCTION public.update_job_runs_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_job_runs_updated_at_trigger ON public.job_runs;
CREATE TRIGGER update_job_runs_updated_at_trigger
    BEFORE UPDATE ON public.job_runs
    FOR EACH ROW
    EXECUTE FUNCTION public.update_job_runs_updated_at();

-- 5) Add RPC function (SECURITY DEFINER): public.claim_job_run(p_worker_id text)
CREATE OR REPLACE FUNCTION public.claim_job_run(p_worker_id text)
RETURNS SETOF public.job_runs
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_job_id uuid;
BEGIN
    SELECT id INTO v_job_id
    FROM public.job_runs
    WHERE status IN ('queued', 'failed_retryable')
      AND (run_after IS NULL OR run_after <= now())
      AND attempt < max_attempts
    ORDER BY scheduled_for ASC, created_at ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED;

    IF v_job_id IS NOT NULL THEN
        RETURN QUERY
        UPDATE public.job_runs
        SET status = 'running',
            locked_by = p_worker_id,
            locked_at = now(),
            started_at = COALESCE(started_at, now()),
            attempt = attempt + 1
        WHERE id = v_job_id
        RETURNING *;
    ELSE
        RETURN;
    END IF;
END;
$$;

-- 6) Add RPC function: public.requeue_job_run(p_job_id uuid, p_run_after timestamptz, p_error jsonb)
CREATE OR REPLACE FUNCTION public.requeue_job_run(p_job_id uuid, p_run_after timestamptz, p_error jsonb)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    UPDATE public.job_runs
    SET status = 'failed_retryable',
        run_after = p_run_after,
        error = p_error,
        locked_by = NULL,
        locked_at = NULL
    WHERE id = p_job_id;
END;
$$;

-- 7) Add RPC function: public.complete_job_run(p_job_id uuid, p_result jsonb)
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
        result = p_result,
        locked_by = NULL,
        locked_at = NULL,
        duration_ms = CASE WHEN v_started_at IS NOT NULL THEN (EXTRACT(EPOCH FROM (now() - v_started_at)) * 1000)::int ELSE NULL END
    WHERE id = p_job_id;
END;
$$;

-- 8) Add RPC function: public.dead_letter_job_run(p_job_id uuid, p_error jsonb)
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
        error = p_error,
        locked_by = NULL,
        locked_at = NULL,
        duration_ms = CASE WHEN v_started_at IS NOT NULL THEN (EXTRACT(EPOCH FROM (now() - v_started_at)) * 1000)::int ELSE NULL END
    WHERE id = p_job_id;
END;
$$;

-- RLS
ALTER TABLE public.job_runs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role can manage job_runs"
  ON public.job_runs FOR ALL
  USING ((auth.jwt()->>'role') = 'service_role');
