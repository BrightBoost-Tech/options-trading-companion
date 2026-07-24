-- Recurring independent shadow-fleet evaluator: additive decision evidence.
--
-- This migration creates ONLY append-only per-policy decision evidence for the
-- prospective 50-slot small_tier_v1 shadow fleet. It registers no policy,
-- activates no fleet, binds no micro-account, creates no portfolio, places no
-- order, and touches no existing trading row. Applying it cannot activate the
-- fleet or produce a single decision — every decision row is written only by a
-- future scan while the fleet is `active` (fleet is `pending_legacy_terminal`
-- today, so the evaluator is a true no-op).
--
-- WHY ADDITIVE (not policy_decisions reuse): policy_decisions is keyed to the
-- 3-cohort world (cohort_id NOT NULL FK to policy_lab_cohorts, UNIQUE
-- (cohort_id, suggestion_id), CHECK decision IN 3 values, CHECK
-- decision_event_id = suggestion_id + immutability trigger). The fleet's
-- evidence key (decision_event_id, fleet_epoch, shadow_micro_account_id), its 6
-- typed dispositions, and its no_candidate run-grain (no suggestion_id) are all
-- structurally inexpressible there, and it is the LIVE Policy-Lab table.
--
-- Two grains mirror single_leg_shadow_runs + single_leg_shadow_attempts:
--   * fleet_policy_decision_runs  — one row per (source scan event, micro-account)
--   * fleet_policy_decisions      — one row per (candidate suggestion, micro-account)
-- Evidence n = COUNT(DISTINCT decision_event_id) (small-tier contract), never
-- the row count.

CREATE TABLE IF NOT EXISTS fleet_policy_decision_runs (
    run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    fleet_id uuid NOT NULL REFERENCES shadow_fleets(id) ON DELETE RESTRICT,
    fleet_epoch text NOT NULL CHECK (fleet_epoch = 'small_tier_v1'),
    shadow_micro_account_id uuid NOT NULL
        REFERENCES shadow_micro_accounts(id) ON DELETE RESTRICT,
    policy_registration_id text NOT NULL
        REFERENCES policy_registrations(policy_registration_id) ON DELETE RESTRICT,
    source_decision_id uuid NOT NULL,
    source_job_run_id uuid,
    source_code_sha text,
    evaluator_version text NOT NULL DEFAULT 'fleet_policy_eval@1',
    user_id uuid NOT NULL,
    as_of timestamptz NOT NULL,
    status text NOT NULL DEFAULT 'running'
        CHECK (status IN (
            'running',
            'succeeded',
            'partial',
            'no_candidate',
            'data_unavailable',
            'evaluator_failed'
        )),
    counts jsonb NOT NULL DEFAULT '{}'::jsonb,
    error_details jsonb NOT NULL DEFAULT '[]'::jsonb,
    started_at timestamptz,
    finished_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    -- Idempotency: one policy's evaluation of one source scan event is unique.
    UNIQUE (source_decision_id, fleet_epoch, shadow_micro_account_id)
);

CREATE TABLE IF NOT EXISTS fleet_policy_decisions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id uuid NOT NULL
        REFERENCES fleet_policy_decision_runs(run_id) ON DELETE RESTRICT,
    fleet_id uuid NOT NULL REFERENCES shadow_fleets(id) ON DELETE RESTRICT,
    fleet_epoch text NOT NULL CHECK (fleet_epoch = 'small_tier_v1'),
    shadow_micro_account_id uuid NOT NULL
        REFERENCES shadow_micro_accounts(id) ON DELETE RESTRICT,
    policy_registration_id text NOT NULL
        REFERENCES policy_registrations(policy_registration_id) ON DELETE RESTRICT,
    -- Immutable statistical identity = the source SUGGESTION uuid (the candidate
    -- structure evaluated). candidate_suggestion_id equals it by construction.
    decision_event_id uuid NOT NULL,
    candidate_suggestion_id uuid NOT NULL,
    disposition text NOT NULL
        CHECK (disposition IN ('selected', 'policy_rejected', 'capital_rejected')),
    rank_at_decision integer CHECK (rank_at_decision IS NULL OR rank_at_decision >= 1),
    reason_codes jsonb NOT NULL DEFAULT '[]'::jsonb,
    features_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
    sizing jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (candidate_suggestion_id = decision_event_id),
    -- Doctrine statistical unit: one row per (candidate, micro-account).
    UNIQUE (decision_event_id, fleet_epoch, shadow_micro_account_id)
);

-- Prune / query indexes.
CREATE INDEX IF NOT EXISTS idx_fleet_decision_runs_source
    ON fleet_policy_decision_runs (source_decision_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_fleet_decision_runs_policy
    ON fleet_policy_decision_runs (policy_registration_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_fleet_decision_runs_micro
    ON fleet_policy_decision_runs (shadow_micro_account_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_fleet_decision_runs_epoch_created
    ON fleet_policy_decision_runs (fleet_epoch, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_fleet_decisions_run
    ON fleet_policy_decisions (run_id);
CREATE INDEX IF NOT EXISTS idx_fleet_decisions_event
    ON fleet_policy_decisions (decision_event_id);
CREATE INDEX IF NOT EXISTS idx_fleet_decisions_disposition
    ON fleet_policy_decisions (disposition, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_fleet_decisions_policy
    ON fleet_policy_decisions (policy_registration_id, created_at DESC);

-- fleet_policy_decisions is strictly append-only (evidence never mutates).
-- fleet_policy_decision_runs stays UPDATE-able for status/counts only (the
-- begin-run -> finish-run pattern of single_leg_shadow_runs); its identity
-- columns are guarded immutable below.
CREATE OR REPLACE FUNCTION fleet_policy_decisions_append_only()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END;
$$;

DROP TRIGGER IF EXISTS trg_fleet_policy_decisions_append_only ON fleet_policy_decisions;
CREATE TRIGGER trg_fleet_policy_decisions_append_only
    BEFORE UPDATE OR DELETE ON fleet_policy_decisions
    FOR EACH ROW EXECUTE FUNCTION fleet_policy_decisions_append_only();

CREATE OR REPLACE FUNCTION fleet_policy_decision_runs_identity_guard()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'fleet_policy_decision_runs is not deletable'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.run_id IS DISTINCT FROM NEW.run_id
       OR OLD.fleet_id IS DISTINCT FROM NEW.fleet_id
       OR OLD.fleet_epoch IS DISTINCT FROM NEW.fleet_epoch
       OR OLD.shadow_micro_account_id IS DISTINCT FROM NEW.shadow_micro_account_id
       OR OLD.policy_registration_id IS DISTINCT FROM NEW.policy_registration_id
       OR OLD.source_decision_id IS DISTINCT FROM NEW.source_decision_id
       OR OLD.user_id IS DISTINCT FROM NEW.user_id THEN
        RAISE EXCEPTION 'fleet_policy_decision_runs identity is immutable'
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_fleet_policy_decision_runs_identity ON fleet_policy_decision_runs;
CREATE TRIGGER trg_fleet_policy_decision_runs_identity
    BEFORE UPDATE OR DELETE ON fleet_policy_decision_runs
    FOR EACH ROW EXECUTE FUNCTION fleet_policy_decision_runs_identity_guard();

ALTER TABLE fleet_policy_decision_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE fleet_policy_decisions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access fleet_policy_decision_runs"
    ON fleet_policy_decision_runs FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');
CREATE POLICY "Service role full access fleet_policy_decisions"
    ON fleet_policy_decisions FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

CREATE POLICY "Users can view own fleet_policy_decision_runs"
    ON fleet_policy_decision_runs FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM shadow_fleets fleet
            WHERE fleet.id = fleet_policy_decision_runs.fleet_id
              AND fleet.user_id = auth.uid()
        )
    );
CREATE POLICY "Users can view own fleet_policy_decisions"
    ON fleet_policy_decisions FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM shadow_fleets fleet
            WHERE fleet.id = fleet_policy_decisions.fleet_id
              AND fleet.user_id = auth.uid()
        )
    );

REVOKE ALL ON fleet_policy_decision_runs FROM PUBLIC, anon, authenticated;
REVOKE ALL ON fleet_policy_decisions FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON fleet_policy_decision_runs TO service_role;
GRANT SELECT, INSERT ON fleet_policy_decisions TO service_role;

COMMENT ON TABLE fleet_policy_decision_runs IS
    'Recurring independent shadow-fleet evaluator: one row per (source scan event, micro-account). Decision evidence only — never a live suggestion, order, or broker row.';
COMMENT ON TABLE fleet_policy_decisions IS
    'Append-only per-(candidate,micro-account) fleet policy dispositions. Evidence n = COUNT(DISTINCT decision_event_id); decision_event_id is the immutable source suggestion uuid.';
COMMENT ON COLUMN fleet_policy_decisions.decision_event_id IS
    'Immutable source suggestion UUID (the evaluated candidate structure); COUNT(DISTINCT ...) is the statistical n.';
