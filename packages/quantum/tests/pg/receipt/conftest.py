"""Real-PostgreSQL harness for the reconciliation-receipt writer (Lane A/B).

Exercises the ACTUAL migration SQL against a live Postgres so the writer RPC's
identity/scope/completed-state proofs, idempotency, concurrency, immutability,
and the Lane-B privilege hardening are proven — not mirrored. Requires a
reachable Postgres and the pure-python ``pg8000`` driver.

CI-safety WITHOUT a skip/xfail: when no Postgres is reachable (this repo's CI
runs no pg service), the real-pg module is removed from collection via
``collect_ignore`` below — the same "uncollectable file" convention the repo
already uses (see ../conftest.py and the fork/ordering modules). No
``pytest.mark.skip`` / ``xfail`` is introduced. The always-green CI signal for
this RPC lives in the pure-python mirror suite
(packages/quantum/tests/test_fleet_reconciliation_receipt_writer.py).

To RUN locally / in review, point it at a throwaway Postgres. PostgreSQL 17+ is
required: the 20260721011000 migration REVOKEs the PG17 MAINTAIN privilege (that
keyword does not exist before PG17), and production is 17.6 — so the container
must match:

    docker run -d --name pg -e POSTGRES_PASSWORD=pw -e POSTGRES_USER=pg \
        -e POSTGRES_DB=testdb -p 55432:5432 postgres:17-alpine
    WT17_PG_PORT=55432 py -3.11 -m pytest packages/quantum/tests/pg/receipt

Connection is read from WT17_PG_{HOST,PORT,USER,PASSWORD,DB} (same env as the
sibling internal-close suite). Run this subpackage TARGETED (not the whole
tests/pg tree) — the two suites bootstrap overlapping base tables in the same DB.
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
_MIG_DIR = _HERE.parents[4] / "supabase" / "migrations"  # receipt->pg->tests->quantum->packages->repo
_MIGRATIONS = [
    _MIG_DIR / "20260720140000_fleet_reconciliation_receipts.sql",          # D1 schema
    _MIG_DIR / "20260721010000_rpc_issue_fleet_reconciliation_receipt_v1.sql",  # Lane A
    _MIG_DIR / "20260721010500_harden_fleet_receipt_privileges.sql",         # Lane B
    _MIG_DIR / "20260721011000_revoke_fleet_receipt_maintain.sql",           # Lane B follow-up: drop residual PG17 MAINTAIN
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


# Remove the real-pg module from collection when infra is absent (NOT a skip).
if not _pg_reachable():
    collect_ignore = ["test_rpc_issue_fleet_reconciliation_receipt_pg.py"]


def _connect():
    import pg8000.dbapi as db
    conn = db.connect(**_DSN)
    conn.autocommit = True
    return conn


@pytest.fixture(scope="session")
def receipt_pg_schema():
    """Apply the bootstrap base tables + the 4 receipt migrations ONCE.

    PostgreSQL 17+ is required (the final migration REVOKEs MAINTAIN, a PG17
    privilege). Fail loudly with a clear message rather than let the apply die on
    an opaque "unrecognized privilege type: maintain" — this is a precondition,
    not a skip."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SHOW server_version_num")
    server_version_num = int(cur.fetchone()[0])
    if server_version_num < 170000:
        cur.close()
        conn.close()
        raise RuntimeError(
            "receipt real-pg suite requires PostgreSQL >= 17 "
            f"(found server_version_num={server_version_num}); the "
            "20260721011000 migration REVOKEs the PG17 MAINTAIN privilege and "
            "production is 17.6. Point WT17_PG_* at a postgres:17+ container.")
    cur.execute(_BOOTSTRAP_SQL.read_text(encoding="utf-8"))
    for mig in _MIGRATIONS:
        cur.execute(mig.read_text(encoding="utf-8"))
    cur.close()
    conn.close()
    yield


@pytest.fixture()
def conn(receipt_pg_schema):
    """A fresh autocommit connection.

    No table is truncated between tests: fleet_reconciliation_receipts is
    append-only (no TRUNCATE/DELETE) and risk_alerts is referenced by its FK, so
    it cannot be truncated once a receipt points at it. Every test instead uses a
    fresh random user_id + source id + FULL fingerprint, so rows never collide
    across tests — accumulation is harmless (all count assertions filter by the
    per-test fingerprint)."""
    c = _connect()
    yield c
    c.close()
