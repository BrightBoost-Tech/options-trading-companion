-- Faithful base-table subset for the rpc_issue_fleet_reconciliation_receipt_v1
-- real-pg tests (Lane A/B). Mirrors the production columns the writer RPC reads
-- (verified against production information_schema on 2026-07-20):
--   * risk_alerts   (user_id uuid, metadata jsonb)      — marker in metadata
--   * paper_orders  (user_id uuid, broker_response jsonb) — marker in broker_response
--   * paper_ledger  (user_id uuid, metadata jsonb)       — marker in metadata
-- The three receipt migrations (D1 schema + Lane A writer + Lane B hardening)
-- are applied ON TOP of these tables by the conftest, verbatim.

-- Supabase-specific grant targets (absent in vanilla Postgres). The migrations
-- REVOKE from / GRANT to these, so they must exist first.
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

-- Mirror the production schema-wide default privilege that granted service_role
-- ALL on new public tables (pg_default_acl, grantor postgres, objtype 'r',
-- acl arwdDxtm) — so the Lane-B REVOKE is exercised against the REAL starting
-- state (service_role holding TRUNCATE/UPDATE/DELETE), not a clean table.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT ALL ON TABLES TO anon, authenticated, service_role;

-- auth.role() is a Supabase helper the RLS policy references. Provide a stub so
-- the D1 policy body is creatable in vanilla Postgres.
CREATE SCHEMA IF NOT EXISTS auth;
CREATE OR REPLACE FUNCTION auth.role() RETURNS text
    LANGUAGE sql STABLE AS $$ SELECT current_setting('request.jwt.claim.role', true) $$;

DROP TABLE IF EXISTS fleet_reconciliation_receipts CASCADE;
DROP TABLE IF EXISTS risk_alerts CASCADE;
DROP TABLE IF EXISTS paper_orders CASCADE;
DROP TABLE IF EXISTS paper_ledger CASCADE;

CREATE TABLE risk_alerts (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at  timestamptz DEFAULT now(),
    user_id     uuid,
    alert_type  text NOT NULL DEFAULT 'test',
    severity    text NOT NULL DEFAULT 'info',
    position_id uuid,
    symbol      text,
    message     text NOT NULL DEFAULT '',
    resolved    boolean DEFAULT false,
    resolved_at timestamptz,
    metadata    jsonb
);

CREATE TABLE paper_orders (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid NOT NULL,
    portfolio_id    uuid,
    status          text NOT NULL DEFAULT 'filled',
    order_json      jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at      timestamptz NOT NULL DEFAULT now(),
    cancelled_reason text,
    broker_response jsonb
);

CREATE TABLE paper_ledger (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       uuid NOT NULL,
    portfolio_id  uuid,
    amount        numeric NOT NULL DEFAULT 0,
    balance_after numeric NOT NULL DEFAULT 0,
    created_at    timestamptz NOT NULL DEFAULT now(),
    event_type    text,
    metadata      jsonb
);
