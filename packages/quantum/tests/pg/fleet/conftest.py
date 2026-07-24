"""Real-PostgreSQL harness for the fleet_policy_decision foundation DDL.

Exercises the ACTUAL migration SQL against a live Postgres so the two
idempotency UNIQUE keys, the append-only decision trigger, the run identity
guard, and the disposition/identity CHECKs are PROVEN, not text-mirrored.
Requires a reachable Postgres and the pure-python ``pg8000`` driver.

CI-safety WITHOUT a skip/xfail: when no Postgres is reachable (this repo's CI
runs no pg service), the real-pg module is removed from collection via
``collect_ignore`` below — the same uncollectable-file convention as the sibling
pg suites. No ``pytest.mark.skip`` / ``xfail`` is introduced. The always-green CI
signal for the migration lives in
``test_fleet_policy_decision_migration_contract.py`` and the unit suite.

To RUN locally / in review, point it at a throwaway Postgres:

    docker run -d --name pg -e POSTGRES_PASSWORD=pw -e POSTGRES_USER=pg \
        -e POSTGRES_DB=testdb -p 55432:5432 postgres:17-alpine
    WT17_PG_PORT=55432 py -3.11 -m pytest packages/quantum/tests/pg/fleet
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
_MIG_DIR = (
    _HERE.parents[4]  # fleet -> pg -> tests -> quantum -> packages -> repo root
    / "supabase" / "migrations"
)
# Production migration chain that shapes fleet_policy_decisions, in timestamp
# order: the C1 foundation THEN the v2 candidate-fingerprint identity evolution
# (nullable suggestion UUID + data_unavailable disposition + fingerprint dedup).
_MIGRATIONS = [
    _MIG_DIR / "20260723160000_fleet_policy_decision_foundation.sql",
    _MIG_DIR / "20260724010000_fleet_decisions_candidate_fingerprint_identity.sql",
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
    collect_ignore = [
        "test_fleet_policy_decision_pg.py",
        "test_fleet_decisions_v2_identity_pg.py",
    ]


def _connect():
    import pg8000.dbapi as db

    conn = db.connect(**_DSN)
    conn.autocommit = True
    return conn


@pytest.fixture(scope="session")
def fleet_pg_schema():
    """Create the base tables + apply the migration under test ONCE."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute(_BOOTSTRAP_SQL.read_text(encoding="utf-8"))
    for mig in _MIGRATIONS:
        cur.execute(mig.read_text(encoding="utf-8"))
    cur.close()
    conn.close()
    yield


@pytest.fixture()
def conn(fleet_pg_schema):
    """A fresh autocommit connection with the evidence tables truncated clean."""
    c = _connect()
    cur = c.cursor()
    cur.execute(
        "TRUNCATE fleet_policy_decisions, fleet_policy_decision_runs, "
        "shadow_micro_accounts, shadow_fleets, policy_registrations "
        "RESTART IDENTITY CASCADE"
    )
    cur.close()
    yield c
    c.close()
