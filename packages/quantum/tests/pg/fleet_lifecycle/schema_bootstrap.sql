-- Base tables for the fleet_shadow lifecycle real-pg tests. The C1 decision
-- foundation migration is applied on top of these (it creates
-- fleet_policy_decision_runs + fleet_policy_decisions), then the C2 lifecycle
-- migration under test. Only the columns the RPCs read/write are present.

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

CREATE SCHEMA IF NOT EXISTS auth;
CREATE OR REPLACE FUNCTION auth.role() RETURNS text
    LANGUAGE sql STABLE AS $$ SELECT current_setting('request.jwt.claim.role', true) $$;
CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid
    LANGUAGE sql STABLE AS $$ SELECT NULLIF(current_setting('request.jwt.claim.sub', true), '')::uuid $$;

DROP TABLE IF EXISTS fleet_shadow_cash_events CASCADE;
DROP TABLE IF EXISTS fleet_shadow_outcomes CASCADE;
DROP TABLE IF EXISTS fleet_shadow_positions CASCADE;
DROP TABLE IF EXISTS fleet_shadow_orders CASCADE;
DROP TABLE IF EXISTS fleet_policy_decisions CASCADE;
DROP TABLE IF EXISTS fleet_policy_decision_runs CASCADE;
DROP TABLE IF EXISTS shadow_micro_accounts CASCADE;
DROP TABLE IF EXISTS shadow_fleets CASCADE;
DROP TABLE IF EXISTS paper_portfolios CASCADE;
DROP TABLE IF EXISTS policy_registrations CASCADE;

CREATE TABLE policy_registrations (
    policy_registration_id text PRIMARY KEY,
    effective_epoch text NOT NULL DEFAULT 'small_tier_v1',
    approval_status text NOT NULL DEFAULT 'approved',
    policy_config jsonb NOT NULL DEFAULT '{}'::jsonb,
    config_hash text,
    schema_version integer NOT NULL DEFAULT 1
);

-- IMPORTANT: this MUST match the REAL production paper_portfolios shape exactly
-- so a migration referencing a non-existent column fails HERE instead of on
-- production. Verified live (information_schema, 2026-07-23): the columns are
-- id, user_id, name, cash_balance, net_liq, created_at, routing_mode — and there
-- is NO updated_at column. Do NOT add columns production lacks.
CREATE TABLE paper_portfolios (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL,
    name text NOT NULL DEFAULT 'Main Paper',
    cash_balance numeric NOT NULL DEFAULT 2000,
    net_liq numeric NOT NULL DEFAULT 2000,
    created_at timestamptz NOT NULL DEFAULT now(),
    routing_mode text NOT NULL DEFAULT 'shadow_only'
        CHECK (routing_mode = ANY (ARRAY['live_eligible', 'shadow_only']))
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
    portfolio_id uuid REFERENCES paper_portfolios(id),
    policy_registration_id text,
    state text NOT NULL DEFAULT 'inactive',
    initial_cash numeric NOT NULL DEFAULT 2000
);
