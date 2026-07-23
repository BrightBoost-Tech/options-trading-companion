"""Real-PostgreSQL proof of the P1-1 event_id migration
(20260723150000_suggestion_rejections_event_id.sql) applied verbatim.

Proves against a live Postgres what the pure-python mirror can only assert on
text: the UNIQUE PARTIAL INDEX enforces one row per non-null event_id, and the
append-only idempotent code contract (INSERT + catch-23505-as-duplicate_ack)
is real. Collected only when a Postgres is reachable (see conftest).
"""

import uuid

import pytest

pg8000 = pytest.importorskip("pg8000")


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _insert(cur, event_id, symbol="SPY", reason="edge_below_minimum",
            strategy_key="IRON_CONDOR"):
    cur.execute(
        "INSERT INTO public.suggestion_rejections "
        "(symbol, strategy_key, reason, cycle_date, event_id) "
        "VALUES (%s, %s, %s, DATE '2026-07-23', %s)",
        (symbol, strategy_key, reason, event_id),
    )


def test_event_id_column_exists_and_is_uuid(conn):
    cur = conn.cursor()
    cur.execute(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name='suggestion_rejections' "
        "AND column_name='event_id'"
    )
    row = cur.fetchone()
    assert row is not None, "event_id column not added"
    assert row[0] == "uuid"


def test_partial_unique_index_present_and_partial(conn):
    cur = conn.cursor()
    cur.execute(
        "SELECT indexdef FROM pg_indexes "
        "WHERE schemaname='public' AND tablename='suggestion_rejections' "
        "AND indexname='suggestion_rejections_event_id_key'"
    )
    row = cur.fetchone()
    assert row is not None, "unique index missing"
    indexdef = row[0].upper()
    assert "UNIQUE" in indexdef
    assert "WHERE" in indexdef and "IS NOT NULL" in indexdef, (
        f"index must be PARTIAL (WHERE event_id IS NOT NULL): {row[0]}")


def test_duplicate_event_id_raises_23505(conn):
    """A re-insert of the SAME event_id (the response-lost-after-commit retry)
    raises the unique violation the persistence code catches as duplicate_ack —
    exactly ONE physical row survives."""
    cur = conn.cursor()
    eid = _new_uuid()
    _insert(cur, eid)
    with pytest.raises(Exception) as ei:
        _insert(cur, eid)  # same event_id -> 23505
    msg = str(ei.value).lower()
    assert "23505" in msg or "unique" in msg or "duplicate" in msg, msg

    # After the connection recovers, exactly one row exists for that event_id.
    cur2 = conn.cursor()
    cur2.execute(
        "SELECT count(*) FROM public.suggestion_rejections WHERE event_id = %s",
        (eid,),
    )
    assert cur2.fetchone()[0] == 1


def test_multiple_null_event_ids_coexist(conn):
    """Historical rows (event_id NULL) coexist untouched — the partial index
    ignores NULLs, so no backfill is required and many NULLs are allowed."""
    cur = conn.cursor()
    for _ in range(3):
        cur.execute(
            "INSERT INTO public.suggestion_rejections "
            "(symbol, reason, cycle_date, event_id) "
            "VALUES ('QQQ', 'no_chain', DATE '2026-05-13', NULL)"
        )
    cur.execute(
        "SELECT count(*) FROM public.suggestion_rejections WHERE event_id IS NULL"
    )
    assert cur.fetchone()[0] == 3


def test_distinct_event_ids_both_persist(conn):
    """Two DISTINCT legitimate rejections (different event_ids) both persist —
    legitimate repeats stay distinguishable, not collapsed by a natural key."""
    cur = conn.cursor()
    a, b = _new_uuid(), _new_uuid()
    _insert(cur, a, reason="execution_cost_exceeds_ev")
    _insert(cur, b, reason="execution_cost_exceeds_ev")  # identical-looking, new id
    cur.execute("SELECT count(*) FROM public.suggestion_rejections")
    assert cur.fetchone()[0] == 2
