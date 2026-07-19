"""Mirror parity — shadow_fleet_activation registration/registry validation
↔ the activation RPC's SQL validation (50 / unique / non-blank / approved /
epoch).

Two mirrors meet here:

  A. STRUCTURAL registration validation. The RPC
     (rpc_shadow_fleet_activate, 20260717090000) validates the operator's
     ``p_policy_registrations`` jsonb with five ordered clauses:
        1. NULL / non-object                              → missing
        2. exactly 50 entries                             → missing
        3. every key ~ '^[0-9]+$' AND 1..50               → missing
        4. no NULL/blank value                            → missing
        5. 50 DISTINCT btrim(value)                       → duplicate
     ``shadow_fleet_activation._validate_policy_registrations`` is the Python
     mirror the /tasks route runs BEFORE the RPC. This test drives a shared
     fixture table through the REAL Python validator AND a faithful Python
     mirror of the SQL clauses (drift-locked to the RPC TEXT) and asserts they
     return the SAME verdict class (missing | duplicate | ok) on the same
     wire-shape input.

  B. APPROVED / EPOCH gate. The RPC has NO FK to policy_registrations (by
     design), so the approved+epoch check is the Python-side
     ``_validate_registry_approvals`` reading the registry the seed populates
     (packages/quantum/policy_lab/fleet_policy_design). This test proves the
     Python gate ACCEPTS exactly what the seed emits (approval_status
     'approved', effective_epoch 'small_tier_v1') and rejects a mutated status.

Failure injected at the ORIGIN (the input map / the registry rows); verdict
asserted at the TOP (the outcome constant). No live DB.
"""

import re
from pathlib import Path

import pytest

from packages.quantum.policy_lab import fleet_policy_design as design
from packages.quantum.policy_lab.shadow_fleet import (
    FLEET_EPOCH,
    MICRO_ACCOUNT_COUNT,
)
from packages.quantum.services import shadow_fleet_activation as sfa

RPC_MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "supabase" / "migrations"
    / "20260717090000_shadow_fleet_activation_rpc.sql"
)


def _rpc_sql() -> str:
    return RPC_MIGRATION.read_text(encoding="utf-8")


# ── Faithful Python mirror of the RPC's jsonb registration clauses ──────────
# Kept 1:1 with the SQL (the drift-lock class below pins the SQL text so this
# mirror can never silently diverge). Operates on the WIRE shape the RPC sees:
# a jsonb object == a dict of string keys -> string values (jsonb_each_text).
def _sql_registration_verdict(reg):
    """Return 'missing' | 'duplicate' | None, mirroring the RPC's five
    ordered validation clauses over p_policy_registrations."""
    # clause 1 — NULL / non-object
    if reg is None or not isinstance(reg, dict):
        return "missing"
    items = list(reg.items())
    # clause 2 — exactly 50 entries (jsonb keys are unique by construction)
    if len(items) != MICRO_ACCOUNT_COUNT:
        return "missing"
    # clause 3 — every key ~ '^[0-9]+$' AND (key)::int BETWEEN 1 AND 50
    good_keys = sum(
        1 for k, _ in items
        if re.fullmatch(r"[0-9]+", str(k)) and 1 <= int(k) <= MICRO_ACCOUNT_COUNT
    )
    if good_keys != MICRO_ACCOUNT_COUNT:
        return "missing"
    # clause 4 — no NULL/blank value
    blank = sum(1 for _, v in items if v is None or str(v).strip() == "")
    if blank > 0:
        return "missing"
    # clause 5 — 50 DISTINCT btrim(value)
    distinct = len({str(v).strip() for _, v in items})
    if distinct != MICRO_ACCOUNT_COUNT:
        return "duplicate"
    return None


def _python_verdict_class(reg):
    """Collapse the service validator's typed outcome to the SQL's 3-class."""
    outcome, _normalized, _detail = sfa._validate_policy_registrations(reg)
    if outcome is None:
        return None
    if outcome == sfa.POLICY_REGISTRATION_DUPLICATE:
        return "duplicate"
    if outcome == sfa.POLICY_REGISTRATION_MISSING:
        return "missing"
    raise AssertionError(f"unexpected registration outcome {outcome!r}")


def _valid_map():
    """The wire shape the RPC receives: {"1".."50": unique id}."""
    return {str(s): f"pol-{s:02d}" for s in range(1, MICRO_ACCOUNT_COUNT + 1)}


# Shared fixture table: (description, wire-shape map). Both mirrors must agree.
_FIXTURES = []


def _fx(desc, mutate):
    m = _valid_map()
    mutate(m)
    _FIXTURES.append((desc, m))


_FIXTURES.append(("valid_50_unique", _valid_map()))
_fx("forty_nine_entries", lambda m: m.pop("50"))
_fx("blank_value", lambda m: m.__setitem__("7", ""))
_fx("whitespace_only_value", lambda m: m.__setitem__("7", "   "))
_fx("duplicate_policy_id", lambda m: m.__setitem__("50", m["1"]))
_fx("bad_slot_key_zero", lambda m: (m.pop("50"), m.__setitem__("0", "pol-00")))
_fx("bad_slot_key_out_of_range",
    lambda m: (m.pop("50"), m.__setitem__("51", "pol-51")))
_fx("non_numeric_slot_key",
    lambda m: (m.pop("50"), m.__setitem__("abc", "pol-xx")))
# 51 entries: slot 51 is out of range → structural miss on both sides.
_fx("fifty_one_entries", lambda m: m.__setitem__("51", "pol-51"))


class TestStructuralRegistrationParity:
    @pytest.mark.parametrize("desc,reg", _FIXTURES, ids=[d for d, _ in _FIXTURES])
    def test_python_and_sql_mirror_agree(self, desc, reg):
        py = _python_verdict_class(reg)
        sql = _sql_registration_verdict(reg)
        assert py == sql, f"{desc}: python={py!r} sql={sql!r}"

    def test_valid_map_accepted_both_sides(self):
        reg = _valid_map()
        assert _python_verdict_class(reg) is None
        assert _sql_registration_verdict(reg) is None

    def test_empty_and_none_are_missing_both_sides(self):
        for reg in ({}, None):
            assert _python_verdict_class(reg) == "missing"
            assert _sql_registration_verdict(reg) == "missing"

    def test_duplicate_is_distinct_from_missing(self):
        # The two classes must not be conflated — a duplicate id is 'duplicate',
        # not 'missing', on both sides (the RPC raises a different message).
        dup = _valid_map()
        dup["50"] = dup["1"]
        assert _python_verdict_class(dup) == "duplicate"
        assert _sql_registration_verdict(dup) == "duplicate"


# ── Drift-lock: the RPC TEXT still carries every clause the mirror encodes ───
class TestRpcTextPinsTheClauses:
    def test_null_or_nonobject_clause(self):
        assert "jsonb_typeof(p_policy_registrations) <> 'object'" in _rpc_sql()

    def test_count_fifty_clause(self):
        sql = _rpc_sql()
        assert "jsonb_each_text(p_policy_registrations)" in sql
        assert "v_count <> 50" in sql

    def test_slot_key_regex_and_range_clause(self):
        sql = _rpc_sql()
        assert "r.key ~ '^[0-9]+$'" in sql
        assert "(r.key)::int BETWEEN 1 AND 50" in sql

    def test_blank_value_clause(self):
        assert "r.value IS NULL OR btrim(r.value) = ''" in _rpc_sql()

    def test_distinct_value_clause(self):
        assert "COUNT(DISTINCT btrim(r.value))" in _rpc_sql()


# ── Approved / epoch gate ↔ the seed the design module emits ────────────────
class _RegistryQuery:
    def __init__(self, rows):
        self._rows = rows
        self._filters = []

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self._filters.append(("eq", col, val))
        return self

    def in_(self, col, vals):
        self._filters.append(("in", col, list(vals)))
        return self

    def execute(self):
        rows = list(self._rows)
        for kind, col, val in self._filters:
            if kind == "eq":
                rows = [r for r in rows if r.get(col) == val]
            elif kind == "in":
                rows = [r for r in rows if r.get(col) in val]

        class _R:
            def __init__(self, data):
                self.data = data
        return _R(rows)


class _RegistryFake:
    def __init__(self, rows):
        self._rows = rows

    def table(self, _name):
        return _RegistryQuery(self._rows)


def _seed_registry_rows():
    """The exact rows the seed (fleet_policy_design) would insert: id +
    approval_status + effective_epoch."""
    return [
        {"policy_registration_id": r["policy_registration_id"],
         "approval_status": r["approval_status"],
         "effective_epoch": r["effective_epoch"]}
        for r in design.build_registrations()
    ]


class TestRegistryApprovalParityWithSeed:
    def test_constants_match_the_seed_literals(self):
        # The Python gate's approved/epoch constants ARE what the seed emits.
        assert sfa.APPROVED_STATUS == "approved"
        assert FLEET_EPOCH == design.EFFECTIVE_EPOCH == "small_tier_v1"
        rows = _seed_registry_rows()
        assert all(r["approval_status"] == "approved" for r in rows)
        assert all(r["effective_epoch"] == "small_tier_v1" for r in rows)

    def test_gate_accepts_exactly_the_seed(self):
        rows = _seed_registry_rows()
        ids = [r["policy_registration_id"] for r in rows]
        outcome, detail = sfa._validate_registry_approvals(
            _RegistryFake(rows), ids, FLEET_EPOCH)
        assert outcome is None  # every seed id is approved for the epoch
        assert detail["registry_approved_count"] == len(ids)

    def test_gate_rejects_a_mutated_status(self):
        rows = _seed_registry_rows()
        rows[0]["approval_status"] = "draft"   # a non-approved seed row
        ids = [r["policy_registration_id"] for r in rows]
        outcome, detail = sfa._validate_registry_approvals(
            _RegistryFake(rows), ids, FLEET_EPOCH)
        assert outcome == sfa.POLICY_NOT_APPROVED
        assert detail["unapproved_count"] == 1

    def test_gate_rejects_wrong_epoch(self):
        rows = _seed_registry_rows()
        ids = [r["policy_registration_id"] for r in rows]
        outcome, _detail = sfa._validate_registry_approvals(
            _RegistryFake(rows), ids, "some_other_epoch")
        assert outcome == sfa.POLICY_NOT_REGISTERED

    def test_registry_read_failure_is_schema_unavailable(self):
        class _Boom:
            def table(self, _n):
                raise RuntimeError("registry down")
        outcome, _detail = sfa._validate_registry_approvals(
            _Boom(), ["pol-01"], FLEET_EPOCH)
        assert outcome == sfa.SCHEMA_UNAVAILABLE  # a failed read is never ready


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
