"""Real-PostgreSQL harness for the fleet_shadow lifecycle RPCs (C2).

Applies the bootstrap base tables, the C1 decision foundation migration, then the
C2 lifecycle migration under test, and PROVES against a live server: the open RPC
rejects every call while the fleet is inactive (cash byte-identical), the
defined-risk collateral reservation, the exact multi-leg terminal payoff at
expiry (win + max-loss), idempotency, and the append-only / pre-expiry guards.

CI-safety WITHOUT a skip/xfail: when no Postgres is reachable, the real-pg module
is removed from collection via ``collect_ignore`` (the uncollectable-file
convention). The always-green CI signal lives in the unit + migration-contract
suites.

To RUN locally:

    docker run -d --name pg -e POSTGRES_PASSWORD=pw -e POSTGRES_USER=pg \
        -e POSTGRES_DB=testdb -p 55432:5432 postgres:17-alpine
    WT17_PG_PORT=55432 py -3.11 -m pytest packages/quantum/tests/pg/fleet_lifecycle
"""

import os
import socket
from pathlib import Path

import pytest

_DSN = dict(
    host=os.environ.get("WT17_PG_HOST", "127.0.0.1"),
    port=int(os.environ.get("WT17_PG_PORT", "55432")),
    user=os.environ.get("WT17_PG_USER", "pg"),
    password=os.environ.get("WT17_PG_PASSWORD", "pw"),
    database=os.environ.get("WT17_PG_DB", "testdb"),
)

_HERE = Path(__file__).resolve().parent
_BOOTSTRAP_SQL = _HERE / "schema_bootstrap.sql"
_MIG_DIR = _HERE.parents[4] / "supabase" / "migrations"
_MIGRATIONS = [
    _MIG_DIR / "20260723160000_fleet_policy_decision_foundation.sql",   # C1
    _MIG_DIR / "20260723170000_fleet_shadow_internal_lifecycle.sql",    # C2
]


def _pg_reachable() -> bool:
    try:
        import pg8000.dbapi  # noqa: F401
    except Exception:
        return False
    try:
        s = socket.create_connection((_DSN["host"], _DSN["port"]), timeout=1.5)
        s.close()
        return True
    except Exception:
        return False


if not _pg_reachable():
    collect_ignore = ["test_fleet_shadow_lifecycle_pg.py"]


def _connect():
    import pg8000.dbapi as db

    conn = db.connect(**_DSN)
    conn.autocommit = True
    return conn


@pytest.fixture(scope="session")
def fleet_lifecycle_pg_schema():
    conn = _connect()
    cur = conn.cursor()
    cur.execute(_BOOTSTRAP_SQL.read_text(encoding="utf-8"))
    for mig in _MIGRATIONS:
        cur.execute(mig.read_text(encoding="utf-8"))
    cur.close()
    conn.close()
    yield


@pytest.fixture()
def conn(fleet_lifecycle_pg_schema):
    c = _connect()
    cur = c.cursor()
    cur.execute(
        "TRUNCATE fleet_shadow_cash_events, fleet_shadow_outcomes, "
        "fleet_shadow_positions, fleet_shadow_orders, fleet_policy_decisions, "
        "fleet_policy_decision_runs, shadow_micro_accounts, shadow_fleets, "
        "paper_portfolios, policy_registrations RESTART IDENTITY CASCADE"
    )
    cur.close()
    yield c
    c.close()
