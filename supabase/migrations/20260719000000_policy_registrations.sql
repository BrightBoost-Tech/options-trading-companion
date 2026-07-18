-- =============================================================================
-- Versioned policy registry (Lane A): policy_registrations
-- =============================================================================
-- NOT APPLIED BY THIS PR. Schema only. Applying it creates the empty registry
-- table + immutability trigger + RLS; it registers NO policies. The 50 approved
-- rows land via the separate, operator-applied seed transaction
-- (supabase/seed-transactions/policy_registrations_seed_50.sql), whose content
-- is designed and pinned by packages/quantum/policy_lab/fleet_policy_design.py.
--
-- Why a DB table (not env, not a config file):
--   * The fleet activation RPC (20260717090000) stores a policy_registration_id
--     as OPAQUE text and validates only structure (50 unique non-blank ids) —
--     it never invents ids and has no source of record mapping an id to a
--     fully-specified policy. This table IS that source of record.
--   * Doctrine section 1: Supabase rows of record are authoritative; the DB is
--     runtime truth. The ENVIRONMENT stores only kill switches + the epoch
--     name — NEVER the catalog of 50 policies.
--
-- Immutability convention (enforced by the trigger below): once a row is
-- approval_status='approved', its identity + parameterization are frozen —
-- policy_registration_id / policy_config / config_canonical / config_hash /
-- schema_version can never change. An approved policy may still be transitioned
-- to 'retired' or 'revoked' (status change only); it can never be silently
-- re-parameterized under a stable id (that would let a bound fleet slot's
-- meaning drift out from under it). A new parameterization is a NEW row with a
-- NEW id (and, for the same epoch, a distinct config_hash).
--
-- config_hash is DERIVED, never client-invented: the seed transaction computes
-- encode(extensions.digest(config_canonical,'sha256'),'hex') server-side.
-- config_canonical is the deterministic serialization (sorted keys, compact
-- separators) that the hash is taken over; UNIQUE(effective_epoch, config_hash)
-- blocks two same-epoch rows with identical parameterization.
-- =============================================================================

CREATE TABLE IF NOT EXISTS policy_registrations (
    policy_registration_id text PRIMARY KEY
        CHECK (btrim(policy_registration_id) <> ''),
    policy_family text NOT NULL,
    anchor_lineage text NOT NULL,
    policy_config jsonb NOT NULL,
    config_canonical text NOT NULL,
    config_hash text NOT NULL,
    schema_version integer NOT NULL DEFAULT 1,
    approval_status text NOT NULL DEFAULT 'draft'
        CHECK (approval_status IN ('draft', 'approved', 'retired', 'revoked')),
    effective_epoch text NOT NULL,
    changed_axes jsonb,
    design_rationale text,
    created_at timestamptz NOT NULL DEFAULT now(),
    approved_at timestamptz,
    created_by text,
    -- No two rows in the same epoch may carry identical parameterization.
    UNIQUE (effective_epoch, config_hash)
);

CREATE INDEX IF NOT EXISTS idx_policy_registrations_epoch_status
    ON policy_registrations (effective_epoch, approval_status);

-- ── Immutability-after-approval trigger ──────────────────────────────────────
-- RAISEs on any UPDATE of a protected column while the row IS approved. Status
-- transitions (approved -> retired/revoked) and touching approved_at are
-- allowed; the frozen parameterization is not.
CREATE OR REPLACE FUNCTION policy_registrations_immutable_after_approval()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.approval_status = 'approved' THEN
        IF NEW.policy_registration_id IS DISTINCT FROM OLD.policy_registration_id
           OR NEW.policy_config       IS DISTINCT FROM OLD.policy_config
           OR NEW.config_canonical    IS DISTINCT FROM OLD.config_canonical
           OR NEW.config_hash         IS DISTINCT FROM OLD.config_hash
           OR NEW.schema_version      IS DISTINCT FROM OLD.schema_version
        THEN
            RAISE EXCEPTION
                'policy_registrations: % is approved — policy_registration_id / '
                'policy_config / config_canonical / config_hash / schema_version '
                'are immutable (retire or revoke instead of re-parameterizing)',
                OLD.policy_registration_id
                USING ERRCODE = 'restrict_violation';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_policy_registrations_immutable
    ON policy_registrations;

CREATE TRIGGER trg_policy_registrations_immutable
    BEFORE UPDATE ON policy_registrations
    FOR EACH ROW
    EXECUTE FUNCTION policy_registrations_immutable_after_approval();

-- ── Row-level security: operator-only (service_role) ─────────────────────────
ALTER TABLE policy_registrations ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Service role full access policy_registrations"
    ON policy_registrations;

CREATE POLICY "Service role full access policy_registrations"
    ON policy_registrations FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

-- ── Documentation ────────────────────────────────────────────────────────────
COMMENT ON TABLE policy_registrations IS
    'Versioned registry of fully-specified fleet trading policies (runtime '
    'truth; env stores only kill switches + epoch, never this catalog). Rows '
    'are immutable once approval_status=''approved'' (see trigger); a new '
    'parameterization is a new id. The fleet activation flow validates each '
    'slot id against approved rows for the fleet epoch.';
COMMENT ON COLUMN policy_registrations.policy_registration_id IS
    'Immutable human-readable PK (e.g. aggressive_anchor / agg_stop015_v1); the '
    'opaque id a fleet slot stores on shadow_micro_accounts.';
COMMENT ON COLUMN policy_registrations.anchor_lineage IS
    'Which of the 3 anchors (aggressive_anchor / neutral_anchor / '
    'conservative_anchor) this row derives from.';
COMMENT ON COLUMN policy_registrations.policy_config IS
    'Full PolicyConfig (same 11-field shape as policy_lab_cohorts.policy_config).';
COMMENT ON COLUMN policy_registrations.config_canonical IS
    'Deterministic canonical JSON of policy_config (sorted keys, compact '
    'separators, PolicyConfig-typed values). The exact bytes config_hash is '
    'taken over.';
COMMENT ON COLUMN policy_registrations.config_hash IS
    'SHA-256 hex of config_canonical. DERIVED (seed computes '
    'encode(extensions.digest(config_canonical,''sha256''),''hex'')), never '
    'client-invented independently.';
COMMENT ON COLUMN policy_registrations.approval_status IS
    'draft | approved | retired | revoked. Only ''approved'' rows may newly bind '
    'a fleet slot; retired/revoked can never newly bind.';
COMMENT ON COLUMN policy_registrations.effective_epoch IS
    'Epoch this registration is valid for (e.g. small_tier_v1 = the fleet '
    'epoch). The activation check matches on this.';
