-- Regime V4 parallel shadow comparison — OBSERVE-ONLY durable evidence surface.
--
-- WHY (Audit-B): RegimeEngineV4 is BUILT BUT UNWIRED (zero live callers). To
-- learn whether V4 would AGREE with the live V3 regime — and whether the
-- disagreement would ever change strategy SELECTION — we run V4 as a parallel,
-- observe-only comparison beside live V3, per cycle, with ZERO new provider
-- calls (the child replays inputs V3 already fetched) and ZERO influence on any
-- live decision. This table is the only thing the child writes.
--
-- WHAT: one table, two row scopes (discriminated by `scope`):
--   'global' — ONE row per cycle. V3 global state/score/scaler/scoring_regime
--       vs V4 label/score/scaler/scoring_regime + the continuous v4_vector +
--       agreement flags. The only apples-to-apples level (both engines emit a
--       single global read).
--   'symbol' — one row per SCANNED symbol per cycle. V3 effective regime + live
--       candidate pool vs the V4-COUNTERFACTUAL effective regime (V4's global
--       run through V3's own per-symbol blend, sentiment/iv_rank held fixed) +
--       counterfactual pool + selection delta. V4 has no per-symbol dimension,
--       so a per-symbol V4 regime is NEVER fabricated.
--
-- DECISION IMPACT: none. The child (packages/quantum/analytics/
-- regime_v4_shadow_compare.py) runs on the `background` queue AFTER the V3 cycle
-- has already returned its suggestions, on COPIES of captured inputs. It writes
-- ONLY this table, never trade_suggestions / decision_runs / calibration / cohorts
-- / ops_control. Gate: REGIME_V4_OBSERVE_ENABLED (behavioral opt-in, default OFF)
-- gates the parent ENQUEUE only; the reserved REGIME_V4_ENABLED wiring gate is
-- untouched.
--
-- IDEMPOTENCY: one row per (cycle_id, code_sha, scope[, symbol]). `code_sha` in
-- the key means a redeploy legitimately re-observes the same cycle under new
-- code (an honest new row), while a child re-run under identical code is a no-op
-- upsert. `symbol` is NULL on global rows; a generated `symbol_key` column
-- (COALESCE(symbol,'__global__')) gives a non-null unique key so ON CONFLICT is
-- portable and null symbols dedup correctly.
--
-- JOIN: `decision_event_id` is a nullable join column (NOT part of the key) so a
-- later step can score the V4 counterfactual against realized P&L via the same
-- source-suggestion UUID.
--
-- RETENTION: diagnostics, not rows of record. No automated purger ships (matches
-- the option_quote_provenance / candidate_terminal_dispositions precedent).
-- Operator guidance:
--   DELETE FROM regime_v4_comparisons WHERE created_at < now() - interval '90 days';
--
-- PROVENANCE AXES (§10): `code_sha` = deployed code identity; `v3_model_version`
-- / `v4_model_version` = MODEL identity (a separate axis — never the app SHA).
--
-- Apply per docs/migration_procedure.md (migrations do not auto-apply on merge).
-- The child no-ops with a typed `table_missing_noops` counter while unapplied.

CREATE TABLE IF NOT EXISTS regime_v4_comparisons (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at         timestamptz NOT NULL DEFAULT now(),

    -- identity / provenance
    scope              text NOT NULL,          -- 'global' | 'symbol'
    cycle_id           text NOT NULL,          -- source decision/job id
    decision_event_id  uuid,                   -- nullable join to trade_suggestions/outcomes
    symbol             text,                   -- NULL on scope='global'
    symbol_key         text GENERATED ALWAYS AS (COALESCE(symbol, '__global__')) STORED,
    as_of_ts           text,                   -- V3 snapshot as_of (captured instant)
    known_at           text,                   -- child run UTC iso
    code_sha           text NOT NULL,          -- deploy identity
    v3_model_version   text,                   -- model identity (separate axis)
    v4_model_version   text,

    -- V3 (live authority)
    v3_state           text,
    v3_scoring_regime  text,
    v3_risk_score      numeric,
    v3_risk_scaler     numeric,
    v3_global_state    text,

    -- V4 (observe-only)
    v4_label           text,
    v4_scoring_regime  text,
    v4_risk_score      numeric,
    v4_risk_scaler     numeric,
    v4_vector          jsonb,

    -- agreement
    scoring_regime_agree boolean,
    state_agree          boolean,

    -- selection (scope='symbol' only; NULL on global)
    v3_effective_regime                 text,
    v4_counterfactual_effective_regime  text,
    v3_selection        jsonb,
    v4_selection        jsonb,
    selection_delta     jsonb,
    candidates_considered jsonb,
    sentiment           text,
    iv_rank             numeric,

    -- honesty
    missing_inputs      jsonb,                 -- typed reasons, never fabricated
    status              text NOT NULL,         -- 'ok' | 'partial' | 'unavailable'

    CONSTRAINT regime_v4_comparisons_scope_check
        CHECK (scope IN ('global', 'symbol'))
);

-- Idempotency: one row per identity. symbol_key is non-null so null symbols on
-- global rows dedup correctly under a standard unique index.
CREATE UNIQUE INDEX IF NOT EXISTS idx_rv4_identity
    ON regime_v4_comparisons (cycle_id, code_sha, scope, symbol_key);

-- Query the disagreements + the selection-changing symbols.
CREATE INDEX IF NOT EXISTS idx_rv4_cycle_created
    ON regime_v4_comparisons (cycle_id, created_at);
CREATE INDEX IF NOT EXISTS idx_rv4_scope_created
    ON regime_v4_comparisons (scope, created_at);
-- Partial index: rows where the V4 counterfactual would change selection.
CREATE INDEX IF NOT EXISTS idx_rv4_selection_changed
    ON regime_v4_comparisons (symbol, created_at)
    WHERE scope = 'symbol' AND (selection_delta ->> 'changed') = 'true';
-- Retention scan.
CREATE INDEX IF NOT EXISTS idx_rv4_created
    ON regime_v4_comparisons (created_at);

ALTER TABLE regime_v4_comparisons ENABLE ROW LEVEL SECURITY;

-- Service-role writer only (background worker inserts); append-only, no
-- user-scoped rows exist.
CREATE POLICY "Service role full access regime_v4_comparisons"
  ON regime_v4_comparisons FOR ALL
  USING (auth.role() = 'service_role');
