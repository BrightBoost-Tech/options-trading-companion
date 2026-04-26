-- #62a-D4-PR1 — Add routing_mode column to paper_portfolios.
--
-- Per #62a audit (2026-04-26), the cohort fan-out was found to lack
-- portfolio-level routing safety: EXECUTION_MODE is global, so
-- restoring shadow-cohort data flow (D4-PR3 fixes the symbol drift)
-- without explicit routing enforcement could send conservative /
-- neutral cohort orders to the live broker — violating the design
-- intent that shadow cohorts are paper-only learning channels.
--
-- This migration is data-only. The dispatch enforcement that READS
-- routing_mode lands in PR2; the symbol drop that produces shadow
-- clones lands in PR3. PR1 is sequenced first so the data shape is
-- in place before any consumer.
--
-- Design principle: each portfolio's intent (live-capable vs
-- shadow-only) becomes explicit data, not implicit code-path
-- knowledge. Safe by default — new portfolios default to
-- 'live_eligible'; shadow status must be intentionally set.

BEGIN;

-- 1. Add column with safe-by-default value and value-restricting CHECK.
ALTER TABLE paper_portfolios
  ADD COLUMN routing_mode text NOT NULL DEFAULT 'live_eligible'
  CHECK (routing_mode IN ('live_eligible', 'shadow_only'));

-- 2. Backfill cohort portfolios. Conservative + Neutral are designed
--    as shadow channels (per operator clarification 2026-04-26: the
--    aggressive cohort is the live-capital champion; conservative and
--    neutral produce shadow observations for learning).
--
--    Rows are matched by joining policy_lab_cohorts so this is robust
--    to portfolio_id drift between environments.
UPDATE paper_portfolios pp
   SET routing_mode = 'shadow_only'
  FROM policy_lab_cohorts c
 WHERE c.portfolio_id = pp.id
   AND c.cohort_name IN ('conservative', 'neutral');

-- 3. Verification: every portfolio must have a non-null routing_mode
--    and a value in the allowed set. Fails the migration if anything
--    leaked through.
DO $$
DECLARE _bad_count int;
BEGIN
  SELECT COUNT(*) INTO _bad_count
    FROM paper_portfolios
   WHERE routing_mode IS NULL
      OR routing_mode NOT IN ('live_eligible', 'shadow_only');
  IF _bad_count > 0 THEN
    RAISE EXCEPTION 'routing_mode invariant violated: % rows', _bad_count;
  END IF;
END $$;

COMMIT;

NOTIFY pgrst, 'reload schema';
