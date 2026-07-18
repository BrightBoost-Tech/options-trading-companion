-- Option-quote provenance — Lane 4C, OBSERVE-ONLY durable evidence surface.
--
-- WHY (2026-07-16 gap): 429/fallback verdict-changes were NOT-PROVEN because
-- per-request quote-source evidence is ephemeral (log lines only). The truth
-- layer logs "[SNAPSHOT] Alpaca missed N option(s), falling back to Polygon"
-- and the scanner logs the spread-gate verdict, but neither survives to a
-- queryable row, so "truth-preserving fallback" vs "source-driven opportunity
-- loss" cannot be distinguished after the fact.
--
-- WHAT: one table, two row shapes (record_type):
--   'fetch_event' — a truth-layer boundary observation (snapshot_many options
--       path / option_chain): which source served, fallback reason
--       (429|miss|error), Alpaca HTTP statuses + rate-limit headers where
--       visible, requested_at/received_at, contracts that stayed dark.
--   'leg_set'     — a scanner spread-gate verdict for one candidate leg set:
--       verdict (rejected|passed), threshold applied, spread-calc basis
--       (denominator + combo source), per-leg quotes with per-leg source
--       provenance joined from the same cycle's fetch notes, selected flag
--       (stamped when the candidate was emitted), leg fingerprint.
--
-- DECISION IMPACT: none. The writer (packages/quantum/services/
-- quote_provenance.py) is fail-soft, observe-only, and changes NO scan
-- verdict, NO threshold, NO source preference. Kill: QUOTE_PROVENANCE_ENABLED
-- explicit falsy (default-ON additive observability).
--
-- VOLUME / SAMPLING (enforced in the writer, not the DB):
--   - per-cycle cap QUOTE_PROVENANCE_MAX_ROWS_PER_CYCLE (default 250);
--   - always persisted: fetch events with a fallback/non-200/error,
--     spread-REJECTED leg sets, SELECTED (emitted) leg sets;
--   - sampled 1-in-QUOTE_PROVENANCE_SAMPLE_N (default 10): clean fetch
--     events and passed-but-not-selected leg sets (rows carry sampled=true);
--   - expected volume: one scan cycle/day x <=250 rows ~= <=5.5k rows/month
--     worst case; typical cycles are far below the cap.
--
-- RETENTION: diagnostics, not rows of record. Operator guidance: purge at
-- 30 days once the fallback/verdict-change question is answered, e.g.
--   DELETE FROM option_quote_provenance
--    WHERE created_at < now() - interval '30 days';
-- No automated purger ships with this migration (matches the
-- option_liquidity_observations precedent).
--
-- SECRETS: the writer scrubs key-like fields and apiKey=/Bearer patterns
-- before insert; API keys/headers are never persisted (the truth layer's
-- key-prefix LOG line is deliberately not copied here).
--
-- LINKAGE: (symbol, strategy_key, cycle_date) joins suggestion_rejections
-- (same-cycle spread_debug) and trade_suggestions emissions; leg_fingerprint
-- identifies the exact leg set across rows.
--
-- Apply per docs/migration_procedure.md (migrations do not auto-apply on
-- merge). The writer no-ops with a typed counter while this is unapplied.

CREATE TABLE IF NOT EXISTS option_quote_provenance (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at        timestamptz NOT NULL DEFAULT now(),
    cycle_date        date,
    job_run_id        uuid,

    record_type       text NOT NULL,   -- 'fetch_event' | 'leg_set'
    boundary          text,            -- 'snapshot_many_options' | 'option_chain' | 'spread_gate'

    symbol            text,            -- underlying
    strategy_key      text,
    contract          text,            -- single-contract rows only (nullable)

    source            text,            -- 'alpaca' | 'polygon_fallback' | 'mixed' | 'unknown'
    fallback_reason   text,            -- '429' | 'miss' | 'error'
    http_statuses     jsonb,           -- Alpaca per-chunk/page statuses where visible

    requested_at      timestamptz,
    received_at       timestamptz,
    quote_ts_ms       bigint,          -- provider quote timestamp, normalized ms
    stale_age_ms      numeric,

    bid               numeric,
    ask               numeric,
    mid               numeric,
    crossed           boolean,
    zero_bid          boolean,

    verdict           text,            -- 'rejected' | 'passed' (leg_set rows)
    reject_reason     text,            -- spread_too_wide | spread_too_wide_real | entry_cost_too_low
    selected          boolean NOT NULL DEFAULT false,
    threshold         numeric,         -- effective spread threshold applied
    option_spread_pct numeric,
    spread_basis      jsonb,           -- {denominator_basis, combo_source, combo_width_share, entry_cost_share, max_loss_share}
    legs              jsonb,           -- per-leg: contract, side, bid, ask, mid, source, quote_ts_ms, stale_age_ms, from_cache, crossed, zero_bid
    leg_fingerprint   text,

    sampled           boolean NOT NULL DEFAULT false,
    details           jsonb
);

CREATE INDEX IF NOT EXISTS idx_oqp_cycle_date
    ON option_quote_provenance (cycle_date);
CREATE INDEX IF NOT EXISTS idx_oqp_symbol_created
    ON option_quote_provenance (symbol, created_at);
CREATE INDEX IF NOT EXISTS idx_oqp_record_type_created
    ON option_quote_provenance (record_type, created_at);
-- Partial index: the fallback/anomaly rows are the query target for the
-- source-driven-opportunity-loss question.
CREATE INDEX IF NOT EXISTS idx_oqp_fallback
    ON option_quote_provenance (fallback_reason, created_at)
    WHERE fallback_reason IS NOT NULL;

ALTER TABLE option_quote_provenance ENABLE ROW LEVEL SECURITY;

-- Service-role writer only (worker inserts); no user-scoped rows exist.
CREATE POLICY "Service role full access option_quote_provenance"
  ON option_quote_provenance FOR ALL
  USING (auth.role() = 'service_role');
