-- Lane 4B (funnel phase-2): durable per-candidate terminal disposition.
--
-- FILE-ONLY until the operator applies it (docs/migration_procedure.md:
-- migration-before-merge for readers; the WRITER in
-- packages/quantum/services/candidate_disposition.py detects table absence
-- and typed-no-ops, so this file may land before it is applied).
--
-- WHY A NEW TABLE (verified against live schema 2026-07-17):
--   - suggestion_rejections: PK-unique only; no selected flag, no candidate
--     fingerprint, no cycle/attempt identity -> cannot represent
--     one-final-disposition-per-selected-candidate.
--   - trade_suggestions: unique_suggestion_per_cycle_v3 covers PERSISTED
--     rows only; the selected-but-never-persisted class (allocator/H7
--     deaths, the AAPL/IWM gap) never lands there.
--   - decision_runs / decision_inputs: cycle-level manifests, not
--     candidate-level.
--   - job_runs.result funnel counts: aggregate integers only.
--
-- Identity: (cycle_id, candidate_fingerprint, attempt); candidate_fingerprint
-- reuses the trade_suggestions legs_fingerprint convention (structure-only
-- legs hash), so persisted rows join on it directly.
--
-- Retention: append-only observability rows keyed by cycle_date; prune with
--   DELETE FROM candidate_terminal_dispositions WHERE cycle_date < :cutoff;
-- (idx_ctd_cycle_date makes this cheap). No FKs to auth.users /
-- trade_suggestions by design: disposition history must survive suggestion
-- pruning and never fail a cycle on referential order.

CREATE TABLE IF NOT EXISTS candidate_terminal_dispositions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  cycle_id uuid NOT NULL,
  cycle_date date NOT NULL,
  user_id uuid,
  "window" text NOT NULL DEFAULT 'midday_entry',
  symbol text NOT NULL,
  strategy text NOT NULL,
  candidate_fingerprint text NOT NULL,
  attempt integer NOT NULL DEFAULT 1,
  is_primary boolean NOT NULL DEFAULT true,
  selected boolean NOT NULL DEFAULT true,
  disposition text,
  is_final boolean NOT NULL DEFAULT false,
  suggestion_id uuid,
  detail jsonb,
  code_sha text,
  selected_at timestamptz,
  finalized_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (attempt >= 1),
  CHECK (disposition IS NULL OR disposition IN (
    'scanner_rejected',
    'h7_dropped',
    'allocator_dropped',
    'rank_blocked',
    'persisted_blocked',
    'persisted_executable',
    'staged',
    'broker_submitted',
    'filled',
    'superseded_retry'
  )),
  -- A final row must say WHAT the final disposition is.
  CHECK (NOT is_final OR disposition IS NOT NULL),
  -- One row per (cycle, candidate identity, attempt).
  UNIQUE (cycle_id, candidate_fingerprint, attempt)
);

-- EXACTLY ONE final disposition per (candidate identity, cycle) across
-- attempts. A newer attempt's final demotes the old one to
-- 'superseded_retry' (is_final=false) BEFORE claiming this slot — enforced
-- by the writer, guaranteed by this index.
CREATE UNIQUE INDEX IF NOT EXISTS idx_ctd_one_final_per_identity
  ON candidate_terminal_dispositions (cycle_id, candidate_fingerprint)
  WHERE is_final;

CREATE INDEX IF NOT EXISTS idx_ctd_cycle_date
  ON candidate_terminal_dispositions (cycle_date);

CREATE INDEX IF NOT EXISTS idx_ctd_symbol_date
  ON candidate_terminal_dispositions (symbol, cycle_date DESC);

CREATE INDEX IF NOT EXISTS idx_ctd_final_disposition_date
  ON candidate_terminal_dispositions (disposition, cycle_date DESC)
  WHERE is_final;

CREATE INDEX IF NOT EXISTS idx_ctd_suggestion
  ON candidate_terminal_dispositions (suggestion_id)
  WHERE suggestion_id IS NOT NULL;

ALTER TABLE candidate_terminal_dispositions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access candidate_terminal_dispositions"
  ON candidate_terminal_dispositions FOR ALL
  USING (auth.role() = 'service_role');

CREATE POLICY "Users can view own candidate_terminal_dispositions"
  ON candidate_terminal_dispositions FOR SELECT
  USING (auth.uid() = user_id);

COMMENT ON TABLE candidate_terminal_dispositions IS
  'Lane 4B: one final disposition per (selected candidate identity, cycle) '
  'with attempt rows preserved. Writer: services/candidate_disposition.py '
  '(observe-only, fail-soft).';
COMMENT ON COLUMN candidate_terminal_dispositions.candidate_fingerprint IS
  'Structure-only legs hash equal to the persisted legs_fingerprint '
  '(compute_legs_fingerprint convention).';
COMMENT ON COLUMN candidate_terminal_dispositions.cycle_id IS
  'Source decision/cycle id: replay DecisionContext decision_id when '
  'REPLAY_ENABLE is on, else a per-cycle UUID minted by the recorder.';
COMMENT ON COLUMN candidate_terminal_dispositions.is_primary IS
  'Primary/fallback strategy flag from the candidate (absent marker = primary).';
