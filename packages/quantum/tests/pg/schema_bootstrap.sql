-- Faithful base-table subset for the rpc_commit_internal_close_v1 real-pg
-- transaction tests. Mirrors the production columns the function touches and
-- the CHECK constraints it must satisfy (verified against production
-- information_schema / pg_constraint on 2026-07-19):
--   * paper_positions.check_close_reason_enum (9 values or NULL)
--   * paper_positions.check_fill_source_enum  (4 values or NULL)
--   * paper_positions.close_path_required     (closed => fill_source+reason+realized_pl NOT NULL)
--   * paper_portfolios.routing_mode CHECK      ('live_eligible' | 'shadow_only')
-- The auth.users FK is intentionally omitted (self-contained ephemeral DB);
-- everything else the function reads/writes is present. The migration under
-- test (20260719180000_rpc_commit_internal_close_v1.sql) is applied verbatim
-- ON TOP of these tables by the conftest.

-- Supabase-specific grant targets (absent in vanilla Postgres). The migration
-- REVOKEs from / GRANTs to these, so they must exist first.
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

DROP TABLE IF EXISTS paper_ledger CASCADE;
DROP TABLE IF EXISTS paper_orders CASCADE;
DROP TABLE IF EXISTS paper_positions CASCADE;
DROP TABLE IF EXISTS paper_portfolios CASCADE;

CREATE TABLE paper_portfolios (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       uuid NOT NULL,
    name          text NOT NULL DEFAULT 'Main Paper',
    cash_balance  numeric NOT NULL DEFAULT 100000,
    net_liq       numeric NOT NULL DEFAULT 100000,
    created_at    timestamptz NOT NULL DEFAULT timezone('utc', now()),
    routing_mode  text NOT NULL DEFAULT 'live_eligible'
                  CHECK (routing_mode = ANY (ARRAY['live_eligible','shadow_only']))
);

CREATE TABLE paper_positions (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        uuid NOT NULL,
    portfolio_id   uuid NOT NULL REFERENCES paper_portfolios(id) ON DELETE CASCADE,
    symbol         text NOT NULL,
    strategy_key   text NOT NULL DEFAULT 'test_strategy',
    legs           jsonb NOT NULL DEFAULT '[]'::jsonb,
    avg_entry_price numeric NOT NULL DEFAULT 0,
    quantity       numeric NOT NULL DEFAULT 0,
    current_mark   numeric NOT NULL DEFAULT 0,
    unrealized_pl  numeric NOT NULL DEFAULT 0,
    created_at     timestamptz NOT NULL DEFAULT timezone('utc', now()),
    trace_id       uuid,
    updated_at     timestamptz DEFAULT now(),
    status         text DEFAULT 'open',
    close_reason   text,
    closed_at      timestamptz,
    realized_pl    numeric,
    fill_source    text,
    CONSTRAINT check_close_reason_enum CHECK (
        close_reason IS NULL OR close_reason = ANY (ARRAY[
            'target_profit_hit','stop_loss_hit','dte_threshold','expiration_day',
            'manual_close_user_initiated','alpaca_fill_reconciler_sign_corrected',
            'alpaca_fill_reconciler_standard','envelope_force_close','orphan_fill_repair'
        ])
    ),
    CONSTRAINT check_fill_source_enum CHECK (
        fill_source IS NULL OR fill_source = ANY (ARRAY[
            'alpaca_fill_reconciler','orphan_fill_repair','exit_evaluator','manual_endpoint'
        ])
    ),
    CONSTRAINT close_path_required CHECK (
        status IS DISTINCT FROM 'closed'
        OR closed_at < '2026-04-26 00:00:00+00'::timestamptz
        OR (fill_source IS NOT NULL AND close_reason IS NOT NULL AND realized_pl IS NOT NULL)
    )
);

CREATE TABLE paper_orders (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid NOT NULL,
    portfolio_id    uuid NOT NULL REFERENCES paper_portfolios(id) ON DELETE CASCADE,
    status          text NOT NULL DEFAULT 'filled',
    order_json      jsonb NOT NULL DEFAULT '{}'::jsonb,
    filled_qty      numeric,
    avg_fill_price  numeric,
    fees_usd        numeric DEFAULT 0,
    side            text,
    submitted_at    timestamptz,
    filled_at       timestamptz,
    created_at      timestamptz NOT NULL DEFAULT timezone('utc', now()),
    position_id     uuid,
    time_in_force   text DEFAULT 'DAY',
    execution_mode  text DEFAULT 'internal_paper',
    alpaca_order_id text,
    broker_status   text,
    broker_response jsonb
);

CREATE TABLE paper_ledger (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       uuid NOT NULL,
    portfolio_id  uuid NOT NULL REFERENCES paper_portfolios(id) ON DELETE CASCADE,
    order_id      uuid REFERENCES paper_orders(id) ON DELETE SET NULL,
    position_id   uuid,
    amount        numeric NOT NULL,
    description   text,
    balance_after numeric NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT timezone('utc', now()),
    event_type    text,
    trace_id      text,
    metadata      jsonb
);
