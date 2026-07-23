"""Always-green structural contract for the fleet decision-evidence migration.

Mirrors test_single_leg_shadow_migration_contract.py: a text-based check that the
additive foundation is isolated, append-only, service-role-only, and carries the
two idempotency keys. The transactional proof lives in the gated real-pg suite
(packages/quantum/tests/pg/).
"""

from pathlib import Path


MIGRATION = Path(
    "supabase/migrations/20260723160000_fleet_policy_decision_foundation.sql"
)


def test_fleet_decision_foundation_is_isolated_and_append_only():
    sql = MIGRATION.read_text(encoding="utf-8")

    for table in ("fleet_policy_decision_runs", "fleet_policy_decisions"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in sql
        assert f'"Service role full access {table}"' in sql

    # The two doctrine idempotency keys.
    assert "UNIQUE (source_decision_id, fleet_epoch, shadow_micro_account_id)" in sql
    assert "UNIQUE (decision_event_id, fleet_epoch, shadow_micro_account_id)" in sql

    # Immutable statistical identity (= source suggestion id).
    assert "CHECK (candidate_suggestion_id = decision_event_id)" in sql

    # 6 typed dispositions decompose across the two grains.
    assert "disposition IN ('selected', 'policy_rejected', 'capital_rejected')" in sql
    for run_status in ("no_candidate", "data_unavailable", "evaluator_failed"):
        assert run_status in sql

    # Epoch pin + append-only decision evidence.
    assert "fleet_epoch = 'small_tier_v1'" in sql
    assert "BEFORE UPDATE OR DELETE ON fleet_policy_decisions" in sql
    assert "GRANT SELECT, INSERT ON fleet_policy_decisions TO service_role" in sql
    # Runs keep UPDATE (begin-run -> finish-run) but never DELETE.
    assert "GRANT SELECT, INSERT, UPDATE ON fleet_policy_decision_runs TO service_role" in sql

    # Isolation: the CODE never touches live/champion trading surfaces. The
    # rationale COMMENT names them (to explain why we do NOT reuse them), so the
    # check strips `--` comment lines first.
    code = "\n".join(
        line for line in sql.splitlines() if not line.lstrip().startswith("--")
    )
    for forbidden in ("trade_suggestions", "paper_positions", "paper_orders", "policy_lab_cohorts"):
        assert forbidden not in code, f"migration code must not reference {forbidden}"
