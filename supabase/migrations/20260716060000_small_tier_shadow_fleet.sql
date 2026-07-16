-- Prospective small_tier_v1 shadow fleet.
--
-- SCHEMA ONLY. This migration creates no fleet, portfolio, cohort, policy
-- registration, order, position, or decision row. Applying it cannot activate
-- the fleet. A later operator-owned activation transaction must first prove the
-- legacy_100k positions and working orders are terminal.
--
-- Capital isolation contract:
--   50 slots x $2,000 = $100,000 administrative total.
--   The aggregate is generated/reporting-only and is never a sizing balance.

CREATE TABLE IF NOT EXISTS shadow_fleets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  epoch_name text NOT NULL DEFAULT 'small_tier_v1',
  legacy_epoch_name text NOT NULL DEFAULT 'legacy_100k',
  capital_basis text NOT NULL DEFAULT 'fixed_small_tier',
  micro_account_count integer NOT NULL DEFAULT 50,
  capital_per_account numeric NOT NULL DEFAULT 2000,
  aggregate_administrative_capital numeric
    GENERATED ALWAYS AS (micro_account_count * capital_per_account) STORED,
  shared_capital_enabled boolean NOT NULL DEFAULT false,
  decision_event_basis text NOT NULL DEFAULT 'source_suggestion_id',
  status text NOT NULL DEFAULT 'pending_legacy_terminal',
  legacy_terminal_verified_at timestamptz,
  effective_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  retired_at timestamptz,
  UNIQUE (user_id, epoch_name),
  CHECK (epoch_name = 'small_tier_v1'),
  CHECK (legacy_epoch_name = 'legacy_100k'),
  CHECK (capital_basis = 'fixed_small_tier'),
  CHECK (micro_account_count = 50),
  CHECK (capital_per_account = 2000),
  CHECK (shared_capital_enabled = false),
  CHECK (decision_event_basis = 'source_suggestion_id'),
  CHECK (status IN ('pending_legacy_terminal', 'ready', 'active', 'retired')),
  CHECK (
    status <> 'active'
    OR (
      legacy_terminal_verified_at IS NOT NULL
      AND effective_at IS NOT NULL
    )
  )
);

CREATE TABLE IF NOT EXISTS shadow_micro_accounts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  fleet_id uuid NOT NULL REFERENCES shadow_fleets(id) ON DELETE CASCADE,
  slot_number integer NOT NULL,
  portfolio_id uuid UNIQUE REFERENCES paper_portfolios(id),
  policy_registration_id text,
  state text NOT NULL DEFAULT 'inactive',
  initial_net_liq numeric NOT NULL DEFAULT 2000,
  initial_cash numeric NOT NULL DEFAULT 2000,
  comparison_eligible boolean NOT NULL DEFAULT true,
  promotion_eligible boolean NOT NULL DEFAULT false,
  evidence_unit text NOT NULL DEFAULT 'decision_event_id',
  activated_at timestamptz,
  retired_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (fleet_id, slot_number),
  CHECK (slot_number BETWEEN 1 AND 50),
  CHECK (initial_net_liq = 2000),
  CHECK (initial_cash = 2000),
  CHECK (state IN ('inactive', 'active', 'retired')),
  CHECK (evidence_unit = 'decision_event_id'),
  CHECK (
    state <> 'active'
    OR (
      portfolio_id IS NOT NULL
      AND policy_registration_id IS NOT NULL
      AND btrim(policy_registration_id) <> ''
      AND activated_at IS NOT NULL
    )
  )
);

CREATE UNIQUE INDEX IF NOT EXISTS
  idx_shadow_micro_accounts_fleet_policy_registration
ON shadow_micro_accounts(fleet_id, policy_registration_id)
WHERE policy_registration_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_shadow_micro_accounts_fleet_state
  ON shadow_micro_accounts(fleet_id, state, slot_number);

ALTER TABLE policy_lab_cohorts
  ADD COLUMN IF NOT EXISTS shadow_micro_account_id uuid
    REFERENCES shadow_micro_accounts(id);

CREATE UNIQUE INDEX IF NOT EXISTS
  idx_policy_lab_cohorts_shadow_micro_account
ON policy_lab_cohorts(shadow_micro_account_id)
WHERE shadow_micro_account_id IS NOT NULL;

-- One immutable market-decision identity shared by every account evaluation.
-- Existing policy_decisions already use the SOURCE suggestion id as
-- suggestion_id, so the prospective backfill is truthful rather than inferred.
ALTER TABLE policy_decisions
  ADD COLUMN IF NOT EXISTS decision_event_id uuid;

UPDATE policy_decisions
SET decision_event_id = suggestion_id
WHERE decision_event_id IS NULL;

ALTER TABLE policy_decisions
  ALTER COLUMN decision_event_id SET NOT NULL;

ALTER TABLE policy_decisions
  DROP CONSTRAINT IF EXISTS policy_decisions_decision_event_matches_source;

ALTER TABLE policy_decisions
  ADD CONSTRAINT policy_decisions_decision_event_matches_source
  CHECK (decision_event_id = suggestion_id);

CREATE INDEX IF NOT EXISTS idx_policy_decisions_decision_event
  ON policy_decisions(decision_event_id);

ALTER TABLE policy_decisions
  ADD COLUMN IF NOT EXISTS shadow_micro_account_id uuid
    REFERENCES shadow_micro_accounts(id);

CREATE INDEX IF NOT EXISTS idx_policy_decisions_micro_event
  ON policy_decisions(shadow_micro_account_id, decision_event_id)
  WHERE shadow_micro_account_id IS NOT NULL;

CREATE OR REPLACE FUNCTION set_policy_decision_event_id()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF TG_OP = 'UPDATE'
     AND NEW.decision_event_id IS DISTINCT FROM OLD.decision_event_id THEN
    RAISE EXCEPTION 'decision_event_id is immutable';
  END IF;

  IF NEW.decision_event_id IS NULL THEN
    NEW.decision_event_id := NEW.suggestion_id;
  END IF;

  IF NEW.decision_event_id IS DISTINCT FROM NEW.suggestion_id THEN
    RAISE EXCEPTION 'decision_event_id must equal source suggestion_id';
  END IF;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS policy_decision_event_identity
  ON policy_decisions;

CREATE TRIGGER policy_decision_event_identity
BEFORE INSERT OR UPDATE OF suggestion_id, decision_event_id
ON policy_decisions
FOR EACH ROW
EXECUTE FUNCTION set_policy_decision_event_id();

ALTER TABLE shadow_fleets ENABLE ROW LEVEL SECURITY;
ALTER TABLE shadow_micro_accounts ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access shadow_fleets"
  ON shadow_fleets FOR ALL
  USING (auth.role() = 'service_role');

CREATE POLICY "Users can view own shadow_fleets"
  ON shadow_fleets FOR SELECT
  USING (auth.uid() = user_id);

CREATE POLICY "Service role full access shadow_micro_accounts"
  ON shadow_micro_accounts FOR ALL
  USING (auth.role() = 'service_role');

CREATE POLICY "Users can view own shadow_micro_accounts"
  ON shadow_micro_accounts FOR SELECT
  USING (
    EXISTS (
      SELECT 1
      FROM shadow_fleets fleet
      WHERE fleet.id = shadow_micro_accounts.fleet_id
        AND fleet.user_id = auth.uid()
    )
  );

COMMENT ON TABLE shadow_fleets IS
  'Prospective 50x$2k shadow fleet; aggregate capital is administrative only.';
COMMENT ON TABLE shadow_micro_accounts IS
  'Isolated $2k slots; only pre-registered policies may be activated.';
COMMENT ON COLUMN policy_decisions.decision_event_id IS
  'Immutable source suggestion UUID; COUNT(DISTINCT ...) is the evidence n.';
