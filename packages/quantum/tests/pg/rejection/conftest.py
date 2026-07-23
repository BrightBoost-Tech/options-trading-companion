"""Real-PostgreSQL harness for the P1-1 suggestion_rejections event_id
migration (append-only idempotent rejection persistence).

Applies the ACTUAL migration SQL (20260723150000) on top of the pre-migration
base table, so the ADD COLUMN + UNIQUE PARTIAL INDEX (WHERE event_id IS NOT
NULL) semantics are PROVEN against a live Postgres — not mirrored: a re-insert
of the same event_id really raises 23505; multiple NULL event_ids really
coexist; the migration really re-applies cleanly (idempotent). Requires a
reachable Postgres and the pure-python ``pg8000`` driver.

CI-safety WITHOUT a skip/xfail: when no Postgres is reachable (this repo's CI
runs no pg service), the real-pg module is removed from collection via
``collect_ignore`` below — the same "uncollectable file" convention the repo
already uses (see ../conftest.py, ../receipt/conftest.py). No
``pytest.mark.skip`` / ``xfail`` is introduced. The always-green CI signal for
this migration lives in the pure-python mirror suite
(test_suggestion_rejections_event_id_migration_contract.py) and the
idempotent-persistence route suite
(test_scanner_rejection_idempotent_persist.py), both one directory up.

To RUN locally / in review, point it at a throwaway Postgres:

    docker run -d --name pg -e POSTGRES_PASSWORD=pw -e POSTGRES_USER=pg \
        -e POSTGRES_DB=testdb -p 55432:5432 postgres:17-alpine
    WT17_PG_PORT=55432 py -3.11 -m pytest packages/quantum/tests/pg/rejection

Connection is read from WT17_PG_{HOST,PORT,USER,PASSWORD,DB} (same env as the
sibling suites). Run this subpackage TARGETED — the sibling suites bootstrap
overlapping base tables in the same DB.
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
# rejection -> pg -> tests -> quantum -> packages -> repo root
_MIG_DIR = _HERE.parents[4] / "supabase" / "migrations"
_MIGRATION_SQL = _MIG_DIR / "20260723150000_suggestion_rejections_event_id.sql"


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
    collect_ignore = ["test_suggestion_rejections_event_id_pg.py"]


def _connect():
    import pg8000.dbapi as db
    conn = db.connect(**_DSN)
    conn.autocommit = True
    return conn


@pytest.fixture(scope="session")
def rejection_pg_schema():
    """Bootstrap the pre-migration table + apply the P1-1 migration TWICE
    (idempotency: the second apply must be a clean no-op)."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute(_BOOTSTRAP_SQL.read_text(encoding="utf-8"))
    migration_sql = _MIGRATION_SQL.read_text(encoding="utf-8")
    cur.execute(migration_sql)
    # Re-apply verbatim: IF NOT EXISTS on both statements must make this a no-op
    # (the code tolerates the column already existing; the migration too).
    cur.execute(migration_sql)
    cur.close()
    conn.close()
    yield


@pytest.fixture()
def conn(rejection_pg_schema):
    """Fresh autocommit connection with the table truncated clean per test."""
    c = _connect()
    cur = c.cursor()
    cur.execute("TRUNCATE public.suggestion_rejections RESTART IDENTITY")
    cur.close()
    yield c
    c.close()
