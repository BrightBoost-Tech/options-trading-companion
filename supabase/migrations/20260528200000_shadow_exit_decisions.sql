-- D6 Phase 1: shadow exit-decision observation harness.
--
-- Logs, at each exit evaluation per open position, what each candidate GEOMETRY
-- exit rule (R1-R4) WOULD decide alongside the premium-% champion's ACTUAL
-- decision. OBSERVATION-ONLY: nothing in this table feeds the real exit/close
-- path. It is the empirical A/B evidence to later decide (separately) whether a
-- geometry rule beats premium-%. Queryable DB-side (no worker-log dependency).
--
-- Forward-only; no backfill (geometry was never computed for past evals).

CREATE TABLE IF NOT EXISTS shadow_exit_decisions (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id              UUID,
    position_id          UUID,
    symbol               TEXT,
    eval_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    underlying_spot      NUMERIC,          -- live spot at eval (NULL if unavailable)
    dte                  INTEGER,
    structure            TEXT,             -- e.g. debit_call_spread / n/a
    geometry             JSONB,            -- strikes/width/breakeven/distances/net_debit
    premium_pct_decision TEXT,             -- the ACTUAL champion decision ('hold' or trigger name)
    geometry_decisions   JSONB,            -- {R1:{decision,reason}, R1_frac:{...}, R2:{...}, R3:{...}, R4:{...}}
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_shadow_exit_decisions_position
    ON shadow_exit_decisions(position_id, eval_at DESC);
CREATE INDEX IF NOT EXISTS idx_shadow_exit_decisions_eval_at
    ON shadow_exit_decisions(eval_at DESC);

NOTIFY pgrst, 'reload schema';
