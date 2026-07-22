from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260722020000_single_leg_experiment_control_rpcs.sql"
)
SEED = (
    ROOT
    / "supabase"
    / "seed-transactions"
    / "policy_registrations_single_leg_experiment.sql"
)

EXPECTED = {
    "sl_exp_throughput_v1": "71e854a6e9f098d561748b49161c5997459b4f2a7a19e27eebcb741c1987db5e",
    "sl_ctrl_throughput_v1": "441ace2f5dc5b7842f6ae41db30db3dcd32ffbb1afa5585794659b04421fb310",
    "sl_exp_conviction_v1": "59e02e8f09b3030f7fa5f3cd6f281ee42e80100e73f2a6e8fdcfe1e56374cf09",
    "sl_ctrl_conviction_v1": "5f74bffe2d819d850f9c74be992b82f353a0ff15d5d2912abd9fb96502fc7de0",
}


def _sql():
    return MIGRATION.read_text(encoding="utf-8")


def test_control_migration_sorts_after_lifecycle_and_seed_exists():
    assert MIGRATION.exists()
    assert SEED.exists()
    lifecycle = ROOT / "supabase" / "migrations" / (
        "20260722010100_single_leg_shadow_open_rpc_concurrency_hardening.sql"
    )
    assert lifecycle.exists()
    assert lifecycle.name < MIGRATION.name


def test_expected_manifest_hashes_are_pinned_server_side():
    sql = _sql()
    seed = SEED.read_text(encoding="utf-8")
    for policy_id, config_hash in EXPECTED.items():
        assert policy_id in sql
        assert config_hash in sql
        assert policy_id in seed
    assert "single_leg_experiment_expected_policies_v1" in sql


def test_migration_defines_separate_setup_approval_enable_pause_tokens():
    sql = _sql().lower()
    for function in (
        "rpc_setup_single_leg_experiment_v1",
        "rpc_approve_single_leg_experiment_v1",
        "rpc_enable_single_leg_experiment_v1",
        "rpc_pause_single_leg_experiment_v1",
        "single_leg_experiment_current_fingerprint_v1",
    ):
        assert f"function {function}" in sql
    setup_start = sql.index("function rpc_setup_single_leg_experiment_v1")
    approval_start = sql.index("function rpc_approve_single_leg_experiment_v1")
    enable_start = sql.index("function rpc_enable_single_leg_experiment_v1")
    pause_start = sql.index("function rpc_pause_single_leg_experiment_v1")
    assert setup_start < approval_start < enable_start < pause_start


def test_setup_is_disabled_two_portfolio_shadow_only_and_idempotent():
    sql = _sql().lower()
    setup = sql[
        sql.index("function rpc_setup_single_leg_experiment_v1") :
        sql.index("function rpc_approve_single_leg_experiment_v1")
    ]
    assert "p_starting_capital is distinct from 2000" in setup
    assert "'disabled'" in setup
    assert "'shadow_only'" in setup
    assert "'internal_paper'" in setup
    assert "live_submit_allowed" in setup
    assert "sl_exp_throughput_v1" in setup
    assert "sl_exp_conviction_v1" in setup
    assert "sl_ctrl_throughput_v1" not in setup.split("insert into single_leg_experiment_bindings")[-1]
    assert "on conflict (epoch_name) do nothing" in setup
    assert "expected 2 bindings" in setup
    assert "enabled_bindings', 0" in setup


def test_approval_never_enables_and_enable_requires_exact_approved_set():
    sql = _sql().lower()
    approval = sql[
        sql.index("function rpc_approve_single_leg_experiment_v1") :
        sql.index("function rpc_enable_single_leg_experiment_v1")
    ]
    enable = sql[
        sql.index("function rpc_enable_single_leg_experiment_v1") :
        sql.index("function rpc_pause_single_leg_experiment_v1")
    ]
    assert "approval_status = 'approved'" in approval
    assert "state = 'disabled'" in approval
    assert "update single_leg_experiment_epochs" not in approval
    assert "enabled = true" not in approval

    assert "v_approved <> 4" in enable
    assert "v_bindings <> 2" in enable
    assert "set enabled = true" in enable
    assert "set state = 'enabled'" in enable
    assert "routing_mode','shadow_only'" in enable
    assert "execution_mode','internal_paper'" in enable
    assert "live_submit_allowed',false" in enable


def test_pause_is_persisted_kill_switch_without_deleting_history():
    sql = _sql().lower()
    pause = sql[sql.index("function rpc_pause_single_leg_experiment_v1") :]
    assert "set enabled = false" in pause
    assert "set state = 'paused'" in pause
    assert "delete from" not in pause
    assert "truncate" not in pause


def test_control_migration_itself_writes_no_business_rows_or_flags():
    sql = _sql().lower()
    # DML appears only inside function bodies and therefore executes solely when
    # an explicitly authorized RPC is called after migration application.
    prefix = sql[: sql.index("create or replace function rpc_setup_single_leg_experiment_v1")]
    assert "insert into policy_registrations" not in prefix
    assert "insert into paper_portfolios" not in prefix
    assert "insert into single_leg_experiment_bindings" not in prefix
    assert "update single_leg_experiment_epochs" not in prefix
    assert "railway" not in sql
    assert "broker" not in sql
    assert "shadow_fleets" not in sql


def test_all_control_functions_are_service_role_only():
    sql = _sql().lower()
    for function in (
        "rpc_setup_single_leg_experiment_v1(uuid,numeric,text)",
        "rpc_approve_single_leg_experiment_v1(uuid,text,text)",
        "rpc_enable_single_leg_experiment_v1(uuid,text,text)",
        "rpc_pause_single_leg_experiment_v1(uuid,text)",
    ):
        assert f"revoke all on function {function} from public, anon, authenticated" in sql
        assert f"grant execute on function {function} to service_role" in sql
