"""REAL-PostgreSQL transaction tests for rpc_commit_internal_close_v1
(V17-1 F-A2-INTERNAL-CLOSE-PRECOMMIT-SIDE-EFFECTS, Lane 1A).

These drive the ACTUAL migration SQL against a live Postgres (see conftest.py
for how the ephemeral DB is provisioned and how this module is transparently
de-collected when no pg is reachable — no skip/xfail). They prove the
economic-commit is ATOMIC (all-or-none), IDEMPOTENT on (order, key), and
CONFLICT-safe under concurrency — the exact guarantees the non-atomic Python
route lacks.

Failure is injected at the ORIGIN (a guard input, a pre-closed position, or a
BEFORE-trigger on the deepest write) and the invariant is asserted at the TOP
(zero surviving economic writes, OR exactly one clean committed close — never a
partial).
"""

import json
import os
import threading
import uuid

import pytest

# Same connection env the conftest uses (kept local to avoid a relative import).
_DSN = dict(
    host=os.environ.get("WT17_PG_HOST", "127.0.0.1"),
    port=int(os.environ.get("WT17_PG_PORT", "55432")),
    user=os.environ.get("WT17_PG_USER", "pg"),
    password=os.environ.get("WT17_PG_PASSWORD", "pw"),
    database=os.environ.get("WT17_PG_DB", "testdb"),
)

# 12 positional args, in the function's declared order.
_CALL = (
    "select rpc_commit_internal_close_v1("
    "%s::uuid,%s::uuid,%s::uuid,%s::uuid,"      # user, portfolio, position, order
    "%s::text,%s::text,%s::text,%s::text,"       # key, reason, source, side
    "%s::numeric,%s::numeric,%s::numeric,%s::numeric)"  # qty, mag, realized_pl, mult
)

_REASON = "target_profit_hit"
_SOURCE = "exit_evaluator"


# ─────────────────────────── row helpers ────────────────────────────────────
def _decode(v):
    return json.loads(v) if isinstance(v, str) else v


def _mk_portfolio(cur, user, cash=10000, routing="shadow_only"):
    cur.execute(
        "insert into paper_portfolios (user_id,name,cash_balance,net_liq,routing_mode) "
        "values (%s,'book',%s,%s,%s) returning id",
        (user, cash, cash, routing),
    )
    return cur.fetchone()[0]


def _mk_position(cur, user, pf, symbol="QQQ", qty=2, entry=1.50, status="open",
                 realized=None, reason=None, source=None, closed_at=None):
    cur.execute(
        "insert into paper_positions "
        "(user_id,portfolio_id,symbol,quantity,avg_entry_price,status,"
        " realized_pl,close_reason,fill_source,closed_at) "
        "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id",
        (user, pf, symbol, qty, entry, status, realized, reason, source, closed_at),
    )
    return cur.fetchone()[0]


def _mk_order(cur, user, pf, pos, status="submitted", side="sell",
              execution_mode="internal_paper"):
    cur.execute(
        "insert into paper_orders "
        "(user_id,portfolio_id,position_id,status,side,execution_mode) "
        "values (%s,%s,%s,%s,%s,%s) returning id",
        (user, pf, pos, status, side, execution_mode),
    )
    return cur.fetchone()[0]


def _args(user, pf, pos, od, key="k1", reason=_REASON, source=_SOURCE,
          side="sell", qty=2, mag=2.00, realized=50.00, mult=100):
    return (user, pf, pos, od, key, reason, source, side, qty, mag, realized, mult)


def _commit(cur, args):
    cur.execute(_CALL, args)
    return _decode(cur.fetchone()[0])


def _commit_err(cur, args, token):
    with pytest.raises(Exception) as ei:
        cur.execute(_CALL, args)
        cur.fetchone()
    assert token in str(ei.value), f"expected {token!r} in error, got: {ei.value}"


def _scalar(cur, sql, params):
    cur.execute(sql, params)
    return cur.fetchone()[0]


def _row_json(cur, table, _id):
    cur.execute(f"select to_jsonb(t) from {table} t where id=%s", (_id,))
    return _decode(cur.fetchone()[0])


def _install_injector(cur, table):
    """A BEFORE INSERT/UPDATE trigger on `table` that always raises — used to
    force a DB failure at that specific write and prove the whole commit rolls
    back."""
    cur.execute(
        "create or replace function wt17_raise() returns trigger language plpgsql "
        "as $$ begin raise exception 'wt17_injected_failure'; end $$"
    )
    cur.execute(
        f"create trigger wt17_inject before insert or update on {table} "
        f"for each row execute function wt17_raise()"
    )


def _assert_clean(cur, pf, pos, od, cash0):
    """No economic write survived: cash unmoved, order not filled/committed, no
    fill ledger, position still open."""
    assert float(_scalar(cur, "select cash_balance from paper_portfolios where id=%s", (pf,))) == cash0
    o = _row_json(cur, "paper_orders", od)
    assert o["status"] == "submitted"
    assert o["internal_close_committed_at"] is None
    assert o["internal_close_commit_key"] is None
    assert o["filled_qty"] is None
    assert int(_scalar(cur, "select count(*) from paper_ledger where order_id=%s and event_type='fill'", (od,))) == 0
    p = _row_json(cur, "paper_positions", pos)
    assert p["status"] == "open"
    assert p["realized_pl"] is None
    assert float(p["quantity"]) != 0


# ─────────────────────────── happy paths ─────────────────────────────────────
def test_happy_debit_close_long_sells_cash_in(conn):
    """Long (qty>0) debit spread: sell-to-close => cash IN (+)."""
    cur = conn.cursor()
    u = str(uuid.uuid4())
    pf = _mk_portfolio(cur, u, cash=10000)
    pos = _mk_position(cur, u, pf, qty=2, entry=1.50)
    od = _mk_order(cur, u, pf, pos, side="sell")

    r = _commit(cur, _args(u, pf, pos, od, side="sell", qty=2, mag=2.00, realized=100.0))

    assert r["committed"] is True and r["idempotent_replay"] is False
    assert float(r["cash_after"]) == 10400.0                # +2*2.00*100
    assert float(_scalar(cur, "select cash_balance from paper_portfolios where id=%s", (pf,))) == 10400.0
    o = _row_json(cur, "paper_orders", od)
    assert o["status"] == "filled" and float(o["filled_qty"]) == 2
    assert o["internal_close_commit_key"] == "k1"
    assert int(_scalar(cur, "select count(*) from paper_ledger where order_id=%s and event_type='fill'", (od,))) == 1
    amt = float(_scalar(cur, "select amount from paper_ledger where order_id=%s", (od,)))
    assert amt == 400.0                                     # cash IN
    p = _row_json(cur, "paper_positions", pos)
    assert p["status"] == "closed" and float(p["quantity"]) == 0 and float(p["realized_pl"]) == 100.0


def test_happy_credit_close_short_buys_cash_out(conn):
    """Short (qty<0) credit spread: buy-to-close => cash OUT (-)."""
    cur = conn.cursor()
    u = str(uuid.uuid4())
    pf = _mk_portfolio(cur, u, cash=10000)
    pos = _mk_position(cur, u, pf, qty=-3, entry=1.00)
    od = _mk_order(cur, u, pf, pos, side="buy")

    r = _commit(cur, _args(u, pf, pos, od, side="buy", qty=3, mag=0.80, realized=-40.0))

    assert r["committed"] is True
    assert float(r["cash_after"]) == 9760.0                 # -3*0.80*100 = -240
    amt = float(_scalar(cur, "select amount from paper_ledger where order_id=%s", (od,)))
    assert amt == -240.0                                    # cash OUT
    p = _row_json(cur, "paper_positions", pos)
    assert p["status"] == "closed" and float(p["realized_pl"]) == -40.0


# ─────────────────── guard-level rejections (nothing written) ────────────────
def test_reject_unknown_reason(conn):
    cur = conn.cursor(); u = str(uuid.uuid4())
    pf = _mk_portfolio(cur, u); pos = _mk_position(cur, u, pf); od = _mk_order(cur, u, pf, pos)
    _commit_err(cur, _args(u, pf, pos, od, reason="not_a_reason"), "invalid_close_reason")
    _assert_clean(cur, pf, pos, od, 10000.0)


def test_reject_invalid_fill_source(conn):
    cur = conn.cursor(); u = str(uuid.uuid4())
    pf = _mk_portfolio(cur, u); pos = _mk_position(cur, u, pf); od = _mk_order(cur, u, pf, pos)
    _commit_err(cur, _args(u, pf, pos, od, source="nope"), "invalid_fill_source")
    _assert_clean(cur, pf, pos, od, 10000.0)


def test_reject_null_realized_pl(conn):
    """The RPC-boundary equivalent of the upstream realized-P&L computation
    failing: realized_pl NULL => reject, zero writes."""
    cur = conn.cursor(); u = str(uuid.uuid4())
    pf = _mk_portfolio(cur, u); pos = _mk_position(cur, u, pf); od = _mk_order(cur, u, pf, pos)
    _commit_err(cur, _args(u, pf, pos, od, realized=None), "realized_pl_required")
    _assert_clean(cur, pf, pos, od, 10000.0)


def test_reject_nonpositive_magnitude(conn):
    cur = conn.cursor(); u = str(uuid.uuid4())
    pf = _mk_portfolio(cur, u); pos = _mk_position(cur, u, pf); od = _mk_order(cur, u, pf, pos)
    _commit_err(cur, _args(u, pf, pos, od, mag=0), "nonpositive_fill_magnitude")
    _assert_clean(cur, pf, pos, od, 10000.0)


def test_reject_missing_idempotency_key(conn):
    cur = conn.cursor(); u = str(uuid.uuid4())
    pf = _mk_portfolio(cur, u); pos = _mk_position(cur, u, pf); od = _mk_order(cur, u, pf, pos)
    _commit_err(cur, _args(u, pf, pos, od, key="  "), "idempotency_key_required")
    _assert_clean(cur, pf, pos, od, 10000.0)


def test_reject_side_mismatch(conn):
    """A long position closed with 'buy' contradicts the server-derived
    direction => reject (client side is verified, never trusted)."""
    cur = conn.cursor(); u = str(uuid.uuid4())
    pf = _mk_portfolio(cur, u); pos = _mk_position(cur, u, pf, qty=2); od = _mk_order(cur, u, pf, pos, side="buy")
    _commit_err(cur, _args(u, pf, pos, od, side="buy", qty=2), "side_mismatch")
    _assert_clean(cur, pf, pos, od, 10000.0)


def test_reject_fill_qty_mismatch(conn):
    cur = conn.cursor(); u = str(uuid.uuid4())
    pf = _mk_portfolio(cur, u); pos = _mk_position(cur, u, pf, qty=2); od = _mk_order(cur, u, pf, pos)
    _commit_err(cur, _args(u, pf, pos, od, qty=5), "fill_qty_mismatch")
    _assert_clean(cur, pf, pos, od, 10000.0)


def test_reject_order_position_linkage_mismatch(conn):
    """An order not linked to the target position => reject."""
    cur = conn.cursor(); u = str(uuid.uuid4())
    pf = _mk_portfolio(cur, u); pos = _mk_position(cur, u, pf)
    other_pos = _mk_position(cur, u, pf, symbol="SPY")
    od = _mk_order(cur, u, pf, other_pos)  # linked to a DIFFERENT position
    _commit_err(cur, _args(u, pf, pos, od), "order_position_linkage_mismatch")
    _assert_clean(cur, pf, pos, od, 10000.0)


def test_reject_ownership_mismatch(conn):
    cur = conn.cursor(); u = str(uuid.uuid4()); other = str(uuid.uuid4())
    pf = _mk_portfolio(cur, u); pos = _mk_position(cur, u, pf); od = _mk_order(cur, u, pf, pos)
    _commit_err(cur, _args(other, pf, pos, od), "ownership_mismatch")
    _assert_clean(cur, pf, pos, od, 10000.0)


# ─────────────────── CAS race / already-closed conflict ──────────────────────
def test_cas_race_position_already_closed(conn):
    """A close against an already-closed position is a typed conflict, no
    writes (the exact orphan/double-book race the function kills)."""
    cur = conn.cursor(); u = str(uuid.uuid4())
    pf = _mk_portfolio(cur, u)
    pos = _mk_position(cur, u, pf, qty=2, status="closed", realized=10.0,
                       reason="stop_loss_hit", source="exit_evaluator",
                       closed_at="2026-07-19T00:00:00+00")
    od = _mk_order(cur, u, pf, pos)
    _commit_err(cur, _args(u, pf, pos, od), "position_already_closed")
    # order untouched, no ledger, cash unmoved
    assert float(_scalar(cur, "select cash_balance from paper_portfolios where id=%s", (pf,))) == 10000.0
    assert _row_json(cur, "paper_orders", od)["status"] == "submitted"
    assert int(_scalar(cur, "select count(*) from paper_ledger where order_id=%s", (od,))) == 0


# ─────────────── mid-write DB failures => full rollback (all-or-none) ─────────
@pytest.mark.parametrize("inject_table", ["paper_orders", "paper_portfolios",
                                          "paper_ledger", "paper_positions"])
def test_midwrite_failure_rolls_back_everything(conn, inject_table):
    """Inject a raise at each write site in turn. Whichever write fails, the
    WHOLE economic commit rolls back: order not filled, cash unmoved, no ledger
    row, position still open. Injecting at paper_positions (the LAST write) is
    the strongest: order+cash+ledger were already written in-txn, then the
    position close raises => every prior write is undone."""
    cur = conn.cursor(); u = str(uuid.uuid4())
    pf = _mk_portfolio(cur, u, cash=10000)
    pos = _mk_position(cur, u, pf, qty=2)
    od = _mk_order(cur, u, pf, pos)
    _install_injector(cur, inject_table)
    _commit_err(cur, _args(u, pf, pos, od), "wt17_injected_failure")
    cur.execute(f"drop trigger if exists wt17_inject on {inject_table}")
    _assert_clean(cur, pf, pos, od, 10000.0)


def test_rollback_leaves_byte_identical_rows(conn):
    """Capture every column of order/position/portfolio, force a failure at the
    deepest write, and assert the rows are byte-identical afterwards + no ledger
    row appeared."""
    cur = conn.cursor(); u = str(uuid.uuid4())
    pf = _mk_portfolio(cur, u); pos = _mk_position(cur, u, pf, qty=2); od = _mk_order(cur, u, pf, pos)
    before = (_row_json(cur, "paper_orders", od),
              _row_json(cur, "paper_positions", pos),
              _row_json(cur, "paper_portfolios", pf))
    _install_injector(cur, "paper_positions")
    _commit_err(cur, _args(u, pf, pos, od), "wt17_injected_failure")
    cur.execute("drop trigger if exists wt17_inject on paper_positions")
    after = (_row_json(cur, "paper_orders", od),
             _row_json(cur, "paper_positions", pos),
             _row_json(cur, "paper_portfolios", pf))
    assert before == after
    assert int(_scalar(cur, "select count(*) from paper_ledger", ())) == 0


# ─────────────────────────── idempotency ─────────────────────────────────────
def test_idempotent_replay_same_key_no_duplicate(conn):
    cur = conn.cursor(); u = str(uuid.uuid4())
    pf = _mk_portfolio(cur, u); pos = _mk_position(cur, u, pf, qty=2); od = _mk_order(cur, u, pf, pos)
    r1 = _commit(cur, _args(u, pf, pos, od, key="kX"))
    r2 = _commit(cur, _args(u, pf, pos, od, key="kX"))
    assert r1["idempotent_replay"] is False and r2["idempotent_replay"] is True
    assert r1["ledger_event_id"] == r2["ledger_event_id"]
    assert int(_scalar(cur, "select count(*) from paper_ledger where order_id=%s", (od,))) == 1
    # cash moved exactly once
    assert float(_scalar(cur, "select cash_balance from paper_portfolios where id=%s", (pf,))) == 10400.0


def test_conflicting_idempotency_key_rejected(conn):
    cur = conn.cursor(); u = str(uuid.uuid4())
    pf = _mk_portfolio(cur, u); pos = _mk_position(cur, u, pf, qty=2); od = _mk_order(cur, u, pf, pos)
    _commit(cur, _args(u, pf, pos, od, key="first"))
    _commit_err(cur, _args(u, pf, pos, od, key="second"), "idempotency_conflict")
    # still exactly one commit's effects
    assert int(_scalar(cur, "select count(*) from paper_ledger where order_id=%s", (od,))) == 1
    assert float(_scalar(cur, "select cash_balance from paper_portfolios where id=%s", (pf,))) == 10400.0


def test_duplicate_fill_ledger_guarded(conn):
    """A pre-existing 'fill' ledger row for the order (e.g. an orphan from the
    old non-atomic path) blocks the commit under the lock — no double cash."""
    cur = conn.cursor(); u = str(uuid.uuid4())
    pf = _mk_portfolio(cur, u); pos = _mk_position(cur, u, pf, qty=2); od = _mk_order(cur, u, pf, pos)
    cur.execute(
        "insert into paper_ledger (user_id,portfolio_id,order_id,position_id,"
        "event_type,amount,balance_after) values (%s,%s,%s,%s,'fill',1,1)",
        (u, pf, od, pos),
    )
    _commit_err(cur, _args(u, pf, pos, od), "duplicate_fill_ledger")
    # zero NEW writes: cash unmoved, order still submitted/uncommitted, position
    # open, and the fill-ledger count is exactly the one pre-seeded row (no dup).
    assert float(_scalar(cur, "select cash_balance from paper_portfolios where id=%s", (pf,))) == 10000.0
    o = _row_json(cur, "paper_orders", od)
    assert o["status"] == "submitted" and o["internal_close_committed_at"] is None
    assert _row_json(cur, "paper_positions", pos)["status"] == "open"
    assert int(_scalar(cur, "select count(*) from paper_ledger where order_id=%s and event_type='fill'", (od,))) == 1


# ─────────────────────── concurrency: one winner, one conflict ───────────────
def test_two_concurrent_closes_one_winner_one_conflict(conn):
    """Two close orders race the SAME open position from two connections. The
    position FOR UPDATE lock serializes them: exactly one commits, the other
    gets position_already_closed. Exactly one cash move, exactly one ledger
    fill, position closed once, loser's order untouched."""
    import pg8000.dbapi as db

    cur = conn.cursor(); u = str(uuid.uuid4())
    pf = _mk_portfolio(cur, u, cash=10000)
    pos = _mk_position(cur, u, pf, qty=3, entry=1.00)
    od_a = _mk_order(cur, u, pf, pos)
    od_b = _mk_order(cur, u, pf, pos)

    barrier = threading.Barrier(2)
    results = {}

    def _attempt(name, od, key):
        c = db.connect(**_DSN); c.autocommit = True
        cc = c.cursor()
        barrier.wait()
        try:
            cc.execute(_CALL, _args(u, pf, pos, od, key=key, side="sell", qty=3,
                                    mag=2.00, realized=25.0))
            results[name] = ("ok", _decode(cc.fetchone()[0]))
        except Exception as e:  # noqa: BLE001
            results[name] = ("err", str(e))
        finally:
            cc.close(); c.close()

    ta = threading.Thread(target=_attempt, args=("A", od_a, "kA"))
    tb = threading.Thread(target=_attempt, args=("B", od_b, "kB"))
    ta.start(); tb.start(); ta.join(); tb.join()

    kinds = sorted(v[0] for v in results.values())
    assert kinds == ["err", "ok"], results
    err_msg = [v[1] for v in results.values() if v[0] == "err"][0]
    assert "position_already_closed" in err_msg

    # exactly one economic effect survived
    assert int(_scalar(cur, "select count(*) from paper_ledger where event_type='fill'", ())) == 1
    assert float(_scalar(cur, "select cash_balance from paper_portfolios where id=%s", (pf,))) == 10600.0  # +3*2*100
    assert int(_scalar(cur, "select count(*) from paper_positions where id=%s and status='closed'", (pos,))) == 1
    filled = int(_scalar(cur, "select count(*) from paper_orders where position_id=%s and status='filled'", (pos,)))
    submitted = int(_scalar(cur, "select count(*) from paper_orders where position_id=%s and status='submitted'", (pos,)))
    assert filled == 1 and submitted == 1  # winner filled, loser untouched


# ─────────────────── no broker / live-path mutation ─────────────────────────
def test_no_broker_or_live_path_mutation(conn):
    """The internal-close commit must not touch broker/live provenance columns
    nor the portfolio routing_mode."""
    cur = conn.cursor(); u = str(uuid.uuid4())
    pf = _mk_portfolio(cur, u, routing="shadow_only")
    pos = _mk_position(cur, u, pf, qty=2)
    od = _mk_order(cur, u, pf, pos, execution_mode="internal_paper")
    _commit(cur, _args(u, pf, pos, od))
    o = _row_json(cur, "paper_orders", od)
    assert o["execution_mode"] == "internal_paper"
    assert o["alpaca_order_id"] is None
    assert o["broker_status"] is None
    assert o["broker_response"] is None
    assert _row_json(cur, "paper_portfolios", pf)["routing_mode"] == "shadow_only"
    # no extra rows manufactured
    assert int(_scalar(cur, "select count(*) from paper_orders", ())) == 1
    assert int(_scalar(cur, "select count(*) from paper_positions", ())) == 1
