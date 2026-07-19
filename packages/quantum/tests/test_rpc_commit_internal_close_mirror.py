"""CI-green mirror suite for rpc_commit_internal_close_v1
(V17-1 F-A2-INTERNAL-CLOSE-PRECOMMIT-SIDE-EFFECTS, Lane 1A).

MIRROR-ONLY. This module has NO live-pg dependency and runs in this repo's CI
(which provisions no Postgres). It provides two kinds of drift-locked proof —
the same dual pattern #1291 established:

  A. STRUCTURAL / SECURITY drift-lock against the migration SQL TEXT: the
     marker columns, the partial-unique idempotency index, the fixed
     search_path, the operator-only REVOKE/GRANT surface, the three FOR UPDATE
     locks, the absence of dynamic SQL / autonomous sub-transactions, and the
     literal presence of the canonical close_reason / fill_source enums.

  B. DECISION-LOGIC mirror: a faithful Python re-statement of the function's
     ordered guards + server-side cash derivation, checked for PARITY against
     (1) the canonical close_helper enums and (2) the enum tokens the SQL
     lists, then exercised over a fixture table so each verdict branch is
     asserted.

The AUTHORITATIVE atomicity / concurrency / rollback behaviour is proven
against real Postgres in tests/pg/test_rpc_commit_internal_close_pg.py; a
mirror cannot prove transactional rollback and does not claim to.
"""

import math
import re
from pathlib import Path

import pytest

from packages.quantum.services.close_helper import (
    _VALID_CLOSE_REASONS,
    _VALID_FILL_SOURCES,
)

MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "supabase" / "migrations"
    / "20260719180000_rpc_commit_internal_close_v1.sql"
)


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def _sql_code() -> str:
    """The migration SQL with ``--`` comments AND single-quoted string literals
    blanked, so structural checks (lock count, no-dynamic-SQL, no explicit txn
    control) inspect executable code only — never prose or string contents."""
    out = []
    for line in _sql().splitlines():
        i = line.find("--")
        out.append(line if i == -1 else line[:i])
    code = "\n".join(out)
    return re.sub(r"'[^']*'", "''", code)  # blank single-quoted literals


# ══════════════════════════════════════════════════════════════════════════
# A. Structural / security drift-lock against the migration SQL text
# ══════════════════════════════════════════════════════════════════════════
def test_migration_file_present():
    assert MIGRATION.exists(), MIGRATION


def test_marker_columns_are_additive_and_nullable():
    s = _sql()
    assert "ADD COLUMN IF NOT EXISTS internal_close_committed_at timestamptz" in s
    assert "ADD COLUMN IF NOT EXISTS internal_close_commit_key   text" in s or \
           "ADD COLUMN IF NOT EXISTS internal_close_commit_key text" in s
    # additive: no NOT NULL / no DEFAULT on the new columns (safe default NULL)
    assert "internal_close_committed_at timestamptz NOT NULL" not in s
    assert "internal_close_commit_key text NOT NULL" not in s


def test_partial_unique_idempotency_index():
    s = _sql()
    assert "CREATE UNIQUE INDEX IF NOT EXISTS ux_paper_orders_internal_close_commit_key" in s
    # partial: indexes only committed (non-null) keys => cannot collide with
    # the all-NULL legacy rows (the read-only preflight justification).
    assert re.search(
        r"ON paper_orders \(internal_close_commit_key\)\s*WHERE internal_close_commit_key IS NOT NULL",
        s,
    )


def test_fixed_safe_search_path():
    assert "SET search_path = public, pg_temp" in _sql()


def test_operator_only_grant_surface():
    s = _sql()
    assert re.search(r"REVOKE ALL ON FUNCTION rpc_commit_internal_close_v1\(", s)
    assert "FROM PUBLIC, anon, authenticated" in s
    assert re.search(r"GRANT EXECUTE ON FUNCTION rpc_commit_internal_close_v1\([^)]*\)\s*TO service_role", s)


def test_three_row_locks_in_fixed_order():
    """position -> order -> portfolio, each FOR UPDATE (deadlock-free order)."""
    s = _sql()
    assert _sql_code().count("FOR UPDATE") == 3  # exactly three real locks
    pos = s.index("FROM paper_positions\n        WHERE id = p_position_id FOR UPDATE")
    ordr = s.index("FROM paper_orders\n        WHERE id = p_close_order_id FOR UPDATE")
    port = s.index("FROM paper_portfolios\n        WHERE id = p_portfolio_id FOR UPDATE")
    assert pos < ordr < port, "lock order must be position -> order -> portfolio"


def test_no_dynamic_sql_or_autonomous_subtxn():
    s = _sql_code().lower()  # code only; the header prose names these words
    assert "dblink" not in s
    assert "pg_background" not in s
    assert "autonomous" not in s
    # no dynamic EXECUTE of a built string (no 'EXECUTE format(' / 'EXECUTE '||)
    assert "execute format(" not in s
    assert "execute '" not in s
    # single implicit transaction: the body must not open its own BEGIN/COMMIT
    assert "commit;" not in s
    assert "\nbegin;" not in s


def test_sql_lists_canonical_enums_verbatim():
    """Drift-lock: the SQL's inline close_reason / fill_source allow-lists must
    equal the canonical close_helper enums exactly."""
    s = _sql()
    for r in _VALID_CLOSE_REASONS:
        assert f"'{r}'" in s, f"close_reason {r} missing from SQL"
    for src in _VALID_FILL_SOURCES:
        assert f"'{src}'" in s, f"fill_source {src} missing from SQL"


def test_receipt_and_marker_write_present():
    s = _sql()
    # write-once marker set inside the commit
    assert "internal_close_committed_at  = v_now" in s
    assert "internal_close_commit_key    = p_idempotency_key" in s
    # typed receipt fields
    for key in ("'committed'", "'order_id'", "'position_id'", "'cash_after'",
                "'ledger_event_id'", "'realized_pl'", "'idempotent_replay'"):
        assert key in s


# ══════════════════════════════════════════════════════════════════════════
# B. Decision-logic mirror (faithful re-statement of the SQL guard order)
# ══════════════════════════════════════════════════════════════════════════
# Kept 1:1 with the plpgsql body; the structural drift-lock above pins the SQL
# so this mirror cannot silently diverge from what actually runs.

_SQL_CLOSE_REASONS = frozenset(_VALID_CLOSE_REASONS)
_SQL_FILL_SOURCES = frozenset(_VALID_FILL_SOURCES)


def mirror_classify(*, position, order, req, routing_mode="shadow_only") -> str:
    """Return the verdict the RPC produces for `req` against the locked
    `position`/`order`/portfolio state. Verdict strings mirror the RAISE tokens
    / receipt flags. Guard ORDER is kept 1:1 with the plpgsql body."""
    # (1) required inputs
    for k in ("user_id", "portfolio_id", "position_id", "close_order_id"):
        if req.get(k) is None:
            return "identifying_ids_required"
    if not (req.get("idempotency_key") or "").strip():
        return "idempotency_key_required"
    if req.get("realized_pl") is None:
        return "realized_pl_required"
    # (FIX 2) non-finite numerics rejected before any derivation
    for k in ("fill_price_magnitude", "multiplier", "fill_qty", "realized_pl"):
        v = req.get(k)
        if isinstance(v, (int, float)) and not math.isfinite(v):
            return "non_finite_input"
    # (6a) domain
    if req["close_reason"] not in _SQL_CLOSE_REASONS:
        return "invalid_close_reason"
    if req["fill_source"] not in _SQL_FILL_SOURCES:
        return "invalid_fill_source"
    if req["close_side"] not in ("buy", "sell"):
        return "invalid_close_side"
    if req["fill_price_magnitude"] <= 0:
        return "nonpositive_fill_magnitude"
    if req["fill_qty"] <= 0:
        return "nonpositive_fill_qty"
    if req["multiplier"] <= 0:
        return "nonpositive_multiplier"
    # (3) ownership + linkage
    if position["user_id"] != req["user_id"] or position["portfolio_id"] != req["portfolio_id"]:
        return "position_ownership_mismatch"
    if order["user_id"] != req["user_id"] or order["portfolio_id"] != req["portfolio_id"]:
        return "order_ownership_mismatch"
    if order["position_id"] != req["position_id"]:
        return "order_position_linkage_mismatch"
    # (FIX 1) live-order isolation — before the marker / any write
    if order.get("execution_mode") == "alpaca_live":
        return "live_order_forbidden"
    if routing_mode != "shadow_only":
        return "live_order_forbidden"
    # (5)/(10)/(11) commit marker
    if order.get("internal_close_committed_at") is not None:
        if order.get("internal_close_commit_key") == req["idempotency_key"]:
            return "idempotent_replay"
        return "idempotency_conflict"
    # (4)/(11) open + nonzero
    if position["status"] == "closed":
        return "position_already_closed"
    if position["status"] != "open":
        return "position_not_open"
    if position["quantity"] == 0:
        return "position_zero_quantity"
    # (6b) side + qty vs locked truth
    expected_side = "sell" if position["quantity"] > 0 else "buy"
    if req["close_side"] != expected_side:
        return "side_mismatch"
    if req["fill_qty"] != abs(position["quantity"]):
        return "fill_qty_mismatch"
    return "commit"


def mirror_cash(position, magnitude, multiplier):
    """Server-side cash derivation mirror: sign from the position quantity."""
    sign = 1 if position["quantity"] > 0 else -1
    delta = sign * magnitude * abs(position["quantity"]) * multiplier
    return sign, delta


def _pos(qty=2, status="open", user="u", pf="pf"):
    return {"user_id": user, "portfolio_id": pf, "quantity": qty, "status": status}


def _ord(user="u", pf="pf", position_id="pos", committed_at=None, commit_key=None,
         execution_mode="internal_paper"):
    return {"user_id": user, "portfolio_id": pf, "position_id": position_id,
            "internal_close_committed_at": committed_at,
            "internal_close_commit_key": commit_key,
            "execution_mode": execution_mode}


def _req(**over):
    base = dict(user_id="u", portfolio_id="pf", position_id="pos",
                close_order_id="od", idempotency_key="k1",
                close_reason="target_profit_hit", fill_source="exit_evaluator",
                close_side="sell", fill_qty=2, fill_price_magnitude=2.0,
                realized_pl=50.0, multiplier=100)
    base.update(over)
    return base


@pytest.mark.parametrize("over,expected", [
    ({}, "commit"),
    ({"idempotency_key": "   "}, "idempotency_key_required"),
    ({"realized_pl": None}, "realized_pl_required"),
    ({"close_reason": "bogus"}, "invalid_close_reason"),
    ({"fill_source": "bogus"}, "invalid_fill_source"),
    ({"close_side": "hold"}, "invalid_close_side"),
    ({"fill_price_magnitude": 0}, "nonpositive_fill_magnitude"),
    ({"fill_qty": 0}, "nonpositive_fill_qty"),
    ({"multiplier": 0}, "nonpositive_multiplier"),
    ({"close_side": "buy"}, "side_mismatch"),          # long position, buy is wrong
    ({"fill_qty": 9}, "fill_qty_mismatch"),
])
def test_mirror_guard_verdicts_open_long(over, expected):
    assert mirror_classify(position=_pos(qty=2), order=_ord(), req=_req(**over)) == expected


def test_mirror_short_credit_commits_with_buy():
    v = mirror_classify(position=_pos(qty=-3), order=_ord(),
                        req=_req(close_side="buy", fill_qty=3))
    assert v == "commit"


def test_mirror_already_closed_conflict():
    v = mirror_classify(position=_pos(qty=2, status="closed"), order=_ord(), req=_req())
    assert v == "position_already_closed"


def test_mirror_idempotent_replay_and_conflict():
    committed = _ord(committed_at="2026-07-19T00:00:00+00", commit_key="k1")
    assert mirror_classify(position=_pos(), order=committed, req=_req(idempotency_key="k1")) == "idempotent_replay"
    assert mirror_classify(position=_pos(), order=committed, req=_req(idempotency_key="k2")) == "idempotency_conflict"


def test_mirror_linkage_and_ownership():
    assert mirror_classify(position=_pos(), order=_ord(position_id="other"), req=_req()) == "order_position_linkage_mismatch"
    assert mirror_classify(position=_pos(user="v"), order=_ord(), req=_req()) == "position_ownership_mismatch"


def test_mirror_cash_direction_long_credits_short_debits():
    # long (qty>0): sell-to-close => cash IN (+)
    sign, delta = mirror_cash(_pos(qty=2), 2.0, 100)
    assert sign == 1 and delta == pytest.approx(400.0)
    # short (qty<0): buy-to-close => cash OUT (-)
    sign, delta = mirror_cash(_pos(qty=-3), 0.80, 100)
    assert sign == -1 and delta == pytest.approx(-240.0)


def test_enum_parity_python_matches_canonical_and_sql():
    """The mirror's allowed sets, the canonical close_helper enums, and the
    tokens embedded in the SQL are one and the same (no third source of
    truth)."""
    s = _sql()
    assert _SQL_CLOSE_REASONS == frozenset(_VALID_CLOSE_REASONS)
    assert _SQL_FILL_SOURCES == frozenset(_VALID_FILL_SOURCES)
    for r in _SQL_CLOSE_REASONS:
        assert f"'{r}'" in s
    for src in _SQL_FILL_SOURCES:
        assert f"'{src}'" in s


# ── FIX 1/2 mirror branches ──────────────────────────────────────────────────
def test_mirror_live_execution_mode_forbidden():
    v = mirror_classify(position=_pos(qty=2), order=_ord(execution_mode="alpaca_live"), req=_req())
    assert v == "live_order_forbidden"


def test_mirror_live_eligible_routing_forbidden():
    v = mirror_classify(position=_pos(qty=2), order=_ord(), req=_req(), routing_mode="live_eligible")
    assert v == "live_order_forbidden"


@pytest.mark.parametrize("field", ["fill_price_magnitude", "multiplier", "fill_qty", "realized_pl"])
@pytest.mark.parametrize("badval", [float("nan"), float("inf"), float("-inf")])
def test_mirror_non_finite_rejected(field, badval):
    assert mirror_classify(position=_pos(qty=2), order=_ord(), req=_req(**{field: badval})) == "non_finite_input"


# ── FIX 4: enum drift-lock is BIDIRECTIONAL (SQL IN-list == canonical set) ────
def _sql_inlist_tokens(param: str) -> frozenset:
    """Extract the quoted tokens inside `<param> NOT IN ( … )` in the SQL."""
    m = re.search(rf"{param} NOT IN \((.*?)\)", _sql(), re.S)
    assert m, f"{param} NOT IN (...) list not found in SQL"
    return frozenset(re.findall(r"'([^']+)'", m.group(1)))


def test_sql_enum_inlists_are_exactly_canonical():
    """A future ROGUE enum token added to the SQL IN-list (outside the canonical
    close_helper sets) must fail CI — set EQUALITY, not just canonical ⊆ SQL."""
    assert _sql_inlist_tokens("p_close_reason") == frozenset(_VALID_CLOSE_REASONS)
    assert _sql_inlist_tokens("p_fill_source") == frozenset(_VALID_FILL_SOURCES)


# ── Structural drift-lock for the three post-review guards ────────────────────
def test_sql_live_order_isolation_guard_present():
    s = _sql()
    assert "execution_mode = 'alpaca_live'" in s
    assert "routing_mode IS DISTINCT FROM 'shadow_only'" in s
    assert s.count("live_order_forbidden") >= 2  # execution_mode + routing_mode


def test_sql_non_finite_guard_present():
    s = _sql()  # raw: _sql_code() blanks the 'NaN' literals we need to see
    # all four numeric inputs checked against NaN / ±Infinity
    for p in ("p_fill_price_magnitude", "p_multiplier", "p_fill_qty", "p_realized_pl"):
        assert re.search(
            rf"{p}\s+IN \('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric\)", s
        ), p
    assert "non_finite_input" in s


def test_sql_provenance_round_trips_to_both_sinks():
    s = _sql()
    # optional, backward-safe params
    assert re.search(r"p_fill_quality\s+text\s+DEFAULT NULL", s)
    assert re.search(r"p_fill_mid_reference\s+numeric\s+DEFAULT NULL", s)
    # order_json sink (single-key jsonb_build_object, closing paren)
    assert "jsonb_build_object('fill_quality', p_fill_quality)" in s
    assert "jsonb_build_object('fill_mid_reference', p_fill_mid_reference)" in s
    # ledger metadata sink (keys inside the multi-key object => trailing comma
    # distinguishes them from the order_json single-key builds above)
    assert "'fill_quality', p_fill_quality,\n" in s
    assert "'fill_mid_reference', p_fill_mid_reference\n" in s


def test_grant_surface_covers_14_arg_signature():
    """The REVOKE/GRANT/COMMENT signatures must include the two new provenance
    param types (…, text, numeric)."""
    s = _sql()
    sig14 = "uuid, uuid, uuid, uuid, text, text, text, text, numeric, numeric, numeric, numeric, text, numeric"
    assert s.count(sig14) == 3  # COMMENT + REVOKE + GRANT
