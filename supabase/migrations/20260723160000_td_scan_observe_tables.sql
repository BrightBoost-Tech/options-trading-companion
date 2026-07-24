-- ⑤ Terminal-distribution score-on-scan observer (observe-only, default OFF).
--
-- FILE-ONLY until the operator applies it (docs/migration_procedure.md:
-- migration-before-merge for readers). The parent-thread CAPTURE writer and the
-- background CHILD scorer both detect table absence and typed-no-op, so this
-- file may land before it is applied. Applied by the orchestrator BEFORE the
-- code merge.
--
-- WHY TWO TABLES (verified against the audit's §3 non-retention finding):
--   No existing durable surface carries the tuple {exact legs, spot, per-leg IV,
--   per-leg delta, net_premium, contracts, dte, known_at} for the REJECTED /
--   non-emitted population (suggestion_rejections has no legs; option_quote_
--   provenance is spread-gate-only + no spot/iv/delta; candidate_terminal_
--   dispositions stores identity+fate, not scorable inputs). The observer
--   therefore captures its own scorable ENVELOPE at scan time (td_scan_envelopes)
--   and, in a background child, writes the challenger-vs-baseline SCORES
--   (td_scan_scores). Both are append-only, observe-only, service-role-write.
--
-- BASIS: contracts = 1 (per structure-contract) — sizing is downstream of the
-- scan seam, so every score is per one structure-contract (stated on the row).
--
-- NON-INTERFERENCE: nothing here is read by any decision path. Pruning is a
-- plain DELETE by cycle_date (indexes below make it cheap).

-- ── 1. td_scan_envelopes — immutable scan-time capture (parent thread) ───────
CREATE TABLE IF NOT EXISTS td_scan_envelopes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  cycle_id uuid NOT NULL,
  cycle_date date NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  user_id uuid,
  symbol text NOT NULL,
  strategy text NOT NULL,                 -- DB vocab (e.g. LONG_CALL_DEBIT_SPREAD)
  strategy_key text,
  candidate_fingerprint text NOT NULL,    -- compute_legs_fingerprint (structure-only)
  emitted boolean NOT NULL DEFAULT false, -- resolved at scan-flush vs the emitted set
  reject_reason text,                     -- typed; unattributed-post-EV in v1
  reject_gate text,
  code_sha text,
  known_at text,                          -- provider snapshot ts, never wall-clock
  envelope jsonb NOT NULL,                -- §7a scorable inputs (legs+iv+delta+spot+dte+ev)
  -- One capture per structure per cycle (structure-only identity). A re-scan of
  -- the same cycle is fail-soft-ignored (23505) by the writer.
  UNIQUE (cycle_id, candidate_fingerprint)
);

CREATE INDEX IF NOT EXISTS idx_td_env_cycle_date
  ON td_scan_envelopes (cycle_date);
CREATE INDEX IF NOT EXISTS idx_td_env_cycle
  ON td_scan_envelopes (cycle_id);
CREATE INDEX IF NOT EXISTS idx_td_env_reject_date
  ON td_scan_envelopes (reject_reason, cycle_date);

ALTER TABLE td_scan_envelopes ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access td_scan_envelopes"
  ON td_scan_envelopes FOR ALL
  USING (auth.role() = 'service_role');

CREATE POLICY "Users can view own td_scan_envelopes"
  ON td_scan_envelopes FOR SELECT
  USING (auth.uid() = user_id);

COMMENT ON TABLE td_scan_envelopes IS
  '5: immutable scan-time research-candidate envelopes (every fully-constructed '
  'candidate, emitted AND rejected). Writer: services/td_scan_capture.py '
  '(observe-only, fail-soft, parent thread). Basis: contracts=1.';
COMMENT ON COLUMN td_scan_envelopes.candidate_fingerprint IS
  'Structure-only legs hash (compute_legs_fingerprint) = trade_suggestions.'
  'legs_fingerprint by construction, so a captured candidate that later '
  'persists/executes joins to its outcome for free.';

-- ── 2. td_scan_scores — challenger-vs-baseline score output (bg child) ───────
CREATE TABLE IF NOT EXISTS td_scan_scores (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  cycle_id uuid NOT NULL,
  cycle_date date NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  user_id uuid,
  symbol text NOT NULL,
  strategy text NOT NULL,
  candidate_fingerprint text NOT NULL,
  challenger_model_version text NOT NULL,   -- MODEL_SET_VERSION (disambiguates re-score)
  emitted boolean NOT NULL DEFAULT false,
  reject_reason text,
  reject_gate text,
  basis text NOT NULL DEFAULT 'raw',
  contracts_basis integer NOT NULL DEFAULT 1,
  envelope jsonb NOT NULL,                   -- the exact scored snapshot (provenance)
  -- frozen production-math baseline (offline re-run)
  baseline_pop numeric,
  baseline_ev numeric,
  baseline_model text,
  baseline_abstain_reason text,
  -- lognormal_v1 challenger
  challenger_pop numeric,
  challenger_ev numeric,
  challenger_model text,
  challenger_abstain_reason text,
  -- production as-emitted comparator (abstains for pre-emit rejects)
  production_pop numeric,
  production_ev numeric,
  -- rank + top-N membership over the identical scored set
  current_rank integer,
  challenger_rank integer,
  rank_delta integer,
  current_topn boolean,
  challenger_topn boolean,
  topn_delta integer,
  -- gate counterfactuals at UNCHANGED production thresholds (typed labels)
  gate_counterfactuals jsonb,
  -- outcome linkage (§6): real label ONLY for executed-and-closed candidates
  suggestion_id uuid,
  realized_pnl numeric,
  realized_win boolean,
  is_paper boolean,
  execution_mode text,
  outcome_status text NOT NULL DEFAULT 'counterfactual_unmarkable',
  provenance jsonb,
  -- Idempotency: one score per candidate per challenger model version per cycle.
  UNIQUE (cycle_id, candidate_fingerprint, challenger_model_version)
);

CREATE INDEX IF NOT EXISTS idx_td_scores_cycle_date
  ON td_scan_scores (cycle_date);
CREATE INDEX IF NOT EXISTS idx_td_scores_reject_date
  ON td_scan_scores (reject_reason, cycle_date);
CREATE INDEX IF NOT EXISTS idx_td_scores_suggestion
  ON td_scan_scores (suggestion_id)
  WHERE suggestion_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_td_scores_outcome
  ON td_scan_scores (outcome_status, cycle_date);

ALTER TABLE td_scan_scores ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access td_scan_scores"
  ON td_scan_scores FOR ALL
  USING (auth.role() = 'service_role');

CREATE POLICY "Users can view own td_scan_scores"
  ON td_scan_scores FOR SELECT
  USING (auth.uid() = user_id);

COMMENT ON TABLE td_scan_scores IS
  '5: per-candidate frozen-baseline vs lognormal-challenger scores over the '
  'scan-time envelopes (emitted AND rejected). Writer: services/td_scan_observe.py '
  'via scripts/analytics/td_scan_scorer.py (observe-only, background). Real '
  'realized label ONLY for executed-and-closed (outcome_status=resolved); '
  'everything else counterfactual_unmarkable, realized fields NULL.';
COMMENT ON COLUMN td_scan_scores.outcome_status IS
  'resolved (executed+closed, real Brier/EV/net) | open (persisted, not closed) '
  '| counterfactual_unmarkable (rejected/non-executed — realized fields NULL, '
  'never fabricated).';
