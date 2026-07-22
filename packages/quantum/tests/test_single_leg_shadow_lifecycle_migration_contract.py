from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260722010000_single_leg_shadow_internal_lifecycle.sql"
)


def _sql():
    return MIGRATION.read_text(encoding="utf-8")


def test_migration_exists_after_foundation():
    assert MIGRATION.exists()
    foundation = ROOT / "supabase" / "migrations" / (
        "20260721190000_single_leg_shadow_experiment_foundation.sql"
    )
    assert foundation.exists()
    assert MIGRATION.name > foundation.name


def test_dedicated_internal_tables_and_no_live_table_writes():
    sql = _sql().lower()
    for table in (
        "single_leg_shadow_orders",
        "single_leg_shadow_positions",
        "single_leg_shadow_outcomes",
        "single_leg_shadow_cash_events",
    ):
        assert f"create table if not exists {table}" in sql
    assert "insert into trade_suggestions" not in sql
    assert "insert into paper_orders" not in sql
    assert "insert into paper_positions" not in sql
    assert "insert into shadow_fleets" not in sql
    assert "broker_order" not in sql


def test_one_contract_shadow_internal_nonlive_constraints_are_repeated():
    sql = _sql().lower()
    assert sql.count("check (contracts = 1)") >= 2
    assert sql.count("check (routing_mode = 'shadow_only')") >= 2
    assert sql.count("check (execution_mode = 'internal_paper')") >= 2
    assert sql.count("check (live_submit_allowed = false)") >= 2
    assert "check (option_type in ('call', 'put'))" in sql
    assert "check (strategy_type in ('long_call', 'long_put'))" in sql


def test_open_rpc_rechecks_every_authoritative_gate():
    sql = _sql().lower()
    assert "rpc_open_single_leg_shadow_position_v1" in sql
    for token in (
        "candidate_generated evidence missing",
        "single_leg_experiment_bindings",
        "role = 'experimental'",
        "execution_mode = 'internal_paper'",
        "e.state = 'enabled'",
        "e.max_contracts = 1",
        "e.live_submit_allowed = false",
        "approval_status = 'approved'",
        "single_leg_experiment_enabled",
        "routing_mode = 'shadow_only'",
        "for update",
        "insufficient experimental portfolio cash",
    ):
        assert token in sql


def test_open_rpc_is_atomic_cash_order_position_and_evidence():
    sql = _sql().lower()
    assert "insert into single_leg_shadow_orders" in sql
    assert "insert into single_leg_shadow_positions" in sql
    assert "update paper_portfolios" in sql
    assert "insert into single_leg_shadow_cash_events" in sql
    assert "'entry_debit'" in sql
    assert "'order_created'" in sql
    assert "'filled_internal'" in sql
    assert "'position_opened'" in sql
    assert "idempotent_replay" in sql


def test_close_rpc_uses_exact_long_option_intrinsic_payoff():
    sql = _sql().lower()
    assert "rpc_close_single_leg_shadow_position_v1" in sql
    assert "greatest(p_terminal_spot - v_position.strike, 0) * 100" in sql
    assert "greatest(v_position.strike - p_terminal_spot, 0) * 100" in sql
    assert "v_pnl := v_terminal - v_position.entry_debit_total" in sql
    assert "p_close_reason <> 'expiry'" in sql
    assert "p_closed_at::date < v_position.expiry" in sql
    assert "insert into single_leg_shadow_outcomes" in sql
    assert "'expiry_settlement'" in sql
    assert "'position_closed'" in sql
    assert "'outcome_recorded'" in sql


def test_append_only_and_transition_guards_are_present():
    sql = _sql().lower()
    assert "single_leg_shadow_append_only_guard" in sql
    assert "single_leg_shadow_position_transition_guard" in sql
    assert "only open -> closed transition is allowed" in sql
    assert "closed single-leg shadow position is immutable" in sql
    assert "settlement_deferred" in sql


def test_service_role_reads_directly_but_writes_only_via_rpcs():
    sql = _sql().lower()
    for table in (
        "single_leg_shadow_orders",
        "single_leg_shadow_positions",
        "single_leg_shadow_outcomes",
        "single_leg_shadow_cash_events",
    ):
        assert f"grant select on {table} to service_role" in sql
    assert "grant execute on function rpc_open_single_leg_shadow_position_v1" in sql
    assert "grant execute on function rpc_close_single_leg_shadow_position_v1" in sql
    assert "grant insert on single_leg_shadow_orders" not in sql
    assert "grant update on single_leg_shadow_positions" not in sql


def test_migration_is_structural_only_until_runtime_rpc_calls():
    sql = _sql().lower()
    assert "insert into policy_registrations" not in sql
    assert "insert into paper_portfolios" not in sql
    assert "insert into single_leg_experiment_bindings" not in sql
    assert "update single_leg_experiment_epochs" not in sql
    assert "commit;" in sql
