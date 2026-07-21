from pathlib import Path


MIGRATION = Path(
    "supabase/migrations/20260721190000_single_leg_shadow_experiment_foundation.sql"
)


def test_single_leg_shadow_foundation_is_isolated_and_fail_closed():
    sql = MIGRATION.read_text(encoding="utf-8")
    for table in (
        "single_leg_experiment_epochs",
        "single_leg_experiment_bindings",
        "single_leg_shadow_runs",
        "single_leg_shadow_attempts",
        "single_leg_shadow_lifecycle_events",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in sql

    assert "CHECK (routing_mode = 'shadow_only')" in sql
    assert "CHECK (execution_mode = 'internal_paper')" in sql
    assert "CHECK (max_contracts = 1)" in sql
    assert "CHECK (live_submit_allowed = false)" in sql
    assert "BEFORE UPDATE OR DELETE ON single_leg_shadow_attempts" in sql
    assert "BEFORE UPDATE OR DELETE ON single_leg_shadow_lifecycle_events" in sql
    assert "GRANT SELECT, INSERT ON single_leg_shadow_attempts TO service_role" in sql
    assert "GRANT SELECT, INSERT ON single_leg_shadow_lifecycle_events TO service_role" in sql
    assert "trade_suggestions" not in sql
    assert "shadow_fleets" not in sql
