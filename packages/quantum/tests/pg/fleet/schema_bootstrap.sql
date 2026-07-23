-- Faithful base-table subset for the fleet_policy_decision foundation real-pg
-- tests. Provides only the tables/roles the additive migration FK-references or
-- GRANTs to; the migration under test
-- (20260723160000_fleet_policy_decision_foundation.sql) is applied verbatim on
-- top of these by the conftest.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        CREATE ROLE service_role NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        CREATE ROLE anon NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        CREATE ROLE authenticated NOLOGIN;
    END IF;
END $$;

-- Supabase RLS helpers referenced by the migration's policies.
CREATE SCHEMA IF NOT EXISTS auth;
CREATE OR REPLACE FUNCTION auth.role() RETURNS text
    LANGUAGE sql STABLE AS $$ SELECT current_setting('request.jwt.claim.role', true) $$;
CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid
    LANGUAGE sql STABLE AS $$ SELECT NULLIF(current_setting('request.jwt.claim.sub', true), '')::uuid $$;

DROP TABLE IF EXISTS fleet_policy_decisions CASCADE;
DROP TABLE IF EXISTS fleet_policy_decision_runs CASCADE;
DROP TABLE IF EXISTS shadow_micro_accounts CASCADE;
DROP TABLE IF EXISTS shadow_fleets CASCADE;
DROP TABLE IF EXISTS policy_registrations CASCADE;

CREATE TABLE policy_registrations (
    policy_registration_id text PRIMARY KEY,
    effective_epoch text NOT NULL DEFAULT 'small_tier_v1',
    approval_status text NOT NULL DEFAULT 'approved',
    policy_config jsonb NOT NULL DEFAULT '{}'::jsonb,
    config_hash text,
    schema_version integer NOT NULL DEFAULT 1
);

CREATE TABLE shadow_fleets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL,
    epoch_name text NOT NULL DEFAULT 'small_tier_v1',
    status text NOT NULL DEFAULT 'pending_legacy_terminal'
);

CREATE TABLE shadow_micro_accounts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    fleet_id uuid NOT NULL REFERENCES shadow_fleets(id) ON DELETE CASCADE,
    slot_number integer NOT NULL,
    policy_registration_id text,
    state text NOT NULL DEFAULT 'inactive',
    initial_cash numeric NOT NULL DEFAULT 2000
);
