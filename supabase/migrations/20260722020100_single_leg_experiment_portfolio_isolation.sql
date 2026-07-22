-- Single-leg experiment portfolio custody hardening.
--
-- The experiment intentionally reuses paper_portfolios for isolated cash custody,
-- but every order/position/outcome row lives in dedicated single_leg_* tables.
-- Therefore a portfolio bound to single_leg_experiment_bindings must NEVER accept
-- a normal paper_orders / paper_positions / paper_ledger row.  Applying this
-- migration creates guards only: no policy, portfolio, binding, order, position,
-- cash event, outcome, or experiment state is created or changed.

BEGIN;

CREATE OR REPLACE FUNCTION single_leg_experiment_portfolio_is_bound_v1(
    p_portfolio_id uuid
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT EXISTS (
        SELECT 1
          FROM single_leg_experiment_bindings b
         WHERE b.portfolio_id = p_portfolio_id
    )
$$;

REVOKE ALL ON FUNCTION single_leg_experiment_portfolio_is_bound_v1(uuid)
    FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION single_leg_experiment_portfolio_is_bound_v1(uuid)
    TO authenticated, service_role;

CREATE OR REPLACE FUNCTION single_leg_reject_normal_surface_on_bound_portfolio_v1()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_portfolio_id uuid;
BEGIN
    v_portfolio_id := CASE
        WHEN TG_OP = 'DELETE' THEN OLD.portfolio_id
        ELSE NEW.portfolio_id
    END;

    IF single_leg_experiment_portfolio_is_bound_v1(v_portfolio_id) THEN
        RAISE EXCEPTION
            'single-leg experiment portfolio % is isolated from normal % rows',
            v_portfolio_id, TG_TABLE_NAME
            USING ERRCODE = '23001';
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION single_leg_reject_normal_surface_on_bound_portfolio_v1()
    FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS trg_single_leg_isolate_normal_paper_orders
    ON paper_orders;
CREATE TRIGGER trg_single_leg_isolate_normal_paper_orders
    BEFORE INSERT OR UPDATE OR DELETE ON paper_orders
    FOR EACH ROW
    EXECUTE FUNCTION single_leg_reject_normal_surface_on_bound_portfolio_v1();

DROP TRIGGER IF EXISTS trg_single_leg_isolate_normal_paper_positions
    ON paper_positions;
CREATE TRIGGER trg_single_leg_isolate_normal_paper_positions
    BEFORE INSERT OR UPDATE OR DELETE ON paper_positions
    FOR EACH ROW
    EXECUTE FUNCTION single_leg_reject_normal_surface_on_bound_portfolio_v1();

DROP TRIGGER IF EXISTS trg_single_leg_isolate_normal_paper_ledger
    ON paper_ledger;
CREATE TRIGGER trg_single_leg_isolate_normal_paper_ledger
    BEFORE INSERT OR UPDATE OR DELETE ON paper_ledger
    FOR EACH ROW
    EXECUTE FUNCTION single_leg_reject_normal_surface_on_bound_portfolio_v1();

-- Authenticated users already have an owner-update policy on paper_portfolios.
-- Make that policy AND with this restrictive policy, so a bound experiment
-- portfolio cannot be edited through the ordinary user/API surface.  The
-- service_role lifecycle RPCs bypass RLS and remain the only runtime cash owner.
DROP POLICY IF EXISTS "Bound single-leg portfolios are service-only"
    ON paper_portfolios;
CREATE POLICY "Bound single-leg portfolios are service-only"
    ON paper_portfolios
    AS RESTRICTIVE
    FOR UPDATE
    TO authenticated
    USING (NOT single_leg_experiment_portfolio_is_bound_v1(id))
    WITH CHECK (NOT single_leg_experiment_portfolio_is_bound_v1(id));

CREATE OR REPLACE FUNCTION single_leg_experiment_binding_custody_guard_v1()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_portfolio paper_portfolios%ROWTYPE;
    v_epoch_state text;
    v_normal_rows bigint;
    v_require_initial_balance boolean := false;
BEGIN
    SELECT *
      INTO v_portfolio
      FROM paper_portfolios
     WHERE id = NEW.portfolio_id
     FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'single-leg binding portfolio % is missing', NEW.portfolio_id
            USING ERRCODE = '23503';
    END IF;

    IF v_portfolio.user_id <> NEW.user_id
       OR v_portfolio.routing_mode <> 'shadow_only'
       OR NEW.routing_mode <> 'shadow_only'
       OR NEW.execution_mode <> 'internal_paper' THEN
        RAISE EXCEPTION
            'single-leg binding/portfolio custody mismatch for %',
            NEW.policy_registration_id
            USING ERRCODE = '23001';
    END IF;

    IF NEW.epoch_name = 'single_leg_experiment_v1'
       AND NEW.role <> 'experimental' THEN
        RAISE EXCEPTION
            'single_leg_experiment_v1 binds experimental policies only'
            USING ERRCODE = '23001';
    END IF;

    SELECT
        (SELECT count(*) FROM paper_orders o
          WHERE o.portfolio_id = NEW.portfolio_id)
      + (SELECT count(*) FROM paper_positions p
          WHERE p.portfolio_id = NEW.portfolio_id)
      + (SELECT count(*) FROM paper_ledger l
          WHERE l.portfolio_id = NEW.portfolio_id)
      INTO v_normal_rows;

    IF v_normal_rows <> 0 THEN
        RAISE EXCEPTION
            'single-leg experiment portfolio % has % normal paper row(s)',
            NEW.portfolio_id, v_normal_rows
            USING ERRCODE = '23001';
    END IF;

    SELECT state
      INTO v_epoch_state
      FROM single_leg_experiment_epochs
     WHERE epoch_name = NEW.epoch_name;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'single-leg epoch % is missing', NEW.epoch_name
            USING ERRCODE = '23503';
    END IF;

    -- Initial disabled setup and the first disabled->enabled transition are
    -- fixed to exactly $2,000 per experimental arm. A paused experiment may
    -- later resume with its genuine accrued cash, so paused->enabled is not
    -- reset or compared to the original balance.
    IF TG_OP = 'INSERT' THEN
        v_require_initial_balance := true;
    ELSIF TG_OP = 'UPDATE'
          AND NEW.enabled
          AND NOT OLD.enabled
          AND v_epoch_state = 'disabled' THEN
        v_require_initial_balance := true;
    END IF;

    IF NEW.epoch_name = 'single_leg_experiment_v1'
       AND v_require_initial_balance
       AND (
           v_portfolio.cash_balance IS DISTINCT FROM 2000::numeric
           OR v_portfolio.net_liq IS DISTINCT FROM 2000::numeric
       ) THEN
        RAISE EXCEPTION
            'single-leg v1 initial custody must be cash_balance=net_liq=2000 for portfolio %',
            NEW.portfolio_id
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION single_leg_experiment_binding_custody_guard_v1()
    FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS trg_single_leg_experiment_binding_custody
    ON single_leg_experiment_bindings;
CREATE TRIGGER trg_single_leg_experiment_binding_custody
    BEFORE INSERT OR UPDATE ON single_leg_experiment_bindings
    FOR EACH ROW
    EXECUTE FUNCTION single_leg_experiment_binding_custody_guard_v1();

-- Refuse to install the guard over already-contaminated custody. This block is
-- read-only on success and rolls the migration back on any mismatch.
DO $$
DECLARE
    v_bad bigint;
BEGIN
    SELECT count(*)
      INTO v_bad
      FROM single_leg_experiment_bindings b
      JOIN paper_portfolios pp ON pp.id = b.portfolio_id
     WHERE b.epoch_name = 'single_leg_experiment_v1'
       AND (
           b.role <> 'experimental'
           OR b.routing_mode <> 'shadow_only'
           OR b.execution_mode <> 'internal_paper'
           OR pp.user_id <> b.user_id
           OR pp.routing_mode <> 'shadow_only'
           OR EXISTS (
               SELECT 1 FROM paper_orders o
                WHERE o.portfolio_id = b.portfolio_id
           )
           OR EXISTS (
               SELECT 1 FROM paper_positions p
                WHERE p.portfolio_id = b.portfolio_id
           )
           OR EXISTS (
               SELECT 1 FROM paper_ledger l
                WHERE l.portfolio_id = b.portfolio_id
           )
       );

    IF v_bad <> 0 THEN
        RAISE EXCEPTION
            'single-leg portfolio isolation preflight failed for % binding(s)',
            v_bad
            USING ERRCODE = '23001';
    END IF;

    SELECT count(*)
      INTO v_bad
      FROM single_leg_experiment_bindings b
      JOIN single_leg_experiment_epochs e
        ON e.epoch_name = b.epoch_name
      JOIN paper_portfolios pp ON pp.id = b.portfolio_id
     WHERE b.epoch_name = 'single_leg_experiment_v1'
       AND e.state = 'disabled'
       AND (
           pp.cash_balance IS DISTINCT FROM 2000::numeric
           OR pp.net_liq IS DISTINCT FROM 2000::numeric
       );

    IF v_bad <> 0 THEN
        RAISE EXCEPTION
            'disabled single-leg v1 custody is not fixed at $2,000 for % binding(s)',
            v_bad
            USING ERRCODE = '23514';
    END IF;
END;
$$;

COMMENT ON FUNCTION single_leg_experiment_portfolio_is_bound_v1(uuid) IS
    'Security-definer membership check used by RLS/triggers to isolate single-leg-bound portfolios from normal paper surfaces.';
COMMENT ON FUNCTION single_leg_reject_normal_surface_on_bound_portfolio_v1() IS
    'Rejects normal paper_orders, paper_positions, and paper_ledger mutations for any single-leg experiment-bound portfolio.';
COMMENT ON FUNCTION single_leg_experiment_binding_custody_guard_v1() IS
    'Validates shadow-only internal-paper custody, zero normal rows, and the fixed $2,000 initial v1 balance at binding/first enable.';

COMMIT;
NOTIFY pgrst, 'reload schema';
