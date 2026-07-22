-- Independent one-contract single-leg shadow experiment: durable foundation.
--
-- This migration creates only append-only experiment evidence and a persisted
-- epoch/binding control surface.  It registers no policy, creates no portfolio,
-- enables no experiment, places no order, and touches no existing trading row.

CREATE TABLE IF NOT EXISTS single_leg_experiment_epochs (
    epoch_name text PRIMARY KEY CHECK (btrim(epoch_name) <> ''),
    state text NOT NULL DEFAULT 'disabled'
        CHECK (state IN ('disabled', 'enabled', 'paused', 'retired')),
    routing_mode text NOT NULL DEFAULT 'shadow_only'
        CHECK (routing_mode = 'shadow_only'),
    max_contracts integer NOT NULL DEFAULT 1 CHECK (max_contracts = 1),
    live_submit_allowed boolean NOT NULL DEFAULT false
        CHECK (live_submit_allowed = false),
    config_hash text NOT NULL CHECK (btrim(config_hash) <> ''),
    version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by text,
    enabled_at timestamptz,
    enabled_by text,
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by text
);

CREATE TABLE IF NOT EXISTS single_leg_experiment_bindings (
    policy_registration_id text PRIMARY KEY
        REFERENCES policy_registrations(policy_registration_id) ON DELETE RESTRICT,
    epoch_name text NOT NULL
        REFERENCES single_leg_experiment_epochs(epoch_name) ON DELETE RESTRICT,
    portfolio_id uuid NOT NULL REFERENCES paper_portfolios(id) ON DELETE RESTRICT,
    user_id uuid NOT NULL,
    role text NOT NULL CHECK (role IN ('experimental', 'control')),
    routing_mode text NOT NULL DEFAULT 'shadow_only'
        CHECK (routing_mode = 'shadow_only'),
    execution_mode text NOT NULL DEFAULT 'internal_paper'
        CHECK (execution_mode = 'internal_paper'),
    enabled boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by text,
    UNIQUE (epoch_name, portfolio_id)
);

CREATE TABLE IF NOT EXISTS single_leg_shadow_runs (
    run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_job_run_id uuid NOT NULL,
    source_decision_id uuid NOT NULL,
    source_code_sha text,
    policy_epoch text NOT NULL
        REFERENCES single_leg_experiment_epochs(epoch_name) ON DELETE RESTRICT,
    policy_registration_id text NOT NULL
        REFERENCES policy_registrations(policy_registration_id) ON DELETE RESTRICT,
    portfolio_id uuid NOT NULL REFERENCES paper_portfolios(id) ON DELETE RESTRICT,
    user_id uuid NOT NULL,
    as_of timestamptz NOT NULL,
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'succeeded', 'partial', 'failed', 'cancelled')),
    counts jsonb NOT NULL DEFAULT '{}'::jsonb,
    error_details jsonb NOT NULL DEFAULT '[]'::jsonb,
    started_at timestamptz,
    finished_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_decision_id, policy_registration_id)
);

CREATE TABLE IF NOT EXISTS single_leg_shadow_attempts (
    attempt_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id uuid NOT NULL REFERENCES single_leg_shadow_runs(run_id) ON DELETE RESTRICT,
    policy_registration_id text NOT NULL
        REFERENCES policy_registrations(policy_registration_id) ON DELETE RESTRICT,
    user_id uuid NOT NULL,
    symbol text NOT NULL CHECK (btrim(symbol) <> ''),
    direction text CHECK (direction IS NULL OR direction IN ('bullish', 'bearish')),
    strategy_type text CHECK (strategy_type IS NULL OR strategy_type IN ('long_call', 'long_put')),
    stage text NOT NULL CHECK (stage IN (
        'selection_rejected',
        'gate_rejected',
        'candidate_generated',
        'execution_rejected'
    )),
    reason_code text,
    detail text,
    candidate_fingerprint text NOT NULL DEFAULT '',
    occ_symbol text,
    strike numeric,
    expiry date,
    debit_per_contract numeric,
    ev_expected_value numeric,
    ev_pop numeric,
    ev_basis text,
    ev_model text,
    considered_contracts integer CHECK (considered_contracts IS NULL OR considered_contracts >= 0),
    viable_contracts integer CHECK (viable_contracts IS NULL OR viable_contracts >= 0),
    provider text,
    known_at timestamptz,
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, policy_registration_id, symbol, stage, candidate_fingerprint)
);

CREATE TABLE IF NOT EXISTS single_leg_shadow_lifecycle_events (
    event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id uuid NOT NULL REFERENCES single_leg_shadow_runs(run_id) ON DELETE RESTRICT,
    policy_registration_id text NOT NULL
        REFERENCES policy_registrations(policy_registration_id) ON DELETE RESTRICT,
    user_id uuid NOT NULL,
    event_type text NOT NULL CHECK (event_type IN (
        'candidate_generated',
        'candidate_persisted',
        'execution_rejected',
        'order_created',
        'filled_internal',
        'position_opened',
        'position_closed',
        'outcome_recorded'
    )),
    entity_type text NOT NULL,
    entity_id text NOT NULL CHECK (btrim(entity_id) <> ''),
    candidate_fingerprint text,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, event_type, entity_type, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_single_leg_runs_source
    ON single_leg_shadow_runs (source_decision_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_single_leg_runs_policy
    ON single_leg_shadow_runs (policy_registration_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_single_leg_attempts_reason
    ON single_leg_shadow_attempts (stage, reason_code, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_single_leg_attempts_symbol
    ON single_leg_shadow_attempts (symbol, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_single_leg_events_type
    ON single_leg_shadow_lifecycle_events (event_type, occurred_at DESC);

CREATE OR REPLACE FUNCTION single_leg_epoch_guard()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
    IF NEW.routing_mode <> 'shadow_only'
       OR NEW.max_contracts <> 1
       OR NEW.live_submit_allowed IS DISTINCT FROM false THEN
        RAISE EXCEPTION 'single-leg experiment must remain one-contract shadow-only and non-live'
            USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.epoch_name IS DISTINCT FROM NEW.epoch_name THEN
        RAISE EXCEPTION 'single-leg experiment epoch_name is immutable'
            USING ERRCODE = 'restrict_violation';
    END IF;
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_single_leg_epoch_guard ON single_leg_experiment_epochs;
CREATE TRIGGER trg_single_leg_epoch_guard
    BEFORE UPDATE ON single_leg_experiment_epochs
    FOR EACH ROW EXECUTE FUNCTION single_leg_epoch_guard();

CREATE OR REPLACE FUNCTION single_leg_evidence_immutable()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END;
$$;

DROP TRIGGER IF EXISTS trg_single_leg_attempts_immutable ON single_leg_shadow_attempts;
CREATE TRIGGER trg_single_leg_attempts_immutable
    BEFORE UPDATE OR DELETE ON single_leg_shadow_attempts
    FOR EACH ROW EXECUTE FUNCTION single_leg_evidence_immutable();

DROP TRIGGER IF EXISTS trg_single_leg_events_immutable ON single_leg_shadow_lifecycle_events;
CREATE TRIGGER trg_single_leg_events_immutable
    BEFORE UPDATE OR DELETE ON single_leg_shadow_lifecycle_events
    FOR EACH ROW EXECUTE FUNCTION single_leg_evidence_immutable();

ALTER TABLE single_leg_experiment_epochs ENABLE ROW LEVEL SECURITY;
ALTER TABLE single_leg_experiment_bindings ENABLE ROW LEVEL SECURITY;
ALTER TABLE single_leg_shadow_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE single_leg_shadow_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE single_leg_shadow_lifecycle_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access single_leg_experiment_epochs"
    ON single_leg_experiment_epochs FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');
CREATE POLICY "Service role full access single_leg_experiment_bindings"
    ON single_leg_experiment_bindings FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');
CREATE POLICY "Service role full access single_leg_shadow_runs"
    ON single_leg_shadow_runs FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');
CREATE POLICY "Service role full access single_leg_shadow_attempts"
    ON single_leg_shadow_attempts FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');
CREATE POLICY "Service role full access single_leg_shadow_lifecycle_events"
    ON single_leg_shadow_lifecycle_events FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

REVOKE ALL ON single_leg_experiment_epochs FROM PUBLIC, anon, authenticated;
REVOKE ALL ON single_leg_experiment_bindings FROM PUBLIC, anon, authenticated;
REVOKE ALL ON single_leg_shadow_runs FROM PUBLIC, anon, authenticated;
REVOKE ALL ON single_leg_shadow_attempts FROM PUBLIC, anon, authenticated;
REVOKE ALL ON single_leg_shadow_lifecycle_events FROM PUBLIC, anon, authenticated;

GRANT SELECT, INSERT, UPDATE ON single_leg_experiment_epochs TO service_role;
GRANT SELECT, INSERT, UPDATE ON single_leg_experiment_bindings TO service_role;
GRANT SELECT, INSERT, UPDATE ON single_leg_shadow_runs TO service_role;
GRANT SELECT, INSERT ON single_leg_shadow_attempts TO service_role;
GRANT SELECT, INSERT ON single_leg_shadow_lifecycle_events TO service_role;

COMMENT ON TABLE single_leg_shadow_runs IS
    'Independent one-contract single-leg shadow experiment runs. Never a live suggestion stream.';
COMMENT ON TABLE single_leg_shadow_attempts IS
    'Append-only per-symbol selection/gate/candidate evidence for the single-leg shadow experiment.';
COMMENT ON TABLE single_leg_shadow_lifecycle_events IS
    'Append-only internal-paper lifecycle evidence isolated from broker-live learning and promotion.';