-- Paper-shadow executor (Phase 1a) — add 'paper_shadow' to the
-- paper_portfolios.routing_mode CHECK constraint.
--
-- 'paper_shadow' tags portfolios owned by the paper-shadow EXECUTOR
-- (Phase 1b), which trades the dedicated Alpaca PAPER account
-- (PA3I8CYLXBOS) for OBSERVATION (D6 exit-rule comparison + D2 momentum
-- calibration). The 3 live management jobs (intraday_risk_monitor,
-- paper_exit_evaluator, alpaca_order_sync) EXCLUDE these portfolios so the
-- live pipeline never manages them — extending the existing 'shadow_only'
-- exclusion precedent (migration 20260426000000), not a parallel mechanism.
--
-- Data-definition only. No row is set to 'paper_shadow' here — only the
-- future executor (Phase 1b) creates such a portfolio, and only on the paper
-- account. There is NO code path (and this migration adds none) that sets
-- 'paper_shadow' on a live (211900084) portfolio. Live portfolios remain
-- 'live_eligible'; a live position can therefore never acquire this tag.
--
-- Apply per docs/migration_procedure.md (migrations do not auto-apply on
-- merge). Safe to deploy before or after the Phase-1a code: the live-job
-- exclusion filters match nothing until a 'paper_shadow' row exists, and no
-- such row exists until Phase 1b.

ALTER TABLE paper_portfolios
  DROP CONSTRAINT IF EXISTS paper_portfolios_routing_mode_check;

ALTER TABLE paper_portfolios
  ADD CONSTRAINT paper_portfolios_routing_mode_check
  CHECK (routing_mode IN ('live_eligible', 'shadow_only', 'paper_shadow'));
