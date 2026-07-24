"""Always-green structural contract for the fleet lifecycle migration (C2).

The transactional / economic proof lives in the gated real-pg suite
(packages/quantum/tests/pg/fleet_lifecycle/).
"""

from pathlib import Path


MIGRATION = Path(
    "supabase/migrations/20260723170000_fleet_shadow_internal_lifecycle.sql"
)


def test_fleet_lifecycle_is_isolated_shadow_only_and_atomic():
    sql = MIGRATION.read_text(encoding="utf-8")

    for table in (
        "fleet_shadow_orders",
        "fleet_shadow_positions",
        "fleet_shadow_outcomes",
        "fleet_shadow_cash_events",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in sql

    # Shadow-only / non-live invariants on every fill surface.
    assert "CHECK (routing_mode = 'shadow_only')" in sql
    assert "CHECK (execution_mode = 'internal_paper')" in sql
    assert "CHECK (live_submit_allowed = false)" in sql

    # Atomic SECURITY DEFINER RPCs, both fleet-active gated.
    assert "CREATE OR REPLACE FUNCTION rpc_open_fleet_shadow_position_v1" in sql
    assert "CREATE OR REPLACE FUNCTION rpc_close_fleet_shadow_position_v1" in sql
    assert "SECURITY DEFINER" in sql
    assert "f.status = 'active'" in sql            # open re-checks fleet active
    assert "m.state = 'active'" in sql             # open re-checks micro active
    assert "disposition = 'selected'" in sql       # candidate identity anchor
    assert "insufficient_funds" in sql             # collateral reservation guard

    # Multi-leg terminal payoff derives from STORED signed legs (never fabricated).
    assert "jsonb_array_elements(v_position.legs)" in sql
    assert "greatest(p_terminal_spot - v_strike, 0)" in sql
    assert "greatest(v_strike - p_terminal_spot, 0)" in sql

    # Append-only evidence + open->closed-only positions.
    assert "BEFORE UPDATE OR DELETE ON fleet_shadow_orders" in sql
    assert "BEFORE UPDATE OR DELETE ON fleet_shadow_outcomes" in sql
    assert "only open -> closed transition is allowed" in sql

    # Idempotency keys (both grains) + write-once cash keys.
    assert "UNIQUE (run_id, candidate_suggestion_id)" in sql
    assert "idempotency_key text NOT NULL UNIQUE" in sql

    # Execute is operator-only (service_role), never public.
    assert "GRANT EXECUTE ON FUNCTION rpc_open_fleet_shadow_position_v1" in sql
    assert "GRANT EXECUTE ON FUNCTION rpc_close_fleet_shadow_position_v1" in sql

    # Isolation: never the champion book (paper_positions / trade_suggestions).
    code = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    assert "paper_positions" not in code
    assert "trade_suggestions" not in code
    # It DOES reference paper_portfolios (the isolated shadow-only $2k portfolios).
    assert "paper_portfolios" in code
