from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260722020100_single_leg_experiment_portfolio_isolation.sql"
)
CONTROL = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260722020000_single_leg_experiment_control_rpcs.sql"
)


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_isolation_migration_follows_control_and_creates_no_business_rows():
    assert CONTROL.exists()
    assert MIGRATION.exists()
    assert MIGRATION.name > CONTROL.name
    sql = _sql().lower()
    assert "insert into" not in sql
    assert "update paper_portfolios" not in sql
    assert "delete from" not in sql


def test_normal_paper_surfaces_are_blocked_for_bound_portfolios():
    sql = _sql()
    assert "single_leg_experiment_portfolio_is_bound_v1" in sql
    assert "single_leg_reject_normal_surface_on_bound_portfolio_v1" in sql
    for table, trigger in (
        ("paper_orders", "trg_single_leg_isolate_normal_paper_orders"),
        ("paper_positions", "trg_single_leg_isolate_normal_paper_positions"),
        ("paper_ledger", "trg_single_leg_isolate_normal_paper_ledger"),
    ):
        assert f"ON {table}" in sql
        assert trigger in sql
    assert sql.count("BEFORE INSERT OR UPDATE OR DELETE") == 3
    assert "normal paper row(s)" in sql


def test_authenticated_portfolio_updates_are_restrictively_blocked():
    sql = _sql()
    assert 'CREATE POLICY "Bound single-leg portfolios are service-only"' in sql
    assert "AS RESTRICTIVE" in sql
    assert "FOR UPDATE" in sql
    assert "TO authenticated" in sql
    assert "NOT single_leg_experiment_portfolio_is_bound_v1(id)" in sql


def test_binding_guard_pins_initial_custody_without_blocking_paused_resume():
    sql = _sql()
    assert "single_leg_experiment_binding_custody_guard_v1" in sql
    assert "trg_single_leg_experiment_binding_custody" in sql
    assert "BEFORE INSERT OR UPDATE ON single_leg_experiment_bindings" in sql
    assert "NEW.role <> 'experimental'" in sql
    assert "NEW.routing_mode <> 'shadow_only'" in sql
    assert "NEW.execution_mode <> 'internal_paper'" in sql
    assert "v_epoch_state = 'disabled'" in sql
    assert "cash_balance IS DISTINCT FROM 2000::numeric" in sql
    assert "net_liq IS DISTINCT FROM 2000::numeric" in sql
    assert "paused->enabled is not" in sql


def test_existing_custody_is_validated_before_guard_installation_commits():
    sql = _sql()
    assert "single-leg portfolio isolation preflight failed" in sql
    assert "disabled single-leg v1 custody is not fixed at $2,000" in sql
    assert "EXISTS (\n               SELECT 1 FROM paper_orders" in sql
    assert "EXISTS (\n               SELECT 1 FROM paper_positions" in sql
    assert "EXISTS (\n               SELECT 1 FROM paper_ledger" in sql
    assert "COMMIT;" in sql
    assert "NOTIFY pgrst, 'reload schema';" in sql


def test_guard_functions_are_not_directly_callable_by_untrusted_roles():
    sql = _sql()
    assert (
        "REVOKE ALL ON FUNCTION "
        "single_leg_reject_normal_surface_on_bound_portfolio_v1()\n"
        "    FROM PUBLIC, anon, authenticated;"
    ) in sql
    assert (
        "REVOKE ALL ON FUNCTION "
        "single_leg_experiment_binding_custody_guard_v1()\n"
        "    FROM PUBLIC, anon, authenticated;"
    ) in sql
    # The boolean helper must be callable by authenticated for the restrictive
    # paper_portfolios policy, but it exposes only membership, never row contents.
    assert (
        "GRANT EXECUTE ON FUNCTION "
        "single_leg_experiment_portfolio_is_bound_v1(uuid)\n"
        "    TO authenticated, service_role;"
    ) in sql
