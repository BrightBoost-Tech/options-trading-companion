-- #109 PR-2 — strategy_lifecycle_states table + seed.
--
-- Foundation for multi-strategy lifecycle gating per
-- docs/designs/multi_strategy_phase1.md Phase 2 PR-2.
--
-- State machine: designed → experimental → live_full → deprecated
--
-- - DESIGNED: code exists but never enabled in production scanner
-- - EXPERIMENTAL: live in scanner, sized down (1 contract max via #110/PR-3)
-- - LIVE_FULL: graduated, normal sizing applies
-- - DEPRECATED: retired (manual SQL only; no automated demotion in
--   PR-2 scope — operator decides)
--
-- Auto-graduation EXPERIMENTAL → LIVE_FULL is performed by
-- evaluate_strategy_lifecycle() (in progression_service.py) called
-- from daily_progression_eval. Gates: cumulative realized_pl > 0
-- AND trade_count >= MIN_TRADES_FOR_STRATEGY_GRADUATION (3) per
-- get_strategy_eligibility from #108 PR-1.
--
-- This PR seeds the 5 currently-shipped strategies as live_full so
-- behavior is unchanged at merge. Future strategies
-- (BULL_PUT_SPREAD_0DTE, CASH_SECURED_PUT) get rows when their
-- implementation code ships, not pre-emptively.

BEGIN;

CREATE TABLE IF NOT EXISTS strategy_lifecycle_states (
  strategy_name           TEXT PRIMARY KEY,
  current_state           TEXT NOT NULL
    CHECK (current_state IN ('designed', 'experimental', 'live_full', 'deprecated')),
  transitioned_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  transition_reason       JSONB,
  closed_trade_count      INTEGER,
  cumulative_realized_pl  NUMERIC,
  updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE strategy_lifecycle_states IS
  'Lifecycle states for trading strategies. Future strategies '
  '(BULL_PUT_SPREAD_0DTE, CASH_SECURED_PUT) get rows when their '
  'implementation code ships, not pre-emptively. Auto-graduation '
  'EXPERIMENTAL -> LIVE_FULL via evaluate_strategy_lifecycle() in '
  'progression_service.py (#109 PR-2).';

-- Reuse the shared updated_at trigger function created in
-- 20250107000000_create_underlying_iv_points.sql.
CREATE TRIGGER set_updated_at_strategy_lifecycle_states
    BEFORE UPDATE ON public.strategy_lifecycle_states
    FOR EACH ROW
    EXECUTE PROCEDURE public.handle_updated_at();

-- Seed: 5 currently-shipped strategies as live_full.
-- ON CONFLICT DO NOTHING preserves any state changes that may have
-- happened between an earlier apply and a re-run (idempotent
-- per the migration apply procedure in CLAUDE.md).
INSERT INTO strategy_lifecycle_states (strategy_name, current_state, transition_reason)
VALUES
  ('LONG_CALL_DEBIT_SPREAD',     'live_full', '{"reason": "initial_seed_existing_strategy", "shipped_at_pr": 109}'::jsonb),
  ('LONG_PUT_DEBIT_SPREAD',      'live_full', '{"reason": "initial_seed_existing_strategy", "shipped_at_pr": 109}'::jsonb),
  ('IRON_CONDOR',                'live_full', '{"reason": "initial_seed_existing_strategy", "shipped_at_pr": 109}'::jsonb),
  ('SHORT_PUT_CREDIT_SPREAD',    'live_full', '{"reason": "initial_seed_existing_strategy", "shipped_at_pr": 109}'::jsonb),
  ('SHORT_CALL_CREDIT_SPREAD',   'live_full', '{"reason": "initial_seed_existing_strategy", "shipped_at_pr": 109}'::jsonb)
ON CONFLICT (strategy_name) DO NOTHING;

-- Verification: seed must produce exactly 5 rows post-apply (whether
-- this run created them or a prior run did). Fails the migration if
-- the table is in an unexpected state.
DO $$
DECLARE _row_count int;
BEGIN
  SELECT COUNT(*) INTO _row_count
    FROM strategy_lifecycle_states
   WHERE strategy_name IN (
      'LONG_CALL_DEBIT_SPREAD', 'LONG_PUT_DEBIT_SPREAD',
      'IRON_CONDOR', 'SHORT_PUT_CREDIT_SPREAD',
      'SHORT_CALL_CREDIT_SPREAD'
   );
  IF _row_count <> 5 THEN
    RAISE EXCEPTION 'strategy_lifecycle_states seed invariant violated: % of 5 rows present', _row_count;
  END IF;
END $$;

-- RLS: strategy lifecycle is global (not per-user), so service-role
-- access only. No user policy needed.
ALTER TABLE strategy_lifecycle_states ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access" ON strategy_lifecycle_states
    FOR ALL TO service_role USING (true);

COMMIT;

NOTIFY pgrst, 'reload schema';
