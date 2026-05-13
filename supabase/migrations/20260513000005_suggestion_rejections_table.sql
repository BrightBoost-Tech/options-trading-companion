-- Tier 1C: per-suggestion rejection persistence.
--
-- Granular complement to the aggregate `rejection_counts` already
-- in `job_runs.result.cycle_results.debug.rejection_counts`. The
-- aggregate answers "how many entry_cost_too_low this week"; this
-- table answers "which specific 8 PFE rejections for entry_cost_too_low
-- in May, with what spread context."
--
-- Forward-only as of 2026-05-13. Pre-PR rejections remain in
-- job_runs.result aggregates only (no synthetic backfill — that
-- would produce false granularity).
--
-- Populated by RejectionStats.record() and .record_with_sample() in
-- packages/quantum/options_scanner.py, hooked via per-thread symbol
-- context (threading.local) so the existing 30+ call sites don't
-- each need a symbol kwarg added.
--
-- Failures are logged but not raised — this is observability, not
-- load-bearing for trade decisions. The aggregate count remains the
-- authoritative source.
--
-- Schema decisions:
-- - strategy_key NULLABLE: rejections at universe-filter stage
--   (e.g., micro_tier_underlying_too_high) happen before strategy
--   selection. RejectionStats.PRE_STRATEGY_KEY ('__pre_strategy__')
--   is what the existing aggregate uses for these; here we store NULL.
-- - spread_debug JSONB: per-reason context shapes vary; jsonb captures
--   variability without rigid columns. Same pattern as
--   trade_suggestions.sizing_metadata.
-- - job_run_id NULLABLE: scanner doesn't currently receive it as a
--   parameter; can be wired through later. Capture is best-effort.
-- - No upsert: each emission produces a row. Same symbol+reason on
--   consecutive cycles produces multiple rows (correct — operator
--   wants persistence pattern visibility).
--
-- See CLAUDE.md `### Operating mode — learning-mode at micro tier`
-- and `### Exit thresholds (defaults under empirical review)`.

CREATE TABLE IF NOT EXISTS public.suggestion_rejections (
  id BIGSERIAL PRIMARY KEY,
  symbol TEXT NOT NULL,
  strategy_key TEXT,
  reason TEXT NOT NULL,
  cycle_date DATE NOT NULL,
  job_run_id UUID,
  spread_debug JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT suggestion_rejections_reason_nonempty CHECK (reason <> '')
);

CREATE INDEX IF NOT EXISTS idx_suggestion_rejections_symbol_reason
  ON public.suggestion_rejections (symbol, reason, cycle_date DESC);

CREATE INDEX IF NOT EXISTS idx_suggestion_rejections_cycle_date
  ON public.suggestion_rejections (cycle_date DESC);

CREATE INDEX IF NOT EXISTS idx_suggestion_rejections_reason
  ON public.suggestion_rejections (reason, cycle_date DESC);

COMMENT ON TABLE public.suggestion_rejections IS
  'Per-rejection persistence for scanner candidate evaluation. '
  'Granular complement to the aggregate rejection_counts in '
  'job_runs.result. Forward-only as of 2026-05-13. One row per '
  'RejectionStats.record() emission. See packages/quantum/options_scanner.py '
  'and CLAUDE.md operational notes for context.';
