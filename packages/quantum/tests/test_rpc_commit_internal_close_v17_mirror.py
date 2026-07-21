"""CI-green mirror suite for the v1.7 guard-hardening of
rpc_commit_internal_close_v1 (migration
20260720120000_rpc_commit_internal_close_v1_guard_hardening.sql).

MIRROR-ONLY (no live-pg dependency; runs in CI, which provisions no Postgres).
It provides the same two proofs the base mirror does, focused on the two v1.7
follow-ups:

  A. STRUCTURAL / SECURITY drift-lock against the NEW migration SQL TEXT — it is
     an ADDITIVE `CREATE OR REPLACE FUNCTION` only (no table/column/index/DML
     churn), preserves the fixed search_path + operator-only grant surface + the
     14-arg signature + the three locks + the canonical enums, adds the explicit
     `routing_mode = 'live_eligible'` reject ABOVE the fail-safe allowlist, and
     extends the non-finite guard to p_fill_mid_reference.

  B. DECISION-LOGIC mirror — the routing accept/reject is UNCHANGED (shadow_only
     commits; live_eligible AND any future third mode reject), and the extended
     non-finite guard rejects a NaN/±Inf provenance while a NULL/finite
     provenance still passes.

The AUTHORITATIVE atomicity/rollback/round-trip behaviour is proven against real
Postgres in tests/pg/test_rpc_commit_internal_close_v17_pg.py; a mirror cannot
prove transactional rollback and does not claim to.
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
    / "20260720120000_rpc_commit_internal_close_v1_guard_hardening.sql"
)

_SIG14 = ("uuid, uuid, uuid, uuid, text, text, text, text, "
          "numeric, numeric, numeric, numeric, text, numeric")


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def _sql_no_comments() -> str:
    """Migration SQL with ``--`` comments stripped but string LITERALS preserved
    (so ordering checks that must distinguish 'live_eligible' from 'shadow_only'
    inspect executable code only, never the header/inline prose that names both)."""
    out = []
    for line in _sql().splitlines():
        i = line.find("--")
        out.append(line if i == -1 else line[:i])
    return "\n".join(out)


def _sql_code() -> str:
    """Migration SQL with ``--`` comments AND single-quoted literals blanked, so
    structural checks inspect executable code only."""
    return re.sub(r"'[^']*'", "''", _sql_no_comments())


# ══════════════════════════════════════════════════════════════════════════
# A. Structural / security drift-lock
# ══════════════════════════════════════════════════════════════════════════
def test_migration_present():
    assert MIGRATION.exists(), MIGRATION


def test_is_additive_create_or_replace_only():
    """The migration REPLACES the function body ONLY — no table/column/index
    creation and no business-row rewrite (additive function replacement)."""
    code = _sql_code()
    assert code.count("CREATE OR REPLACE FUNCTION rpc_commit_internal_close_v1(") == 1
    # no schema churn / no data migration outside the function body
    assert "ALTER TABLE" not in code
    assert "CREATE UNIQUE INDEX" not in code
    assert "CREATE INDEX" not in code
    assert "DROP " not in code
    assert "TRUNCATE" not in code
    # the only DML tokens present are INSIDE the function body (the fill/close
    # writes v1 already performs); none appear as a top-level backfill. Assert
    # there is no standalone UPDATE/INSERT/DELETE before the function is defined.
    head = code[: code.index("CREATE OR REPLACE FUNCTION")]
    for kw in ("UPDATE ", "INSERT ", "DELETE "):
        assert kw not in head.upper()


def test_signature_and_grant_surface_preserved():
    s = _sql()
    # 14-arg signature appears exactly 3x: COMMENT + REVOKE + GRANT
    assert s.count(_SIG14) == 3
    assert re.search(r"REVOKE ALL ON FUNCTION rpc_commit_internal_close_v1\(", s)
    assert "FROM PUBLIC, anon, authenticated" in s
    assert re.search(r"GRANT EXECUTE ON FUNCTION rpc_commit_internal_close_v1\([^)]*\)\s*TO service_role", s)


def test_fixed_safe_search_path_preserved():
    assert "SET search_path = public, pg_temp" in _sql()


def test_three_row_locks_preserved():
    assert _sql_code().count("FOR UPDATE") == 3


def test_no_dynamic_sql_or_autonomous_subtxn():
    s = _sql_code().lower()
    for bad in ("dblink", "pg_background", "autonomous", "execute format(", "execute '", "commit;"):
        assert bad not in s
    assert "\nbegin;" not in s


def test_enums_verbatim_and_canonical():
    s = _sql()
    for r in _VALID_CLOSE_REASONS:
        assert f"'{r}'" in s
    for src in _VALID_FILL_SOURCES:
        assert f"'{src}'" in s


# ── FOLLOW-UP 1 drift-lock: explicit live_eligible ABOVE the fail-safe allowlist
def test_explicit_live_eligible_reject_above_allowlist():
    s = _sql()
    assert "routing_mode = 'live_eligible'" in s              # explicit deliberate branch
    assert "routing_mode IS DISTINCT FROM 'shadow_only'" in s  # authoritative allowlist KEPT
    # ordering: the explicit live_eligible branch precedes the allowlist catch-all
    # — checked on comment-stripped CODE (the header prose names both strings).
    code = _sql_no_comments()
    assert code.index("routing_mode = 'live_eligible'") < code.index("routing_mode IS DISTINCT FROM 'shadow_only'")
    # three live_order_forbidden RAISEs now: execution_mode + live_eligible + allowlist
    assert _sql_no_comments().count("live_order_forbidden") == 3


# ── FOLLOW-UP 2 drift-lock: non-finite guard extended to the provenance param ─
def test_non_finite_guard_covers_all_five_numerics():
    s = _sql()
    for p in ("p_fill_price_magnitude", "p_multiplier", "p_fill_qty",
              "p_realized_pl", "p_fill_mid_reference"):
        assert re.search(
            rf"{p}\s+IN \('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric\)", s
        ), p
    assert "non_finite_input" in s


# ══════════════════════════════════════════════════════════════════════════
# B. Decision-logic mirror (1:1 with the plpgsql guard order, v1.7)
# ══════════════════════════════════════════════════════════════════════════
_SQL_CLOSE_REASONS = frozenset(_VALID_CLOSE_REASONS)
_SQL_FILL_SOURCES = frozenset(_VALID_FILL_SOURCES)


def mirror_classify(*, position, order, req, routing_mode="shadow_only") -> str:
    for k in ("user_id", "portfolio_id", "position_id", "close_order_id"):
        if req.get(k) is None:
            return "identifying_ids_required"
    if not (req.get("idempotency_key") or "").strip():
        return "idempotency_key_required"
    if req.get("realized_pl") is None:
        return "realized_pl_required"
    # (FIX 2 + v1.7 FOLLOW-UP 2) non-finite guard now covers p_fill_mid_reference,
    # NULL-safely (a None provenance is NOT rejected).
    for k in ("fill_price_magnitude", "multiplier", "fill_qty", "realized_pl", "fill_mid_reference"):
        v = req.get(k)
        if isinstance(v, (int, float)) and not math.isfinite(v):
            return "non_finite_input"
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
    if position["user_id"] != req["user_id"] or position["portfolio_id"] != req["portfolio_id"]:
        return "position_ownership_mismatch"
    if order["user_id"] != req["user_id"] or order["portfolio_id"] != req["portfolio_id"]:
        return "order_ownership_mismatch"
    if order["position_id"] != req["position_id"]:
        return "order_position_linkage_mismatch"
    # (FIX 1 + v1.7 FOLLOW-UP 1) live isolation: alpaca_live order OR any
    # non-shadow book rejects. The allowlist is authoritative; the explicit
    # live_eligible branch only sharpens the error, not the outcome.
    if order.get("execution_mode") == "alpaca_live":
        return "live_order_forbidden"
    if routing_mode != "shadow_only":
        return "live_order_forbidden"
    if order.get("internal_close_committed_at") is not None:
        if order.get("internal_close_commit_key") == req["idempotency_key"]:
            return "idempotent_replay"
        return "idempotency_conflict"
    if position["status"] == "closed":
        return "position_already_closed"
    if position["status"] != "open":
        return "position_not_open"
    if position["quantity"] == 0:
        return "position_zero_quantity"
    expected_side = "sell" if position["quantity"] > 0 else "buy"
    if req["close_side"] != expected_side:
        return "side_mismatch"
    if req["fill_qty"] != abs(position["quantity"]):
        return "fill_qty_mismatch"
    return "commit"


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


# ── FOLLOW-UP 1: routing accept/reject unchanged, third mode fails SAFE ───────
@pytest.mark.parametrize("routing,expected", [
    ("shadow_only", "commit"),
    ("live_eligible", "live_order_forbidden"),
    ("paper_shadow", "live_order_forbidden"),   # future third mode => fail-safe reject
    ("something_new", "live_order_forbidden"),
    (None, "live_order_forbidden"),
])
def test_mirror_routing_accept_reject(routing, expected):
    assert mirror_classify(position=_pos(qty=2), order=_ord(), req=_req(),
                           routing_mode=routing) == expected


def test_mirror_alpaca_live_execution_mode_still_forbidden():
    assert mirror_classify(position=_pos(qty=2),
                           order=_ord(execution_mode="alpaca_live"),
                           req=_req()) == "live_order_forbidden"


# ── FOLLOW-UP 2: provenance non-finite rejected; NULL/finite pass ─────────────
@pytest.mark.parametrize("badval", [float("nan"), float("inf"), float("-inf")])
def test_mirror_non_finite_provenance_rejected(badval):
    assert mirror_classify(position=_pos(qty=2), order=_ord(),
                           req=_req(fill_mid_reference=badval)) == "non_finite_input"


@pytest.mark.parametrize("goodval", [None, 1.87, 0.0, -0.5])
def test_mirror_null_or_finite_provenance_passes(goodval):
    # NULL is designed-valid; a finite reference (incl. 0 / negative) is not a
    # non-finite value and must not trip the guard — the close commits.
    assert mirror_classify(position=_pos(qty=2), order=_ord(),
                           req=_req(fill_mid_reference=goodval)) == "commit"


# ── the four original cash-math non-finite guards are unchanged ───────────────
@pytest.mark.parametrize("field", ["fill_price_magnitude", "multiplier", "fill_qty", "realized_pl"])
@pytest.mark.parametrize("badval", [float("nan"), float("inf"), float("-inf")])
def test_mirror_cash_math_non_finite_still_rejected(field, badval):
    assert mirror_classify(position=_pos(qty=2), order=_ord(),
                           req=_req(**{field: badval})) == "non_finite_input"
