"""REAL-PostgreSQL tests for the v1.7 guard-hardening of
rpc_commit_internal_close_v1 (migration
20260720120000_rpc_commit_internal_close_v1_guard_hardening.sql).

This module applies the ORIGINAL v1 migration (via the shared `pg_schema`
fixture in conftest.py) and THEN the v1.7 `CREATE OR REPLACE` on top, so every
test here drives the HARDENED function against a live Postgres. It proves the
two follow-ups end-to-end and — critically — that the economic core is
byte-unchanged:

  FOLLOW-UP 1 (clarity): a 'live_eligible' portfolio is rejected with the new
  SPECIFIC typed error, an 'alpaca_live' order is still rejected, and a
  'shadow_only' internal close still commits — the accept/reject outcome is
  identical to v1.

  FOLLOW-UP 2 (real fix): a NaN/±Infinity p_fill_mid_reference is rejected
  (typed non_finite_input) with ZERO writes — because on PG17 a non-finite
  numeric serializes to a JSON *string* and would otherwise be durably stored;
  a finite reference round-trips into both sinks; a NULL reference (the
  designed default) is accepted unchanged.

Same de-collection convention as the sibling real-pg module (no skip/xfail):
conftest.py removes this file from collection when no Postgres is reachable.
"""

import json
import uuid
from pathlib import Path

import pytest

# Reuse the shared real-pg harness (DSN + connect + schema/truncation fixtures).
from .conftest import _DSN, _connect  # type: ignore

_V17_MIGRATION_SQL = (
    Path(__file__).resolve().parents[4]  # file: pg -> tests -> quantum -> packages -> repo root
    / "supabase" / "migrations"
    / "20260720120000_rpc_commit_internal_close_v1_guard_hardening.sql"
)

_CALL = (
    "select rpc_commit_internal_close_v1("
    "%s::uuid,%s::uuid,%s::uuid,%s::uuid,"
    "%s::text,%s::text,%s::text,%s::text,"
    "%s::numeric,%s::numeric,%s::numeric,%s::numeric)"
)
_CALL_PROV = _CALL[:-1] + ",%s::text,%s::numeric)"  # + p_fill_quality, p_fill_mid_reference

_REASON = "target_profit_hit"
_SOURCE = "exit_evaluator"


# ── the v1.7 replace, applied ONCE on top of the base schema/migration ────────
@pytest.fixture(scope="session")
def pg_schema_v17(pg_schema):
    """Apply the CREATE OR REPLACE hardening on top of the base v1 migration."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute(_V17_MIGRATION_SQL.read_text(encoding="utf-8"))
    cur.close()
    conn.close()
    yield


# ─────────────────────────── helpers ────────────────────────────────────────
def _decode(v):
    return json.loads(v) if isinstance(v, str) else v


def _mk_portfolio(cur, user, cash=10000, routing="shadow_only"):
    cur.execute(
        "insert into paper_portfolios (user_id,name,cash_balance,net_liq,routing_mode) "
        "values (%s,'book',%s,%s,%s) returning id",
        (user, cash, cash, routing),
    )
    return cur.fetchone()[0]


def _mk_position(cur, user, pf, symbol="QQQ", qty=2, entry=1.50):
    cur.execute(
        "insert into paper_positions "
        "(user_id,portfolio_id,symbol,quantity,avg_entry_price,status) "
        "values (%s,%s,%s,%s,%s,'open') returning id",
        (user, pf, symbol, qty, entry),
    )
    return cur.fetchone()[0]


def _mk_order(cur, user, pf, pos, side="sell", execution_mode="internal_paper"):
    cur.execute(
        "insert into paper_orders "
        "(user_id,portfolio_id,position_id,status,side,execution_mode) "
        "values (%s,%s,%s,'submitted',%s,%s) returning id",
        (user, pf, pos, side, execution_mode),
    )
    return cur.fetchone()[0]


def _args(user, pf, pos, od, key="k1", reason=_REASON, source=_SOURCE,
          side="sell", qty=2, mag=2.00, realized=50.00, mult=100):
    return (user, pf, pos, od, key, reason, source, side, qty, mag, realized, mult)


def _commit(cur, args):
    cur.execute(_CALL, args)
    return _decode(cur.fetchone()[0])


def _commit_err(cur, args, token, call=_CALL):
    with pytest.raises(Exception) as ei:
        cur.execute(call, args)
        cur.fetchone()
    assert token in str(ei.value), f"expected {token!r} in error, got: {ei.value}"


def _scalar(cur, sql, params):
    cur.execute(sql, params)
    return cur.fetchone()[0]


def _row_json(cur, table, _id):
    cur.execute(f"select to_jsonb(t) from {table} t where id=%s", (_id,))
    return _decode(cur.fetchone()[0])


def _assert_clean(cur, pf, pos, od, cash0):
    assert float(_scalar(cur, "select cash_balance from paper_portfolios where id=%s", (pf,))) == cash0
    o = _row_json(cur, "paper_orders", od)
    assert o["status"] == "submitted"
    assert o["internal_close_committed_at"] is None
    assert o["internal_close_commit_key"] is None
    assert int(_scalar(cur, "select count(*) from paper_ledger where order_id=%s and event_type='fill'", (od,))) == 0
    assert _row_json(cur, "paper_positions", pos)["status"] == "open"


# ════════════════════ FOLLOW-UP 1: routing accept-gate ═══════════════════════
def test_internal_shadow_close_allowed_debit_long(conn, pg_schema_v17):
    """A shadow_only internal close still commits; economics BYTE-UNCHANGED
    (long debit sell-to-close => cash IN +400 = +2*2.00*100)."""
    cur = conn.cursor(); u = str(uuid.uuid4())
    pf = _mk_portfolio(cur, u, cash=10000, routing="shadow_only")
    pos = _mk_position(cur, u, pf, qty=2, entry=1.50)
    od = _mk_order(cur, u, pf, pos, side="sell")
    r = _commit(cur, _args(u, pf, pos, od, side="sell", qty=2, mag=2.00, realized=100.0))
    assert r["committed"] is True and r["idempotent_replay"] is False
    assert float(r["cash_after"]) == 10400.0
    assert float(_scalar(cur, "select amount from paper_ledger where order_id=%s", (od,))) == 400.0
    p = _row_json(cur, "paper_positions", pos)
    assert p["status"] == "closed" and float(p["realized_pl"]) == 100.0


def test_internal_shadow_close_allowed_credit_short(conn, pg_schema_v17):
    """Credit short buy-to-close => cash OUT (-240); economics BYTE-UNCHANGED."""
    cur = conn.cursor(); u = str(uuid.uuid4())
    pf = _mk_portfolio(cur, u, cash=10000, routing="shadow_only")
    pos = _mk_position(cur, u, pf, qty=-3, entry=1.00)
    od = _mk_order(cur, u, pf, pos, side="buy")
    r = _commit(cur, _args(u, pf, pos, od, side="buy", qty=3, mag=0.80, realized=-40.0))
    assert float(r["cash_after"]) == 9760.0
    assert float(_scalar(cur, "select amount from paper_ledger where order_id=%s", (od,))) == -240.0
    assert float(_row_json(cur, "paper_positions", pos)["realized_pl"]) == -40.0


def test_live_eligible_routing_rejected_with_specific_typed_error(conn, pg_schema_v17):
    """FOLLOW-UP 1: a 'live_eligible' portfolio is rejected DELIBERATELY with the
    new specific error, and nothing is written. (v1 already rejected it via the
    allowlist; the outcome is identical — this asserts the clarified message.)"""
    cur = conn.cursor(); u = str(uuid.uuid4())
    pf = _mk_portfolio(cur, u, routing="live_eligible")
    pos = _mk_position(cur, u, pf, qty=2)
    od = _mk_order(cur, u, pf, pos, execution_mode="internal_paper")
    _commit_err(cur, _args(u, pf, pos, od), "live_order_forbidden (routing_mode=live_eligible)")
    _assert_clean(cur, pf, pos, od, 10000.0)


def test_alpaca_live_execution_mode_still_rejected(conn, pg_schema_v17):
    """Live isolation preserved: an execution_mode='alpaca_live' order is still
    rejected (the ghost-fill guard is unchanged by the v1.7 clarity tweak)."""
    cur = conn.cursor(); u = str(uuid.uuid4())
    pf = _mk_portfolio(cur, u, routing="shadow_only")
    pos = _mk_position(cur, u, pf, qty=2)
    od = _mk_order(cur, u, pf, pos, execution_mode="alpaca_live")
    _commit_err(cur, _args(u, pf, pos, od), "live_order_forbidden (execution_mode=alpaca_live)")
    _assert_clean(cur, pf, pos, od, 10000.0)


# ════════════════ FOLLOW-UP 2: non-finite provenance guard ═══════════════════
def test_pg17_would_store_non_finite_provenance_as_json_string(conn, pg_schema_v17):
    """DOCUMENTS THE HAZARD the guard closes: on PG17 a non-finite numeric is
    serialized to a JSON *string* (it does NOT raise), so an unguarded
    p_fill_mid_reference WOULD be durably stored."""
    cur = conn.cursor()
    for lit in ("NaN", "Infinity", "-Infinity"):
        cur.execute("select jsonb_build_object('fill_mid_reference', %s::numeric)", (lit,))
        stored = _decode(cur.fetchone()[0])
        assert stored == {"fill_mid_reference": lit}  # would be persisted verbatim


@pytest.mark.parametrize("badval", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_fill_mid_reference_rejected_zero_writes(conn, pg_schema_v17, badval):
    """FOLLOW-UP 2: NaN/±Infinity provenance => typed non_finite_input, and NOT
    ONE write survives (the value never reaches order_json / ledger metadata)."""
    cur = conn.cursor(); u = str(uuid.uuid4())
    pf = _mk_portfolio(cur, u); pos = _mk_position(cur, u, pf, qty=2); od = _mk_order(cur, u, pf, pos)
    args = _args(u, pf, pos, od) + ("mid_fallback", badval)
    _commit_err(cur, args, "non_finite_input", call=_CALL_PROV)
    _assert_clean(cur, pf, pos, od, 10000.0)


def test_finite_fill_mid_reference_accepted_round_trips_both_sinks(conn, pg_schema_v17):
    """A FINITE provenance value is accepted unchanged and lands in BOTH the
    order_json and the ledger metadata (economic core untouched)."""
    cur = conn.cursor(); u = str(uuid.uuid4())
    pf = _mk_portfolio(cur, u); pos = _mk_position(cur, u, pf, qty=2); od = _mk_order(cur, u, pf, pos)
    cur.execute(_CALL_PROV, _args(u, pf, pos, od, mag=2.00, realized=100.0) + ("mid_fallback", 1.87))
    r = _decode(cur.fetchone()[0])
    assert r["committed"] is True and float(r["cash_after"]) == 10400.0
    oj = _row_json(cur, "paper_orders", od)["order_json"]
    assert oj["fill_quality"] == "mid_fallback" and float(oj["fill_mid_reference"]) == 1.87
    cur.execute("select metadata from paper_ledger where order_id=%s and event_type='fill'", (od,))
    meta = _decode(cur.fetchone()[0])
    assert meta["fill_quality"] == "mid_fallback" and float(meta["fill_mid_reference"]) == 1.87


def test_null_fill_mid_reference_accepted_as_designed(conn, pg_schema_v17):
    """NULL provenance (the default) is DESIGNED-VALID: the NULL-safe IN-guard
    lets it pass; order_json stays '{}' and the ledger provenance keys are NULL.
    The economic receipt is byte-unchanged from a no-provenance close."""
    cur = conn.cursor(); u = str(uuid.uuid4())
    pf = _mk_portfolio(cur, u); pos = _mk_position(cur, u, pf, qty=2); od = _mk_order(cur, u, pf, pos)
    # explicit NULL provenance via the 14-arg call
    cur.execute(_CALL_PROV, _args(u, pf, pos, od, mag=2.00, realized=100.0) + (None, None))
    r = _decode(cur.fetchone()[0])
    assert r["committed"] is True and float(r["cash_after"]) == 10400.0
    assert _row_json(cur, "paper_orders", od)["order_json"] == {}
    cur.execute("select metadata->>'fill_quality', metadata->>'fill_mid_reference' "
                "from paper_ledger where order_id=%s and event_type='fill'", (od,))
    assert cur.fetchone() == [None, None]


# ════════════════ replay / idempotency UNCHANGED by the hardening ════════════
def test_idempotent_replay_unchanged(conn, pg_schema_v17):
    cur = conn.cursor(); u = str(uuid.uuid4())
    pf = _mk_portfolio(cur, u); pos = _mk_position(cur, u, pf, qty=2); od = _mk_order(cur, u, pf, pos)
    r1 = _commit(cur, _args(u, pf, pos, od, key="kX"))
    r2 = _commit(cur, _args(u, pf, pos, od, key="kX"))
    assert r1["idempotent_replay"] is False and r2["idempotent_replay"] is True
    assert r1["ledger_event_id"] == r2["ledger_event_id"]
    assert int(_scalar(cur, "select count(*) from paper_ledger where order_id=%s", (od,))) == 1
    assert float(_scalar(cur, "select cash_balance from paper_portfolios where id=%s", (pf,))) == 10400.0


def test_conflicting_key_rejected_unchanged(conn, pg_schema_v17):
    cur = conn.cursor(); u = str(uuid.uuid4())
    pf = _mk_portfolio(cur, u); pos = _mk_position(cur, u, pf, qty=2); od = _mk_order(cur, u, pf, pos)
    _commit(cur, _args(u, pf, pos, od, key="first"))
    _commit_err(cur, _args(u, pf, pos, od, key="second"), "idempotency_conflict")
    assert int(_scalar(cur, "select count(*) from paper_ledger where order_id=%s", (od,))) == 1
    assert float(_scalar(cur, "select cash_balance from paper_portfolios where id=%s", (pf,))) == 10400.0
