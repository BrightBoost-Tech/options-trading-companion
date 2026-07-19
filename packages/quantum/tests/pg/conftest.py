"""Real-PostgreSQL harness for the rpc_commit_internal_close_v1 transaction
suite (V17-1 F-A2, Lane 1A).

These tests exercise the ACTUAL migration SQL against a live Postgres so the
atomicity / rollback / concurrency / idempotency guarantees are proven, not
mirrored. They require a reachable Postgres and the pure-python ``pg8000``
driver.

CI-safety WITHOUT a skip/xfail: when no Postgres is reachable (the default in
this repo's CI, which runs no pg service), the real-pg module is removed from
collection via ``collect_ignore`` below — the same "uncollectable file"
convention the repo already uses for the fork/ordering modules. No
``pytest.mark.skip`` / ``xfail`` is introduced. The always-green CI signal for
this function lives in the pure-python mirror suite
(test_rpc_commit_internal_close_mirror.py, one directory up).

To RUN the real-pg suite locally / in review, point it at a throwaway Postgres:

    docker run -d --name pg -e POSTGRES_PASSWORD=pw -e POSTGRES_USER=pg \
        -e POSTGRES_DB=testdb -p 55432:5432 postgres:16-alpine
    WT17_PG_PORT=55432 py -3.11 -m pytest packages/quantum/tests/pg

Connection is read from WT17_PG_{HOST,PORT,USER,PASSWORD,DB} (defaults target
the command above).
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
_MIGRATION_SQL = (
    _HERE.parents[3]  # repo root: tests/pg -> tests -> quantum -> packages -> root
    / "supabase" / "migrations"
    / "20260719180000_rpc_commit_internal_close_v1.sql"
)


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


# Remove the real-pg module from collection when infra is absent (NOT a skip).
if not _pg_reachable():
    collect_ignore = ["test_rpc_commit_internal_close_pg.py"]


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures (only reached when the module is collected, i.e. pg is reachable)
# ─────────────────────────────────────────────────────────────────────────────
def _connect():
    import pg8000.dbapi as db
    conn = db.connect(**_DSN)
    conn.autocommit = True
    return conn


@pytest.fixture(scope="session")
def pg_schema():
    """Create the base tables + apply the migration under test ONCE."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute(_BOOTSTRAP_SQL.read_text(encoding="utf-8"))
    cur.execute(_MIGRATION_SQL.read_text(encoding="utf-8"))
    cur.close()
    conn.close()
    yield
    # Leave the schema in place; the throwaway container is discarded by the
    # operator. (Dropping here would race parallel connections needlessly.)


@pytest.fixture()
def conn(pg_schema):
    """A fresh autocommit connection with the 4 tables truncated clean."""
    c = _connect()
    cur = c.cursor()
    cur.execute(
        "TRUNCATE paper_ledger, paper_orders, paper_positions, paper_portfolios "
        "RESTART IDENTITY CASCADE"
    )
    # Drop any failure-injection triggers a prior test may have left (defensive).
    _drop_injectors(cur)
    cur.close()
    yield c
    cur = c.cursor()
    _drop_injectors(cur)
    cur.close()
    c.close()


def _drop_injectors(cur):
    for tbl in ("paper_orders", "paper_portfolios", "paper_ledger", "paper_positions"):
        cur.execute(f"DROP TRIGGER IF EXISTS wt17_inject ON {tbl}")
    cur.execute("DROP FUNCTION IF EXISTS wt17_raise() CASCADE")
