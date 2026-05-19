-- H9 generalization (silent decisions): universe selection log.
--
-- Origin: 2026-05-19 funnel diagnostic surfaced that 34 of 70 active
-- universe symbols never emit candidates. 19 of those (56%) were
-- silently dropped by universe_service.get_scan_candidates(limit=50)
-- — the bottom 20 symbols by liquidity_score never entered the
-- scanner loop, with no rejection record, no alert, no surface
-- anywhere.
--
-- Structurally identical anti-pattern to H9 (silent decision with no
-- verification surface), applied to universe selection rather than
-- error handling. This table closes the observability gap for the
-- selection boundary; the corresponding doctrine generalization
-- (silent-decision → verified-decision) lands in
-- docs/loud_error_doctrine.md alongside this PR.
--
-- Writer: UniverseService.get_scan_candidates (one row per call).
-- Verified-write per H9 doctrine: post-insert anchor probe in the
-- writer; alert (`universe_selection_log_write_failed`, warning)
-- on insert failure. Observability is the whole point — the writer
-- itself must not be silent-failure-prone.
--
-- Forward-only. Historical selection decisions before 2026-05-20
-- are unknowable from this surface (the data was never captured).
--
-- Schema decisions:
-- - selected_symbols + dropped_symbols are JSONB arrays of strings.
--   Both are captured so consumers can audit exclusion as well as
--   inclusion (the universe-cap defect was an exclusion-side
--   silent decision; capturing inclusion alone would have missed it).
-- - score_threshold = lowest liquidity_score in selected set
--   (just-included). score_at_cutoff = highest liquidity_score in
--   dropped set (just-excluded). When the two are equal, ties
--   exist at the cutoff and the alphabetical sort key (symbol ASC)
--   resolves them.
-- - job_run_id NULLABLE: scanner already wires a job_run_id through
--   RejectionStats; iv_daily_refresh handler has its own job context.
--   Capture is best-effort.
-- - metadata JSONB carries caller identity + free-form context.
-- - No upsert: each call produces a row.

CREATE TABLE IF NOT EXISTS public.universe_selection_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_run_id UUID,
  selected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  total_active INTEGER NOT NULL,
  limit_applied INTEGER NOT NULL,
  selected_count INTEGER NOT NULL,
  dropped_count INTEGER NOT NULL,
  selected_symbols JSONB NOT NULL,
  dropped_symbols JSONB NOT NULL,
  score_threshold NUMERIC,
  score_at_cutoff NUMERIC,
  metadata JSONB,
  CONSTRAINT universe_selection_log_counts_nonneg
    CHECK (total_active >= 0 AND selected_count >= 0 AND dropped_count >= 0),
  CONSTRAINT universe_selection_log_counts_consistent
    CHECK (selected_count + dropped_count <= total_active)
);

CREATE INDEX IF NOT EXISTS idx_universe_selection_log_job_run
  ON public.universe_selection_log (job_run_id);

CREATE INDEX IF NOT EXISTS idx_universe_selection_log_selected_at
  ON public.universe_selection_log (selected_at DESC);

COMMENT ON TABLE public.universe_selection_log IS
  'Per-call audit of UniverseService.get_scan_candidates. Captures '
  'the selection decision (what was included AND what was excluded '
  'by the limit) so silent universe truncation is queryable. '
  'Forward-only as of 2026-05-20. Closes the H9-generalization '
  'observability gap discovered in the 2026-05-19 funnel diagnostic. '
  'See docs/loud_error_doctrine.md H9 silent-decision generalization.';
