"""E19-2 — pre-rejection fork source + explicit EV basis + champion fence.
Adversarial-review corrections (2026-07-13/14): fork-result contract with
top-level failure propagation (B1), recoverable clone→verdict order with
repair (B2), verdict built from the PERSISTED clone (B3), genuine raw
eligibility gate (B4), honest execution-state semantics (B5A), versioned
clone identity with the verdict narrowing documented (B8), a DB-contract
fake enforcing the REAL unique indexes (B9, mirrored from live pg_indexes),
fail-closed clone lookup (B10), and a frozen-baseline champion fence running
the literal f34d5cd fork source (B11).
"""
import copy
import importlib.util
import json
import math
import os
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from packages.quantum.policy_lab import fork as fork_mod
from packages.quantum.policy_lab.config import PolicyConfig


# ---------------------------------------------------------------------------
# Hardened fake supabase (Blocker 9) — enforces the REAL deployed contract:
#   trade_suggestions: pkey uuid · UNIQUE(trace_id) WHERE NOT NULL ·
#     UNIQUE(user_id, window, cycle_date, ticker, strategy, legs_fingerprint)
#     WHERE status NOT IN ('dismissed','cancelled')   [unique_suggestion_per_cycle_v3]
#   policy_decisions: pkey uuid · UNIQUE(cohort_id, suggestion_id)
# UPSERT honours on_conflict (update-in-place); INSERT raises 'duplicate key
# value violates unique constraint …' exactly like PostgREST surfaces 23505.
# ---------------------------------------------------------------------------

_TS_NOT_NULL = ("user_id", "status")
_PD_NOT_NULL = ("cohort_id", "suggestion_id", "user_id", "decision")


class _Dup(Exception):
    pass


class _Q:
    def __init__(self, client, table):
        self._c = client
        self._t = table
        self._filters = []
        self._order = []
        self._op = None
        self._payload = None
        self._on_conflict = None
        self._limit = None
        self._single = False
        self._count = None
        self._select_cols = ""

    def select(self, *cols, **kw):
        self._op = self._op or "select"
        self._count = kw.get("count")
        self._select_cols = ",".join(str(c) for c in cols)
        return self

    def insert(self, rows):
        self._op, self._payload = "insert", rows
        return self

    def update(self, values):
        self._op, self._payload = "update", values
        return self

    def upsert(self, rows, on_conflict=None):
        self._op, self._payload, self._on_conflict = "upsert", rows, on_conflict
        return self

    def eq(self, col, val):
        self._filters.append(("eq", col, val))
        return self

    def neq(self, col, val):
        self._filters.append(("neq", col, val))
        return self

    def gte(self, col, val):
        self._filters.append(("gte", col, val))
        return self

    def gt(self, col, val):
        self._filters.append(("gt", col, val))
        return self

    def lte(self, col, val):
        self._filters.append(("lte", col, val))
        return self

    def lt(self, col, val):
        self._filters.append(("lt", col, val))
        return self

    def is_(self, col, val):
        self._filters.append(("is", col, val))
        return self

    def in_(self, col, vals):
        self._filters.append(("in", col, list(vals)))
        return self

    def order(self, col, desc=False):
        self._order.append((col, desc))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def single(self):
        self._single = True
        return self

    # -- semantics ----------------------------------------------------------
    def _match(self, row):
        for kind, col, val in self._filters:
            v = row.get(col)
            if kind == "eq" and v != val:
                return False
            if kind == "neq" and v == val:
                return False
            if kind == "is" and val == "null" and v is not None:
                return False
            if kind == "in" and v not in val:
                return False
            if kind in ("gte", "gt", "lte", "lt"):
                if v is None:
                    return False
                sv, svv = str(v), str(val)
                if kind == "gte" and not sv >= svv:
                    return False
                if kind == "gt" and not sv > svv:
                    return False
                if kind == "lte" and not sv <= svv:
                    return False
                if kind == "lt" and not sv < svv:
                    return False
        return True

    def _check_constraints(self, table, row, rows, ignore_row=None):
        if table == "trade_suggestions":
            for f in _TS_NOT_NULL:
                if row.get(f) is None:
                    raise _Dup(f'null value in column "{f}" violates not-null constraint')
            if row.get("trace_id") is not None:
                for r in rows:
                    if r is not ignore_row and r.get("trace_id") == row.get("trace_id"):
                        raise _Dup('duplicate key value violates unique constraint '
                                   '"idx_trade_suggestions_trace_id_unique"')
            if row.get("status") not in ("dismissed", "cancelled"):
                key = tuple(row.get(k) for k in
                            ("user_id", "window", "cycle_date", "ticker",
                             "strategy", "legs_fingerprint"))
                for r in rows:
                    if r is ignore_row or r.get("status") in ("dismissed", "cancelled"):
                        continue
                    if tuple(r.get(k) for k in
                             ("user_id", "window", "cycle_date", "ticker",
                              "strategy", "legs_fingerprint")) == key:
                        raise _Dup('duplicate key value violates unique constraint '
                                   '"unique_suggestion_per_cycle_v3"')
        if table == "policy_decisions":
            for f in _PD_NOT_NULL:
                if row.get(f) is None:
                    raise _Dup(f'null value in column "{f}" violates not-null constraint')
            for r in rows:
                if r is not ignore_row and (r.get("cohort_id"), r.get("suggestion_id")) == \
                        (row.get("cohort_id"), row.get("suggestion_id")):
                    raise _Dup('duplicate key value violates unique constraint '
                               '"policy_decisions_cohort_id_suggestion_id_key"')

    def execute(self):
        hook = self._c.raise_hooks.get((self._t, self._op))
        if hook and hook(self):
            raise RuntimeError(f"injected {self._op} failure on {self._t}")

        rows = self._c.tables.setdefault(self._t, [])
        if self._op == "select":
            out = [r for r in rows if self._match(r)]
            for col, desc in reversed(self._order):
                out.sort(key=lambda r: (r.get(col) is None,
                                        r.get(col) if r.get(col) is not None else 0),
                         reverse=desc)
            if self._limit is not None:
                out = out[: self._limit]
            out = copy.deepcopy(out)

            class _R:
                pass
            r = _R()
            r.data = (out[0] if out else {}) if self._single else out
            r.count = len(out) if self._count else None
            return r

        if self._op == "insert":
            payload = self._payload if isinstance(self._payload, list) else [self._payload]
            staged = []
            for row in payload:
                row = copy.deepcopy(row)
                if not row.get("id"):
                    row["id"] = str(uuid.uuid4())
                else:
                    uuid.UUID(str(row["id"]))  # ids must be valid UUIDs
                self._check_constraints(self._t, row, rows)
                staged.append(row)
            rows.extend(staged)
            self._c.writes.setdefault(self._t, []).append(("insert", staged))

            class _R2:
                data = copy.deepcopy(staged)
                count = None
            return _R2()

        if self._op == "update":
            for row in rows:
                if self._match(row):
                    row.update(copy.deepcopy(self._payload))
            self._c.writes.setdefault(self._t, []).append(
                ("update", self._payload, list(self._filters)))

            class _R3:
                data = [{}]
                count = None
            return _R3()

        if self._op == "upsert":
            payload = self._payload if isinstance(self._payload, list) else [self._payload]
            conflict_cols = [c.strip() for c in (self._on_conflict or "").split(",") if c.strip()]
            written = []
            for row in payload:
                row = copy.deepcopy(row)
                target = None
                if conflict_cols:
                    for r in rows:
                        if all(r.get(c) == row.get(c) for c in conflict_cols):
                            target = r
                            break
                if target is not None:
                    self._check_constraints(self._t, {**target, **row}, rows,
                                            ignore_row=target)
                    target.update(row)
                    written.append(copy.deepcopy(target))
                else:
                    if not row.get("id"):
                        row["id"] = str(uuid.uuid4())
                    self._check_constraints(self._t, row, rows)
                    rows.append(row)
                    written.append(copy.deepcopy(row))
            self._c.writes.setdefault(self._t, []).append(("upsert", written))

            class _R4:
                data = copy.deepcopy(written)
                count = None
            return _R4()

        raise RuntimeError(f"unsupported op {self._op}")


class FakeSupabase:
    def __init__(self):
        self.tables = {}
        self.writes = {}
        # (table, op) -> predicate(query) -> bool ; True = raise
        self.raise_hooks = {}

    def table(self, name):
        return _Q(self, name)

    # helpers for origin injection
    def raise_when(self, table, op, predicate=lambda q: True, times=None):
        state = {"left": times}

        def hook(q):
            if not predicate(q):
                return False
            if state["left"] is None:
                return True
            if state["left"] > 0:
                state["left"] -= 1
                return True
            return False
        self.raise_hooks[(table, op)] = hook

    def clear_hooks(self):
        self.raise_hooks = {}


def _has_filter(q, col, val=None):
    for kind, c, v in q._filters:
        if c == col and (val is None or v == val):
            return True
    return False


# ---------------------------------------------------------------------------
# Fixtures — today's live shapes (uuid identities)
# ---------------------------------------------------------------------------

UID = str(uuid.uuid4())


def _pending_qqq():
    """The champion's executable multi-leg IC (07-13 16:00Z shape)."""
    return {
        "id": str(uuid.uuid4()), "user_id": UID, "window": "midday_entry",
        "cycle_date": fork_mod.date.today().isoformat(),
        "ticker": "QQQ", "strategy": "IRON_CONDOR", "direction": "neutral",
        "status": "pending", "cohort_name": None,
        "ev": 18.61, "ev_raw": 37.22, "risk_adjusted_ev": 0.045881,
        "legs_fingerprint": "fp-qqq", "trace_id": str(uuid.uuid4()),
        "model_version": "spy_opt_autolearn_v6@86",
        "lineage_hash": "lh-qqq",
        "order_json": {"contracts": 1, "legs": [
            {"symbol": "QQQ_P1", "side": "buy", "quantity": 1, "mid": 0.2},
            {"symbol": "QQQ_P2", "side": "sell", "quantity": 1, "mid": 0.5},
            {"symbol": "QQQ_C1", "side": "sell", "quantity": 1, "mid": 1.0},
            {"symbol": "QQQ_C2", "side": "buy", "quantity": 1, "mid": 0.5},
        ]},
        "sizing_metadata": {"score": 72.0, "contracts": 1, "max_loss_total": 372.0},
    }


def _prerejected_sofi(ev_raw=30.73):
    """Calibrated-rejected two-leg vertical (07-13 15:02Z SOFI shape)."""
    return {
        "id": str(uuid.uuid4()), "user_id": UID, "window": "midday_entry",
        "cycle_date": fork_mod.date.today().isoformat(),
        "ticker": "SOFI", "strategy": "LONG_CALL_DEBIT_SPREAD", "direction": "long",
        "status": "NOT_EXECUTABLE", "blocked_reason": "edge_below_minimum",
        "cohort_name": None,
        "ev": 15.37, "ev_raw": ev_raw, "risk_adjusted_ev": -999.0,
        "legs_fingerprint": "fp-sofi", "trace_id": str(uuid.uuid4()),
        "model_version": "spy_opt_autolearn_v6@86",
        "lineage_hash": "lh-sofi",
        "order_json": {"contracts": 1, "legs": [
            {"symbol": "SOFI_C1", "side": "buy", "quantity": 1, "mid": 0.6},
            {"symbol": "SOFI_C2", "side": "sell", "quantity": 1, "mid": 0.3},
        ]},
        "sizing_metadata": {"score": 65.0, "contracts": 1, "max_loss_total": 60.0},
    }


def _quality_blocked():
    """Stale/dark/unpriceable class — must NEVER be resurrected."""
    row = _prerejected_sofi()
    row.update({"id": str(uuid.uuid4()), "ticker": "XLE",
                "blocked_reason": "marketdata_quality_gate",
                "legs_fingerprint": "fp-xle", "trace_id": str(uuid.uuid4())})
    return row


def _seed(client, *suggestion_rows):
    client.tables["trade_suggestions"] = [copy.deepcopy(r) for r in suggestion_rows]
    client.tables["policy_lab_cohorts"] = [
        {"id": "c-agg", "user_id": UID, "cohort_name": "aggressive",
         "portfolio_id": "pf-agg", "is_active": True},
        {"id": "c-neu", "user_id": UID, "cohort_name": "neutral",
         "portfolio_id": "pf-neu", "is_active": True},
    ]
    client.tables["paper_portfolios"] = [
        {"id": "pf-agg", "cash_balance": 2000, "net_liq": 2000},
        {"id": "pf-neu", "cash_balance": 10000, "net_liq": 10000},
    ]
    client.tables["paper_positions"] = []


_COHORT_PATCHES = dict(
    is_policy_lab_enabled=lambda: True,
    get_current_champion=lambda *_a, **_k: "aggressive",
)


def _cohort_configs(*_a, **_k):
    return {
        "aggressive": PolicyConfig(),
        "neutral": PolicyConfig(min_score_threshold=0.0),
    }


def _run_fork(client, module=fork_mod):
    with patch.object(module, "is_policy_lab_enabled", _COHORT_PATCHES["is_policy_lab_enabled"]), \
         patch.object(module, "load_cohort_configs", _cohort_configs), \
         patch.object(module, "get_current_champion", _COHORT_PATCHES["get_current_champion"]):
        return module.fork_suggestions_for_cohorts(UID, client)


def _clones(client, **field_filters):
    rows = client.tables.get("trade_suggestions", [])
    out = [r for r in rows if r.get("cohort_name") == "neutral"]
    for k, v in field_filters.items():
        out = [r for r in out if r.get(k) == v]
    return out


def _verdicts(client, suggestion_id=None, decision=None):
    rows = client.tables.get("policy_decisions", [])
    if suggestion_id is not None:
        rows = [r for r in rows if r.get("suggestion_id") == suggestion_id]
    if decision is not None:
        rows = [r for r in rows if r.get("decision") == decision]
    return rows


class _EnvRawOn(unittest.TestCase):
    def setUp(self):
        os.environ.pop("SHADOW_RAW_EV_ENABLED", None)  # default ON

    def tearDown(self):
        os.environ.pop("SHADOW_RAW_EV_ENABLED", None)


# ---------------------------------------------------------------------------
# Defect reproduction + core invariants
# ---------------------------------------------------------------------------

class TestDefectReproduction(_EnvRawOn):
    def test_prerejected_source_produces_exactly_one_shadow_verdict(self):
        client = FakeSupabase()
        sofi = _prerejected_sofi()
        _seed(client, _pending_qqq(), sofi)
        res = _run_fork(client)

        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["errors"], 0)
        self.assertEqual(res["prerejection_source_count"], 1)
        self.assertEqual(res["prerejection_clone_count"], 1)
        self.assertEqual(res["prerejection_verdict_count"], 1)
        self.assertEqual(len(_clones(client, ticker="SOFI")), 1)
        # champion rejection preserved on the source
        src = [r for r in client.tables["trade_suggestions"]
               if r.get("id") == sofi["id"]][0]
        self.assertEqual((src["status"], src["blocked_reason"], src["cohort_name"]),
                         ("NOT_EXECUTABLE", "edge_below_minimum", None))
        self.assertEqual(len(_verdicts(client, sofi["id"], "accepted")), 1)


class TestCloneInvariants(_EnvRawOn):
    def _clone(self):
        client = FakeSupabase()
        sofi = _prerejected_sofi()
        _seed(client, _pending_qqq(), sofi)
        _run_fork(client)
        return client, sofi, _clones(client, ticker="SOFI")[0]

    def test_not_executable_and_honest_execution_state(self):
        """Blocker 5A (adjudicated: ENTRY-SELECTION-ONLY): the clone claims
        NO execution_mode — execution is described by what happened
        (nothing); routing INTENT and observation scope are separate,
        explicit labels."""
        _, _, c = self._clone()
        self.assertEqual(c["status"], "NOT_EXECUTABLE")
        self.assertEqual(c["blocked_reason"], "shadow_prerejection_fork")
        sz = c["sizing_metadata"]
        self.assertNotIn("execution_mode", sz)
        self.assertNotIn("routing_mode", sz)
        self.assertNotIn("calibration_identity", sz)  # B20: no false identity
        self.assertEqual(sz["execution_state"], "not_executed")
        self.assertEqual(sz["execution_intent"], "internal_paper_only")
        self.assertEqual(sz["observation_scope"], "raw_candidate_eligibility_only")
        self.assertEqual(sz["decision_semantics"], "raw_candidate_eligibility")
        self.assertIs(sz["selected_for_entry"], False)
        self.assertIs(sz["capacity_evaluated"], False)
        self.assertIs(sz["joint_rank_evaluated"], False)
        self.assertEqual(sz["routing_intent"], "shadow_only")

    def test_raw_basis_provenance_and_finite_raev(self):
        _, sofi, c = self._clone()
        sz = c["sizing_metadata"]
        self.assertEqual(c["ev"], 30.73)
        self.assertEqual(c["ev_raw"], 30.73)
        self.assertEqual(sz["ev_basis"], "raw")
        self.assertEqual(sz["ev_calibrated"], 15.37)
        self.assertEqual(sz["raev_basis"], "raw_per_contract_normalized")
        # B12 unit-contract stamps
        self.assertEqual(sz["eligibility_ev_unit"], "per_contract")
        self.assertEqual(sz["eligibility_contracts"], 1)
        self.assertEqual(sz["clone_contracts"], c["order_json"]["contracts"])
        self.assertEqual(sz["eligibility_cost_basis"],
                         fork_mod._ELIGIBILITY_COST_BASIS)
        self.assertEqual(sz["source_model_version"], "spy_opt_autolearn_v6@86")
        self.assertEqual(sz["calibration_provenance_status"],
                         "not_persisted_on_source")
        self.assertNotIn("calibration_identity", sz)
        self.assertEqual(sz["experiment_version"], fork_mod.EXPERIMENT_VERSION)
        self.assertEqual(sz["champion_blocked_reason"], "edge_below_minimum")
        self.assertEqual(sz["source_suggestion_id"], sofi["id"])
        # Blocker 4 sharpening: finite numeric ABOVE the sentinel — None must fail
        raev = c["risk_adjusted_ev"]
        self.assertIsInstance(raev, float)
        self.assertTrue(math.isfinite(raev))
        self.assertGreater(raev, -999.0)

    def test_version_embedded_in_fingerprint(self):
        _, _, c = self._clone()
        self.assertIn(f"_prerej_{fork_mod.EXPERIMENT_VERSION}_neutral",
                      c["legs_fingerprint"])


# ---------------------------------------------------------------------------
# Blocker 4 — the raw eligibility gate
# ---------------------------------------------------------------------------

class TestRawGateMatrix(_EnvRawOn):
    def _run_one(self, source, raev_patch=None):
        client = FakeSupabase()
        _seed(client, _pending_qqq(), source)
        if raev_patch is not None:
            from packages.quantum.analytics import canonical_ranker
            with patch.object(canonical_ranker, "compute_risk_adjusted_ev",
                              raev_patch):
                res = _run_fork(client)
        else:
            res = _run_fork(client)
        return client, res

    def _assert_refused(self, client, res, source, reason):
        self.assertEqual(_clones(client, ticker=source["ticker"]), [])
        v = _verdicts(client, source["id"])
        self.assertEqual(len(v), 1)
        self.assertEqual(v[0]["decision"], "rejected")
        self.assertEqual(v[0]["reason_codes"], [reason])
        self.assertEqual(res["errors"], 0)  # typed refusal is NOT an error

    def test_calibrated_fails_raw_passes_creates_clone(self):
        client, res = self._run_one(_prerejected_sofi(ev_raw=30.73))
        self.assertEqual(res["prerejection_counts"]["created"], 1)

    def test_calibrated_fails_raw_also_fails(self):
        # raw 16.0: neutral clone sizes up contracts → fees exceed the $15
        # edge on the raw basis too → canonical -999 → typed refusal
        src = _prerejected_sofi(ev_raw=16.0)
        client, res = self._run_one(src, raev_patch=lambda *a, **k: -999.0)
        self._assert_refused(client, res, src, "raw_edge_below_minimum")

    def test_missing_ev_raw_refused_typed(self):
        src = _prerejected_sofi(ev_raw=None)
        client, res = self._run_one(src)
        self._assert_refused(client, res, src, "missing_ev_basis")

    def test_recompute_raises_refused_typed(self):
        src = _prerejected_sofi()

        def boom(*_a, **_k):
            raise RuntimeError("ranker exploded")
        client, res = self._run_one(src, raev_patch=boom)
        self._assert_refused(client, res, src, "raw_raev_recompute_failed")

    def test_recompute_none_refused_typed(self):
        src = _prerejected_sofi()
        client, res = self._run_one(src, raev_patch=lambda *a, **k: None)
        self._assert_refused(client, res, src, "raw_raev_invalid")

    def test_recompute_nan_and_inf_refused_typed(self):
        for bad in (float("nan"), float("inf")):
            src = _prerejected_sofi()
            client, res = self._run_one(src, raev_patch=lambda *a, **k: bad)
            self._assert_refused(client, res, src, "raw_raev_invalid")

    def test_score_below_cohort_threshold_filtered(self):
        src = _prerejected_sofi()
        src["sizing_metadata"]["score"] = -1.0
        client = FakeSupabase()
        _seed(client, _pending_qqq(), src)
        with patch.object(fork_mod, "is_policy_lab_enabled", lambda: True), \
             patch.object(fork_mod, "load_cohort_configs", lambda *_a, **_k: {
                 "aggressive": PolicyConfig(),
                 "neutral": PolicyConfig(min_score_threshold=50.0)}), \
             patch.object(fork_mod, "get_current_champion", lambda *_a, **_k: "aggressive"):
            fork_mod.fork_suggestions_for_cohorts(UID, client)
        self.assertEqual(_clones(client, ticker="SOFI"), [])
        v = _verdicts(client, src["id"])
        self.assertEqual(v[0]["reason_codes"], ["filtered_by_policy"])

    def test_quality_gate_reject_never_cloned_never_verdicted(self):
        dark = _quality_blocked()
        client, res = self._run_one(dark)
        self.assertEqual(_clones(client, ticker="XLE"), [])
        self.assertEqual(_verdicts(client, dark["id"]), [])

    def test_lever_off_disables_source(self):
        os.environ["SHADOW_RAW_EV_ENABLED"] = "0"
        src = _prerejected_sofi()
        client, res = self._run_one(src)
        self.assertEqual(_clones(client, ticker="SOFI"), [])
        self.assertEqual(res["prerejection_source_count"], 0)


# ---------------------------------------------------------------------------
# Blockers 2/3/10 — recoverable order, persisted-clone verdict, fail-closed
# ---------------------------------------------------------------------------

class TestRecoverableOrder(_EnvRawOn):
    def test_verdict_from_persisted_clone_full_readback(self):
        client = FakeSupabase()
        sofi = _prerejected_sofi()
        _seed(client, _pending_qqq(), sofi)
        _run_fork(client)
        clone = _clones(client, ticker="SOFI")[0]
        v = _verdicts(client, sofi["id"], "accepted")[0]
        fs = v["features_snapshot"]
        self.assertEqual(fs["source_suggestion_id"], sofi["id"])
        self.assertEqual(fs["clone_suggestion_id"], clone["id"])
        self.assertEqual(fs["source_trace_id"], sofi["trace_id"])
        self.assertEqual(fs["source_lineage_hash"], "lh-sofi")
        self.assertEqual(fs["ev"], clone["ev"])
        self.assertEqual(fs["ev_raw"], clone["ev_raw"])
        self.assertEqual(fs["ev_calibrated"], 15.37)
        self.assertEqual(fs["ev_basis"], "raw")
        self.assertEqual(fs["risk_adjusted_ev"], clone["risk_adjusted_ev"])
        self.assertEqual(fs["raev_basis"], "raw_per_contract_normalized")
        self.assertEqual(fs["eligibility_ev_unit"], "per_contract")
        self.assertEqual(fs["eligibility_contracts"], 1)
        self.assertEqual(fs["clone_contracts"], clone["order_json"]["contracts"])
        self.assertEqual(fs["eligibility_cost_basis"],
                         fork_mod._ELIGIBILITY_COST_BASIS)
        self.assertEqual(fs["champion_blocked_reason"], "edge_below_minimum")
        self.assertEqual(fs["routing_intent"], "shadow_only")
        self.assertEqual(fs["execution_state"], "not_executed")
        self.assertEqual(fs["source_model_version"], "spy_opt_autolearn_v6@86")
        self.assertEqual(fs["calibration_provenance_status"],
                         "not_persisted_on_source")
        self.assertEqual(fs["experiment_version"], fork_mod.EXPERIMENT_VERSION)
        self.assertEqual(fs["cohort_name"], "neutral")
        self.assertEqual(fs["clone_fingerprint"], clone["legs_fingerprint"])
        # simulated_fill from the CLONE's own sizing, not the source's
        self.assertEqual(v["simulated_fill"]["contracts"],
                         clone["order_json"]["contracts"])
        self.assertEqual(v["simulated_fill"]["max_loss_total"],
                         clone["sizing_metadata"]["max_loss_total"])

    def test_verdict_upsert_failure_typed_then_repaired_on_rerun(self):
        client = FakeSupabase()
        sofi = _prerejected_sofi()
        _seed(client, _pending_qqq(), sofi)
        client.raise_when("policy_decisions", "upsert")
        res1 = _run_fork(client)
        self.assertEqual(res1["status"], "partial")
        self.assertGreaterEqual(res1["errors"], 1)
        self.assertEqual(res1["prerejection_counts"]["accepted_verdict_failed"], 1)
        self.assertEqual(len(_clones(client, ticker="SOFI")), 1)   # clone persisted
        self.assertEqual(_verdicts(client, sofi["id"]), [])        # no verdict yet
        stages = {e["stage"] for e in res1["error_details"]}
        self.assertIn("verdict_upsert_failed", stages)

        client.clear_hooks()
        res2 = _run_fork(client)
        self.assertEqual(res2["status"], "ok")
        self.assertEqual(res2["prerejection_counts"]["repaired"], 1)
        self.assertEqual(len(_clones(client, ticker="SOFI")), 1)   # no duplicate
        self.assertEqual(len(_verdicts(client, sofi["id"], "accepted")), 1)

    def test_clone_insert_failure_no_accepted_verdict(self):
        client = FakeSupabase()
        sofi = _prerejected_sofi()
        _seed(client, _pending_qqq(), sofi)
        client.raise_when(
            "trade_suggestions", "insert",
            predicate=lambda q: any("_prerej_" in str(r.get("legs_fingerprint"))
                                    for r in (q._payload if isinstance(q._payload, list)
                                              else [q._payload])))
        res = _run_fork(client)
        self.assertEqual(res["status"], "partial")
        self.assertEqual(res["prerejection_counts"]["clone_failed"], 1)
        self.assertEqual(_clones(client, ticker="SOFI"), [])
        self.assertEqual(_verdicts(client, sofi["id"], "accepted"), [])

    def test_clone_lookup_failure_fails_closed_no_insert(self):
        """Blocker 10: 'could not prove absence' must never insert."""
        client = FakeSupabase()
        sofi = _prerejected_sofi()
        _seed(client, _pending_qqq(), sofi)
        client.raise_when(
            "trade_suggestions", "select",
            predicate=lambda q: _has_filter(q, "legs_fingerprint"))
        res = _run_fork(client)
        self.assertEqual(res["status"], "partial")
        self.assertEqual(res["prerejection_counts"]["clone_failed"], 1)
        stages = {e["stage"] for e in res["error_details"]}
        self.assertIn("clone_lookup_failed", stages)
        self.assertEqual(_clones(client, ticker="SOFI"), [])

    def test_duplicate_race_reconciled_as_existing(self):
        client = FakeSupabase()
        sofi = _prerejected_sofi()
        _seed(client, _pending_qqq(), sofi)
        _run_fork(client)  # first run creates the clone
        # delete the verdict to simulate a half-completed prior run, then
        # re-run: lookup finds the clone → existing → verdict repaired
        client.tables["policy_decisions"] = [
            r for r in client.tables["policy_decisions"]
            if r.get("suggestion_id") != sofi["id"]]
        res = _run_fork(client)
        self.assertEqual(res["prerejection_counts"]["existing"], 1)
        self.assertEqual(res["prerejection_counts"]["repaired"], 1)
        self.assertEqual(len(_clones(client, ticker="SOFI")), 1)

    def test_full_rerun_idempotent(self):
        client = FakeSupabase()
        _seed(client, _pending_qqq(), _prerejected_sofi())
        _run_fork(client)
        n = len(client.tables["trade_suggestions"])
        res = _run_fork(client)
        self.assertEqual(len(client.tables["trade_suggestions"]), n)
        self.assertEqual(res["prerejection_counts"]["existing"], 1)
        self.assertEqual(res["prerejection_counts"]["created"], 0)


# ---------------------------------------------------------------------------
# Blocker 12 — the EV quantity-unit contract
# ---------------------------------------------------------------------------

class TestEvUnitContract(_EnvRawOn):
    """Eligibility is decided on the one-contract normalized view: identical
    decisions and identical normalized raw RAeV at EVERY clone quantity."""

    def _clone_at(self, deployable, ev_raw=30.73, src=None):
        src = src or _prerejected_sofi(ev_raw=ev_raw)
        clone, reason = fork_mod._build_prerejection_clone(
            copy.deepcopy(src), "neutral",
            PolicyConfig(min_score_threshold=0.0), deployable)
        return clone, reason

    def test_invariance_across_clone_quantities(self):
        results = []
        for deployable in (400.0, 900.0, 2500.0, 10000.0):
            clone, reason = self._clone_at(deployable)
            self.assertIsNone(reason)
            results.append((clone["order_json"]["contracts"],
                            clone["risk_adjusted_ev"],
                            clone["max_loss_total"]))
        quantities = [r[0] for r in results]
        self.assertGreater(len(set(quantities)), 1,
                           f"fixture must vary clone qty, got {quantities}")
        # same eligibility RAeV at every quantity
        self.assertEqual(len({r[1] for r in results}), 1, results)
        # clone risk STILL scales with clone quantity (per-ct 60.0)
        for qty, _raev, mlt in results:
            self.assertAlmostEqual(mlt, 60.0 * qty, places=2)
        # the normalized value itself: net = 30.73 − 5%·30.73 − 1.30 = 27.8935;
        # raev = 27.8935 / 60 (per-contract max loss)
        self.assertAlmostEqual(results[0][1], round(27.8935 / 60.0, 6), places=6)

    def test_below_15_per_contract_refuses_at_every_quantity(self):
        # net = 0.95×16 − 1.30 = 13.90 < 15 → refuse regardless of clone size
        for deployable in (400.0, 900.0, 2500.0, 10000.0):
            clone, reason = self._clone_at(deployable, ev_raw=16.0)
            self.assertIsNone(clone)
            self.assertEqual(reason, "raw_edge_below_minimum")

    def test_above_15_per_contract_accepts_at_every_quantity(self):
        # net = 0.95×18 − 1.30 = 15.80 ≥ 15 → accept regardless of clone size
        for deployable in (400.0, 900.0, 2500.0, 10000.0):
            clone, reason = self._clone_at(deployable, ev_raw=18.0)
            self.assertIsNone(reason)
            self.assertAlmostEqual(clone["risk_adjusted_ev"],
                                   round((0.95 * 18.0 - 1.30) / 60.0, 6),
                                   places=6)

    def test_sofi_fixture_no_longer_uses_mixed_units(self):
        """The literal SOFI shape must be judged at contracts=1 — never the
        old '30.73 minus ten-contract fees' mixed calculation."""
        clone, reason = self._clone_at(10000.0)
        self.assertIsNone(reason)
        old_mixed = round((30.73 - 0.05 * 30.73
                           - 0.65 * clone["order_json"]["contracts"] * 2)
                          / clone["max_loss_total"], 6)
        self.assertNotEqual(clone["risk_adjusted_ev"], old_mixed)
        self.assertAlmostEqual(clone["risk_adjusted_ev"],
                               round(27.8935 / 60.0, 6), places=6)

    def test_invalid_ev_and_max_loss_typed_refusals(self):
        cases = [
            ({"ev_raw": None}, "missing_ev_basis"),
            ({"ev_raw": 0.0}, "raw_ev_invalid"),
            ({"ev_raw": float("nan")}, "raw_ev_invalid"),
            ({"ev_raw": float("inf")}, "raw_ev_invalid"),
        ]
        for patch_fields, want in cases:
            src = _prerejected_sofi()
            src.update(patch_fields)
            view, reason = fork_mod.build_raw_eligibility_view(src)
            self.assertIsNone(view)
            self.assertEqual(reason, want, patch_fields)
        # per-contract max-loss failures
        for sz_patch in ({"max_loss_total": None}, {"max_loss_total": 0},
                         {"max_loss_total": float("nan")}, {"contracts": 0}):
            src = _prerejected_sofi()
            src["sizing_metadata"] = {**src["sizing_metadata"], **sz_patch}
            src.pop("max_loss_total", None)
            # keep sizing & order contract counts aligned so this exercises the
            # normalization guard, not the B17 mismatch guard
            if "contracts" in sz_patch:
                src["order_json"] = {**src["order_json"],
                                     "contracts": sz_patch["contracts"]}
            view, reason = fork_mod.build_raw_eligibility_view(src)
            self.assertIsNone(view)
            self.assertEqual(reason, "max_loss_not_normalizable", sz_patch)

    def test_contract_count_basis_mismatch_typed(self):
        """B17: sizing.contracts != order_json.contracts → never chosen
        silently; typed refusal, no clone."""
        src = _prerejected_sofi()
        src["sizing_metadata"] = {**src["sizing_metadata"], "contracts": 1}
        src["order_json"] = {**src["order_json"], "contracts": 3}
        view, reason = fork_mod.build_raw_eligibility_view(src)
        self.assertIsNone(view)
        self.assertEqual(reason, "contract_count_basis_mismatch")


# ---------------------------------------------------------------------------
# Blocker 13 — persisted clone identity validation
# ---------------------------------------------------------------------------

class TestPersistedCloneIdentity(_EnvRawOn):
    MISMATCH_PARAMS = [
        ("source_suggestion_id", "sizing", "source_suggestion_id", "other-id",
         "clone_identity_mismatch"),
        ("cohort_name", "row", "cohort_name", "conservative",
         "clone_identity_mismatch"),
        ("experiment_version", "sizing", "experiment_version", "v999",
         "clone_identity_mismatch"),
        # legs_fingerprint is a LOOKUP KEY — a tampered row cannot be found,
        # so it is covered by dedicated tests below, not this route matrix.
        ("observation_scope", "sizing", "observation_scope", "outcome",
         "clone_identity_mismatch"),
        ("execution_state", "sizing", "execution_state", "filled",
         "clone_identity_mismatch"),
        ("execution_intent", "sizing", "execution_intent", "live",
         "clone_identity_mismatch"),
        ("routing_intent", "sizing", "routing_intent", "live_eligible",
         "clone_identity_mismatch"),
        ("ev_basis", "sizing", "ev_basis", "calibrated",
         "clone_basis_mismatch"),
        ("ev_raw", "row", "ev_raw", 99.99, "clone_basis_mismatch"),
        ("ev_calibrated", "sizing", "ev_calibrated", 1.23,
         "clone_basis_mismatch"),
        ("risk_adjusted_ev", "row", "risk_adjusted_ev", 0.42,
         "clone_basis_mismatch"),
    ]

    def _run_with_preexisting(self, tamper=None):
        """Seed the EXACT persisted clone (by running once), optionally tamper
        one field, wipe the verdict, and re-run → the repair path must
        validate identity before writing."""
        client = FakeSupabase()
        sofi = _prerejected_sofi()
        _seed(client, _pending_qqq(), sofi)
        _run_fork(client)
        # wipe the verdict so the rerun takes the repair path
        client.tables["policy_decisions"] = [
            r for r in client.tables["policy_decisions"]
            if r.get("suggestion_id") != sofi["id"]]
        if tamper:
            where, field, value = tamper
            row = _clones(client, ticker="SOFI")[0]
            if where == "row":
                row[field] = value
            else:
                row["sizing_metadata"][field] = value
        res = _run_fork(client)
        return client, sofi, res

    def test_each_identity_field_mismatch_blocks_verdict(self):
        for name, where, field, value, want_kind in self.MISMATCH_PARAMS:
            client, sofi, res = self._run_with_preexisting(
                tamper=(where, field, value))
            self.assertEqual(
                _verdicts(client, sofi["id"], "accepted"), [],
                f"accepted verdict written despite {name} mismatch")
            self.assertEqual(res["status"], "partial", name)
            self.assertEqual(
                res["prerejection_counts"]["identity_mismatch"], 1, name)
            stages = {e["stage"] for e in res["error_details"]}
            self.assertIn(want_kind, stages, name)

    def test_fingerprint_mismatch_at_validator_level(self):
        """legs_fingerprint is one of the idempotency lookup keys, so a
        route-level tamper is unfindable by construction; the validator
        itself must still reject a foreign-fingerprint row."""
        client = FakeSupabase()
        sofi = _prerejected_sofi()
        _seed(client, _pending_qqq(), sofi)
        _run_fork(client)
        persisted = copy.deepcopy(_clones(client, ticker="SOFI")[0])
        expected = copy.deepcopy(persisted)
        persisted["legs_fingerprint"] = "fp-tampered"
        kind, field = fork_mod._validate_persisted_clone(
            persisted, expected, sofi)
        self.assertEqual((kind, field),
                         ("clone_identity_mismatch", "legs_fingerprint"))

    def test_tampered_fingerprint_row_never_receives_verdict(self):
        """Route-level: a fingerprint-tampered row is simply not the clone —
        the system mints a fresh CORRECT clone and the accepted verdict binds
        to the new clone's id, never the tampered row's."""
        client, sofi, res = self._run_with_preexisting(
            tamper=("row", "legs_fingerprint", "fp-tampered"))
        self.assertEqual(res["status"], "ok")
        sofi_rows = _clones(client, ticker="SOFI")
        self.assertEqual(len(sofi_rows), 2)  # tampered orphan + fresh clone
        tampered = [r for r in sofi_rows
                    if r["legs_fingerprint"] == "fp-tampered"][0]
        clean = [r for r in sofi_rows
                 if r["legs_fingerprint"] != "fp-tampered"][0]
        v = _verdicts(client, sofi["id"], "accepted")
        self.assertEqual(len(v), 1)
        self.assertEqual(v[0]["features_snapshot"]["clone_suggestion_id"],
                         clean["id"])
        self.assertNotEqual(v[0]["features_snapshot"]["clone_suggestion_id"],
                            tampered["id"])

    def test_exact_match_repairs_and_rerun_idempotent(self):
        client, sofi, res = self._run_with_preexisting(tamper=None)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["prerejection_counts"]["repaired"], 1)
        self.assertEqual(len(_verdicts(client, sofi["id"], "accepted")), 1)
        res2 = _run_fork(client)
        self.assertEqual(res2["status"], "ok")
        self.assertEqual(len(_clones(client, ticker="SOFI")), 1)
        self.assertEqual(len(_verdicts(client, sofi["id"], "accepted")), 1)

    def test_counts_reconcile_with_dispositions(self):
        """B15 invariant: source_cohort_attempts == accepted + refused +
        clone_failed + identity_mismatch + accepted_verdict_failed +
        cohort_identity_missing (one terminal disposition per attempt).
        reject_verdict_write_failed is a SECONDARY error on an already-refused
        attempt and does NOT enter this identity."""
        client = FakeSupabase()
        good = _prerejected_sofi()
        no_basis = _prerejected_sofi(ev_raw=None)
        no_basis.update({"id": str(uuid.uuid4()), "ticker": "XPEV",
                         "legs_fingerprint": "fp-xpev",
                         "trace_id": str(uuid.uuid4())})
        _seed(client, _pending_qqq(), good, no_basis)
        res = _run_fork(client)
        c = res["prerejection_counts"]
        self.assertEqual(
            c["source_cohort_attempts"],
            c["accepted"] + c["refused"] + c["clone_failed"]
            + c["identity_mismatch"] + c["accepted_verdict_failed"]
            + c["cohort_binding_unavailable"] + c["cohort_identity_missing"]
            + c["cohort_portfolio_missing"] + c["cohort_capital_invalid"])
        self.assertEqual(c["source_cohort_attempts"],
                         res["expected_source_cohort_attempts"])
        self.assertTrue(res["coverage_complete"])
        # single non-champion cohort (neutral) × 2 sources = 2 attempts
        self.assertEqual(c["source_cohort_attempts"], 2)
        self.assertEqual(c["source"], 2)
        self.assertEqual(c["accepted"], 1)
        self.assertEqual(c["refused"], 1)
        self.assertEqual(c["accepted_verdicts"], 1)
        self.assertEqual(c["rejected_verdicts"], 1)
        self.assertEqual(res["prerejection_total_verdict_count"], 2)
        self.assertEqual(c["accepted_verdict_failed"], 0)

    def test_reject_verdict_write_failure_is_secondary_not_double_counted(self):
        """B15: a rejected-verdict UPSERT failure increments
        reject_verdict_write_failed AND errors, degrades to partial, but the
        terminal disposition stays `refused` (not double-counted)."""
        client = FakeSupabase()
        no_basis = _prerejected_sofi(ev_raw=None)
        _seed(client, _pending_qqq(), no_basis)
        client.raise_when("policy_decisions", "upsert")
        res = _run_fork(client)
        c = res["prerejection_counts"]
        self.assertEqual(res["status"], "partial")
        self.assertEqual(c["refused"], 1)
        self.assertEqual(c["reject_verdict_write_failed"], 1)
        self.assertEqual(c["rejected_verdicts"], 0)  # write failed → not counted
        self.assertEqual(c["accepted_verdict_failed"], 0)
        # invariant still holds: refused counts the terminal disposition once
        self.assertEqual(
            c["source_cohort_attempts"],
            c["accepted"] + c["refused"] + c["clone_failed"]
            + c["identity_mismatch"] + c["accepted_verdict_failed"]
            + c["cohort_binding_unavailable"] + c["cohort_identity_missing"]
            + c["cohort_portfolio_missing"] + c["cohort_capital_invalid"])
        self.assertGreaterEqual(res["errors"], 1)
        stages = {e["stage"] for e in res["error_details"]}
        self.assertIn("reject_verdict_upsert_failed", stages)


# ---------------------------------------------------------------------------
# Blocker 8 — version semantics (honest narrowing)
# ---------------------------------------------------------------------------

class TestVersionSemantics(_EnvRawOn):
    def test_new_version_mints_distinct_clone_verdict_is_latest_only(self):
        client = FakeSupabase()
        sofi = _prerejected_sofi()
        _seed(client, _pending_qqq(), sofi)
        _run_fork(client)
        with patch.object(fork_mod, "EXPERIMENT_VERSION", "e19_prerejection_v2"):
            _run_fork(client)
        sofi_clones = _clones(client, ticker="SOFI")
        self.assertEqual(len(sofi_clones), 2)  # version-aware clone identity
        versions = {c["sizing_metadata"]["experiment_version"] for c in sofi_clones}
        self.assertEqual(versions, {"e19_prerejection_v1", "e19_prerejection_v2"})
        # DOCUMENTED NARROWING: UNIQUE(cohort_id, suggestion_id) is
        # version-blind — one verdict row, representing the LATEST run.
        v = _verdicts(client, sofi["id"], "accepted")
        self.assertEqual(len(v), 1)
        self.assertEqual(v[0]["features_snapshot"]["experiment_version"],
                         "e19_prerejection_v2")


# ---------------------------------------------------------------------------
# Blocker 1 — failure origins reach the TOP-LEVEL job contract
# ---------------------------------------------------------------------------

def _drive_suggestions_open(client):
    """Drive the REAL suggestions_open.run with the REAL fork. The midday
    cycle itself is stubbed with an async no-op cycle_result: it is a
    PARALLEL branch that runs BEFORE the fork — it does not sit between the
    injected origin (the fork's DB layer) and the asserted truth (the job
    result), so stubbing it does not forfeit any layer under test.
    (The full production route incl. the real cycle is TestFullRoute.)"""
    from packages.quantum.jobs.handlers import suggestions_open as so

    async def _stub_cycle(*_a, **_k):
        return {"counts": {}}

    class _NotStale:
        blocked = False
        reason = ""
        age_seconds = 0
        stale_symbols = []

    with patch("packages.quantum.risk.staleness_gate.check_staleness_gate",
               lambda: _NotStale()), \
         patch.object(so, "is_market_day", lambda: (True, "open")), \
         patch.object(so, "get_admin_client", lambda: client), \
         patch.object(so, "get_active_user_ids", lambda _c: [UID]), \
         patch.object(so, "ensure_default_strategy_exists", lambda *a, **k: None), \
         patch.object(so, "load_strategy_config", lambda *a, **k: {"version": 1}), \
         patch.object(so, "run_midday_cycle", _stub_cycle), \
         patch("packages.quantum.policy_lab.config.is_policy_lab_enabled",
               lambda: True), \
         patch.object(fork_mod, "is_policy_lab_enabled", lambda: True), \
         patch.object(fork_mod, "load_cohort_configs", _cohort_configs), \
         patch.object(fork_mod, "get_current_champion",
                      lambda *_a, **_k: "aggressive"):
        return so.run({"date": "2026-07-13", "type": "open"})


class TestTopLevelFailurePropagation(_EnvRawOn):
    """Each failure injected at its REAL origin must classify the JOB
    partial — none of these can ride a green scheduled job again."""

    def _assert_partial(self, result):
        from packages.quantum.jobs.runner import _classify_handler_return
        self.assertFalse(result["ok"])
        self.assertGreaterEqual(int(result["counts"]["errors"]), 1)
        self.assertEqual(_classify_handler_return(result), "partial")

    def _client(self):
        client = FakeSupabase()
        _seed(client, _pending_qqq(), _prerejected_sofi())
        return client

    def test_control_no_injection_is_green(self):
        from packages.quantum.jobs.runner import _classify_handler_return
        result = _drive_suggestions_open(self._client())
        self.assertTrue(result["ok"])
        self.assertEqual(int(result["counts"]["errors"]), 0)
        self.assertEqual(_classify_handler_return(result), "succeeded")

    def test_prerejection_select_failure_job_partial(self):
        client = self._client()
        client.raise_when(
            "trade_suggestions", "select",
            predicate=lambda q: _has_filter(q, "status", "NOT_EXECUTABLE"))
        self._assert_partial(_drive_suggestions_open(client))

    def test_clone_lookup_failure_job_partial(self):
        client = self._client()
        client.raise_when(
            "trade_suggestions", "select",
            predicate=lambda q: _has_filter(q, "legs_fingerprint"))
        self._assert_partial(_drive_suggestions_open(client))

    def test_clone_insert_failure_job_partial(self):
        client = self._client()
        client.raise_when(
            "trade_suggestions", "insert",
            predicate=lambda q: any(
                "_prerej_" in str(r.get("legs_fingerprint"))
                for r in (q._payload if isinstance(q._payload, list)
                          else [q._payload])))
        self._assert_partial(_drive_suggestions_open(client))

    def test_verdict_upsert_failure_job_partial(self):
        client = self._client()
        client.raise_when("policy_decisions", "upsert")
        self._assert_partial(_drive_suggestions_open(client))

    def test_champion_detail_preserved_on_partial(self):
        client = self._client()
        client.raise_when("policy_decisions", "upsert")
        result = _drive_suggestions_open(client)
        cr = result["cycle_results"][0]
        # B18 honest non-claim: the legacy champion path is not measured.
        self.assertEqual(cr["fork_champion_status"], "legacy_unmeasured")
        self.assertEqual(cr["fork_status"], "partial")


# ---------------------------------------------------------------------------
# Blocker 11 — champion fence vs the FROZEN f34d5cd baseline
# ---------------------------------------------------------------------------

def _load_baseline_module():
    path = Path(__file__).parent / "fixtures" / "fork_baseline_f34d5cd.py"
    spec = importlib.util.spec_from_file_location("fork_baseline_f34d5cd", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _champion_view(client):
    """Champion-visible effect set: source rows + champion-tag updates +
    NORMAL (pending) clones + champion policy decisions. Experimental rows
    (the sanctioned additions) are excluded; non-deterministic fields
    stripped; sanctioned additive provenance keys stripped from normal
    clones before comparison."""
    sugg = []
    for r in sorted(client.tables.get("trade_suggestions", []),
                    key=lambda x: (str(x.get("ticker")), str(x.get("cohort_name")))):
        if r.get("blocked_reason") == "shadow_prerejection_fork":
            continue  # sanctioned experimental artifact
        r = copy.deepcopy(r)
        for k in ("id", "trace_id", "created_at"):
            r.pop(k, None)
        r.pop("ev_raw", None)  # sanctioned additive provenance (normal clones)
        sz = r.get("sizing_metadata")
        if isinstance(sz, dict):
            sz.pop("ev_basis", None)
            sz.pop("raev_basis", None)
        sugg.append(r)
    updates = [w for w in client.writes.get("trade_suggestions", [])
               if w[0] == "update"]
    decisions = []
    for r in sorted(client.tables.get("policy_decisions", []),
                    key=lambda x: str(x.get("suggestion_id"))):
        if "prerejection_shadow_observation" in (r.get("reason_codes") or []) \
                or set(r.get("reason_codes") or []) & {
                    "missing_ev_basis", "raw_edge_below_minimum",
                    "raw_raev_recompute_failed", "raw_raev_invalid",
                    "filtered_by_policy"}:
            # prerejection verdicts are sanctioned additions; note that
            # 'filtered_by_policy' rows for PENDING sources (legacy) are kept
            # via the fingerprint check below
            if r.get("features_snapshot", {}).get("blocked_reason") \
                    == "edge_below_minimum" or \
                    r.get("features_snapshot", {}).get("champion_blocked_reason"):
                continue
        r = copy.deepcopy(r)
        for k in ("id", "created_at"):
            r.pop(k, None)
        fs = r.get("features_snapshot")
        if isinstance(fs, dict):
            fs.pop("ev_raw", None)
            fs.pop("ev_basis", None)
            fs.pop("blocked_reason", None)
        decisions.append(r)
    return json.loads(json.dumps(
        {"suggestions": sugg, "updates": updates, "decisions": decisions},
        sort_keys=True, default=str))


class TestChampionFrozenBaseline(_EnvRawOn):
    """Run the LITERAL f34d5cd fork source and the amended fork on identical
    inputs + identical hardened fakes; the champion-visible effect sets must
    be EQUAL. Scenarios: no divergence · divergence candidate · quality
    reject · retry/replay."""

    SCENARIOS = {
        "no_divergence": lambda: [_pending_qqq()],
        "with_divergence": lambda: [_pending_qqq(), _prerejected_sofi()],
        "quality_reject": lambda: [_pending_qqq(), _quality_blocked()],
    }

    def _run_pair(self, rows_factory, reruns=1):
        baseline_mod = _load_baseline_module()
        rows = rows_factory()
        results = {}
        for name, module in (("baseline", baseline_mod), ("current", fork_mod)):
            client = FakeSupabase()
            _seed(client, *[copy.deepcopy(r) for r in rows])
            for _ in range(reruns):
                _run_fork(client, module=module)
            results[name] = _champion_view(client)
        return results

    def test_no_divergence_identical(self):
        r = self._run_pair(self.SCENARIOS["no_divergence"])
        self.assertEqual(r["baseline"], r["current"])

    def test_with_divergence_champion_identical(self):
        r = self._run_pair(self.SCENARIOS["with_divergence"])
        self.assertEqual(r["baseline"], r["current"])

    def test_quality_reject_identical(self):
        r = self._run_pair(self.SCENARIOS["quality_reject"])
        self.assertEqual(r["baseline"], r["current"])

    def test_retry_replay_identical(self):
        r = self._run_pair(self.SCENARIOS["with_divergence"], reruns=2)
        self.assertEqual(r["baseline"], r["current"])


# ---------------------------------------------------------------------------
# Blocker 7 — executor isolation at the PRODUCTION boundaries
# ---------------------------------------------------------------------------

class TestExecutorIsolation(_EnvRawOn):
    def _seeded_client_with_clone(self):
        client = FakeSupabase()
        sofi = _prerejected_sofi()
        _seed(client, _pending_qqq(), sofi)
        _run_fork(client)
        # remove the champion pending row so the ONLY candidate rows left for
        # selection are the experimental artifacts
        client.tables["trade_suggestions"] = [
            r for r in client.tables["trade_suggestions"]
            if r.get("status") != "pending" or r.get("cohort_name") == "neutral"
        ]
        return client

    def test_live_selection_excludes_clone(self):
        """The live executor's ACTUAL selection function returns nothing for
        a book containing only prerejection clones."""
        from packages.quantum.services.paper_autopilot_service import (
            PaperAutopilotService,
        )
        client = self._seeded_client_with_clone()
        # keep only NOT_EXECUTABLE rows (drop the normal neutral clone too)
        client.tables["trade_suggestions"] = [
            r for r in client.tables["trade_suggestions"]
            if r.get("blocked_reason") == "shadow_prerejection_fork"
            or r.get("status") == "NOT_EXECUTABLE"
        ]
        svc = PaperAutopilotService.__new__(PaperAutopilotService)
        svc.client = client
        rows = svc.get_executable_suggestions(UID, include_backlog=False)
        self.assertEqual(rows, [])

    def test_no_staging_no_submit_through_production_predicates(self):
        """Selection predicates used by the per-cohort executor + broker
        submit spy: a prerejection clone can produce NO staging write, NO
        paper_orders row, NO broker submit."""
        client = self._seeded_client_with_clone()
        client.tables["trade_suggestions"] = [
            r for r in client.tables["trade_suggestions"]
            if r.get("blocked_reason") == "shadow_prerejection_fork"
        ]
        submit_calls = []
        with patch("packages.quantum.brokers.alpaca_order_handler.submit_and_track",
                   side_effect=lambda *a, **k: submit_calls.append(a) or {"status": "submitted"}):
            # the executor's exact per-cohort selection shape (status='pending')
            pending = client.table("trade_suggestions").select("*") \
                .eq("user_id", UID).eq("cohort_name", "neutral") \
                .eq("status", "pending").execute().data
            self.assertEqual(pending, [])
        self.assertEqual(submit_calls, [])
        self.assertEqual(client.tables.get("paper_orders", []), [])
        staged_writes = [w for w in client.writes.get("trade_suggestions", [])
                         if w[0] == "update" and
                         isinstance(w[1], dict) and w[1].get("status") == "staged"]
        self.assertEqual(staged_writes, [])


# ---------------------------------------------------------------------------
# Blocker 14 — active-clone lookup (archived twins ignored)
# ---------------------------------------------------------------------------

class TestActiveCloneLookup(_EnvRawOn):
    def _make_persisted_clone(self, status="NOT_EXECUTABLE",
                              blocked_reason="shadow_prerejection_fork"):
        """Seed one archived clone shape directly, then run the fork and
        return (client, sofi)."""
        client = FakeSupabase()
        sofi = _prerejected_sofi()
        _seed(client, _pending_qqq(), sofi)
        return client, sofi

    def _archived_clone_row(self, sofi, status):
        """A row sharing the clone's unique-index key but in an ARCHIVED /
        wrong-reason state (must never be picked up as THE active clone)."""
        clone, _ = fork_mod._build_prerejection_clone(
            copy.deepcopy(sofi), "neutral",
            PolicyConfig(min_score_threshold=0.0), 10000.0)
        clone["id"] = str(uuid.uuid4())
        clone["status"] = status
        return clone

    def test_dismissed_twin_ignored_new_active_clone_created(self):
        client, sofi = self._make_persisted_clone()
        client.tables["trade_suggestions"].append(
            self._archived_clone_row(sofi, "dismissed"))
        res = _run_fork(client)
        active = _clones(client, ticker="SOFI",
                         blocked_reason="shadow_prerejection_fork")
        active = [r for r in active if r["status"] == "NOT_EXECUTABLE"]
        self.assertEqual(len(active), 1)               # a fresh active clone
        self.assertEqual(res["prerejection_counts"]["created"], 1)
        v = _verdicts(client, sofi["id"], "accepted")[0]
        self.assertEqual(v["features_snapshot"]["clone_suggestion_id"],
                         active[0]["id"])              # verdict → the active one

    def test_cancelled_twin_ignored(self):
        client, sofi = self._make_persisted_clone()
        client.tables["trade_suggestions"].append(
            self._archived_clone_row(sofi, "cancelled"))
        res = _run_fork(client)
        self.assertEqual(res["prerejection_counts"]["created"], 1)
        self.assertEqual(len(_verdicts(client, sofi["id"], "accepted")), 1)

    def test_active_plus_archived_returns_active_deterministically(self):
        client, sofi = self._make_persisted_clone()
        _run_fork(client)  # creates the real active clone
        active_id = _clones(client, ticker="SOFI",
                            blocked_reason="shadow_prerejection_fork")[0]["id"]
        # add an archived twin AFTER the active one
        client.tables["trade_suggestions"].append(
            self._archived_clone_row(sofi, "dismissed"))
        # wipe verdict → repair path
        client.tables["policy_decisions"] = []
        res = _run_fork(client)
        self.assertEqual(res["prerejection_counts"]["existing"], 1)
        v = _verdicts(client, sofi["id"], "accepted")[0]
        self.assertEqual(v["features_snapshot"]["clone_suggestion_id"], active_id)

    def test_active_row_wrong_blocked_reason_rejected_by_lookup_and_validator(self):
        """A row active + sharing the fingerprint key but carrying a foreign
        blocked_reason is NOT this clone. The active-clone LOOKUP filters it
        out (status+reason clauses) and the VALIDATOR independently rejects
        it. (A real foreign row can't share the _prerej_ fingerprint, so this
        is tested at the two component boundaries, not via a route that would
        require an impossible unique-key collision.)"""
        client, sofi = self._make_persisted_clone()
        expected, _ = fork_mod._build_prerejection_clone(
            copy.deepcopy(sofi), "neutral",
            PolicyConfig(min_score_threshold=0.0), 10000.0)
        foreign = copy.deepcopy(expected)
        foreign["id"] = str(uuid.uuid4())
        foreign["blocked_reason"] = "some_other_reason"
        client.tables["trade_suggestions"].append(foreign)
        # LOOKUP: the active-clone query must NOT return the foreign row
        found = fork_mod._find_existing_clone(client, expected)
        self.assertIsNone(found)
        # VALIDATOR: independent hard reject on blocked_reason
        kind, field = fork_mod._validate_persisted_clone(foreign, expected, sofi)
        self.assertEqual((kind, field),
                         ("clone_identity_mismatch", "blocked_reason"))


# ---------------------------------------------------------------------------
# Blocker 16 — missing cohort id is non-green
# ---------------------------------------------------------------------------

class TestMissingCohortId(_EnvRawOn):
    def test_configured_cohort_without_id_is_partial_no_orphan(self):
        client = FakeSupabase()
        sofi = _prerejected_sofi()
        _seed(client, _pending_qqq(), sofi)
        # neutral cohort has a portfolio but NO id row
        client.tables["policy_lab_cohorts"] = [
            r for r in client.tables["policy_lab_cohorts"]
            if r["cohort_name"] != "neutral"]
        client.tables["policy_lab_cohorts"].append(
            {"id": None, "user_id": UID, "cohort_name": "neutral",
             "portfolio_id": "pf-neu", "is_active": True})
        res = _run_fork(client)
        self.assertEqual(res["status"], "partial")
        self.assertEqual(res["prerejection_counts"]["cohort_identity_missing"], 1)
        self.assertEqual(_clones(client, ticker="SOFI"), [])  # no orphan clone
        self.assertEqual(_verdicts(client, sofi["id"], "accepted"), [])
        stages = {e["stage"] for e in res["error_details"]}
        self.assertIn("cohort_identity_missing", stages)

    def test_binding_query_failure_distinct_from_empty(self):
        """B19-F / B16: a binding-read fault must NOT become an authoritative
        empty result. Inject at the REAL binding-query origin (the
        policy_lab_cohorts select reading id+portfolio_id); every expected
        pair records cohort_binding_unavailable (non-green), never a silent
        skip or a fabricated empty."""
        client = FakeSupabase()
        sofi = _prerejected_sofi()
        _seed(client, _pending_qqq(), sofi)
        client.raise_when(
            "policy_lab_cohorts", "select",
            predicate=lambda q: "portfolio_id" in q._select_cols
            and q._select_cols.startswith("id"))
        res = _run_fork(client)
        self.assertEqual(res["status"], "partial")
        stages = {e["stage"] for e in res["error_details"]}
        self.assertIn("cohort_bindings_fetch_failed", stages)
        c = res["prerejection_counts"]
        self.assertEqual(c["cohort_binding_unavailable"], 1)
        self.assertEqual(c["source_cohort_attempts"], 1)
        self.assertFalse(res["coverage_complete"] is True and c["accepted"] > 0)
        self.assertEqual(_clones(client, ticker="SOFI"), [])
        self.assertEqual(_verdicts(client, sofi["id"], "accepted"), [])


# ---------------------------------------------------------------------------
# Blocker 15 — three-cohort count conservation
# ---------------------------------------------------------------------------

class TestThreeCohortConservation(_EnvRawOn):
    def _seed_three(self, client, sources):
        client.tables["trade_suggestions"] = [copy.deepcopy(s) for s in sources]
        client.tables["policy_lab_cohorts"] = [
            {"id": "c-agg", "user_id": UID, "cohort_name": "aggressive",
             "portfolio_id": "pf-agg", "is_active": True},
            {"id": "c-neu", "user_id": UID, "cohort_name": "neutral",
             "portfolio_id": "pf-neu", "is_active": True},
            {"id": "c-con", "user_id": UID, "cohort_name": "conservative",
             "portfolio_id": "pf-con", "is_active": True},
        ]
        client.tables["paper_portfolios"] = [
            {"id": "pf-agg", "cash_balance": 2000, "net_liq": 2000},
            {"id": "pf-neu", "cash_balance": 10000, "net_liq": 10000},
            {"id": "pf-con", "cash_balance": 10000, "net_liq": 10000},
        ]
        client.tables["paper_positions"] = []

    def _run_three(self, client):
        cfgs = {
            "aggressive": PolicyConfig(),
            "neutral": PolicyConfig(min_score_threshold=0.0),
            "conservative": PolicyConfig(min_score_threshold=64.0),
        }
        with patch.object(fork_mod, "is_policy_lab_enabled", lambda: True), \
             patch.object(fork_mod, "load_cohort_configs", lambda *_a, **_k: cfgs), \
             patch.object(fork_mod, "get_current_champion",
                          lambda *_a, **_k: "aggressive"):
            return fork_mod.fork_suggestions_for_cohorts(UID, client)

    def _invariant(self, c):
        return (c["source_cohort_attempts"] ==
                c["accepted"] + c["refused"] + c["clone_failed"]
                + c["identity_mismatch"] + c["accepted_verdict_failed"]
                + c["cohort_binding_unavailable"] + c["cohort_identity_missing"]
                + c["cohort_portfolio_missing"] + c["cohort_capital_invalid"])

    def test_three_cohort_dispositions_and_reconciliation(self):
        # both_ok: score 65 → accepted by neutral(0) AND conservative(64)
        both_ok = _prerejected_sofi()
        both_ok["sizing_metadata"]["score"] = 65.0
        # split: score 60 → accepted by neutral, refused by conservative
        split = _prerejected_sofi()
        split.update({"id": str(uuid.uuid4()), "ticker": "PLTR",
                      "legs_fingerprint": "fp-pltr",
                      "trace_id": str(uuid.uuid4())})
        split["sizing_metadata"]["score"] = 60.0
        client = FakeSupabase()
        self._seed_three(client, [_pending_qqq(), both_ok, split])
        res = self._run_three(client)
        c = res["prerejection_counts"]

        # 2 non-champion cohorts × 2 sources = 4 attempts
        self.assertEqual(c["source_cohort_attempts"], 4)
        self.assertEqual(res["prerejection_source_rows"], 2)
        self.assertTrue(self._invariant(c), c)
        # accepted: both_ok×2 + split×neutral = 3 ; refused: split×conservative = 1
        self.assertEqual(c["accepted"], 3)
        self.assertEqual(c["refused"], 1)
        self.assertEqual(c["accepted_verdicts"], 3)
        # prerejection clones: both_ok in neutral+conservative, split in
        # neutral = 3 (the NORMAL-clone path also mints QQQ champion clones,
        # counted separately — assert the prerej set specifically)
        prerej_clones = [r for r in client.tables["trade_suggestions"]
                         if r.get("blocked_reason") == "shadow_prerejection_fork"]
        self.assertEqual(len(prerej_clones), 3)
        self.assertEqual(res["status"], "ok")

    def test_three_cohort_verdict_failure_then_repair(self):
        both_ok = _prerejected_sofi()
        both_ok["sizing_metadata"]["score"] = 65.0
        client = FakeSupabase()
        self._seed_three(client, [_pending_qqq(), both_ok])
        client.raise_when("policy_decisions", "upsert")
        res1 = self._run_three(client)
        self.assertEqual(res1["status"], "partial")
        c1 = res1["prerejection_counts"]
        self.assertEqual(c1["accepted_verdict_failed"], 2)  # neutral + conservative
        self.assertTrue(self._invariant(c1), c1)
        self.assertEqual(_verdicts(client, both_ok["id"], "accepted"), [])

        client.clear_hooks()
        res2 = self._run_three(client)
        self.assertEqual(res2["status"], "ok")
        c2 = res2["prerejection_counts"]
        self.assertEqual(c2["repaired"], 2)
        self.assertEqual(c2["existing"], 2)          # no duplicate clones
        self.assertEqual(len(_verdicts(client, both_ok["id"], "accepted")), 2)
        self.assertEqual(c2["accepted_verdicts"], 2)
        self.assertTrue(self._invariant(c2), c2)


if __name__ == "__main__":
    unittest.main()
