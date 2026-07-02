-- P1-C 2026-07-02: corroborated-mark persistence (MTM mark-write corroboration).
-- ADDITIVE, all nullable — the raw current_mark/unrealized_pl keep their
-- original columns untouched (move-don't-lose; fast loss paths and the
-- close-limit read are byte-identical). Written by refresh_marks + the
-- monitor's Part-B persist via exit_mark_corroboration.corroborated_mark_fields;
-- read by policy_lab cohort scoring (drawdown → champion auto-rollback) and
-- the go-live checkpoint. NULL = quotes dark/incomplete at write time (H9 —
-- never fabricated).
--
-- Apply per docs/migration_procedure.md BEFORE merging the code that writes
-- these columns (migration-before-merge).

ALTER TABLE public.paper_positions
  ADD COLUMN IF NOT EXISTS mark_corroborated numeric NULL,
  ADD COLUMN IF NOT EXISTS unrealized_pl_corroborated numeric NULL,
  ADD COLUMN IF NOT EXISTS mark_quality jsonb NULL;

COMMENT ON COLUMN public.paper_positions.mark_corroborated IS
  'Executable-side (long->bid, short->ask) per-contract close estimate at last mark write; NULL when quotes incomplete (P1-C 2026-07-02)';
COMMENT ON COLUMN public.paper_positions.unrealized_pl_corroborated IS
  'Achievable implied P&L at last mark write (#1034 basis); governance readers prefer this over raw unrealized_pl';
COMMENT ON COLUMN public.paper_positions.mark_quality IS
  'Corroboration stamp: {basis, quote_complete, divergence_frac, corroborated_at}';
