-- Cluster 3: persist the VRP inputs on trade_suggestions so the EXECUTOR
-- (paper_autopilot_service) — which re-ranks suggestions read back from the DB
-- and OVERWRITES the midday-stamped risk_adjusted_ev — can apply the VRP soft
-- down-weight at the decision that actually fires.
--
-- Without these columns the executor's compute_risk_adjusted_ev sees no
-- iv_rv_spread (internal_cand is stripped on persist) and the down-weight
-- no-ops, making any in-memory midday wiring cosmetic.
--
--   iv_rv_spread     = atm_iv - rv_20d (the VRP proxy; log-return rv after
--                      Cluster 1). Nullable: a name lacking it is a no-op by
--                      design (never penalize missing data; composes with
--                      Cluster 1's min-history exclusion).
--   premium_direction = 'debit' | 'credit'. The VRP down-weight is applied to
--                      long-debit candidates ONLY; credit/short-premium and
--                      unknown are left at multiplier 1.0.
--
-- Data-definition only; both columns are nullable with no default, so existing
-- rows and any pre-wiring writer are unaffected. The live application is gated
-- behind VRP_LIVE_ENABLED (default OFF), so populating these columns changes no
-- ranking until the flag is explicitly turned on.
--
-- Apply per docs/migration_procedure.md BEFORE merging the wiring code
-- (migration-before-merge): the scanner/midday writer adds these keys to the
-- suggestion payload, and the column must exist or the missing-column retry
-- shim (workflow_orchestrator) would silently strip it.

ALTER TABLE trade_suggestions ADD COLUMN IF NOT EXISTS iv_rv_spread numeric;
ALTER TABLE trade_suggestions ADD COLUMN IF NOT EXISTS premium_direction text;
