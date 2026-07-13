"""E19-2 (2026-07-13) — pre-rejection fork source + EV basis + champion fence.

THE DEFECT (route-proven in TestDefectReproduction): a candidate that passes
raw eligibility but dies at the CALIBRATED edge floor is stamped
status=NOT_EXECUTABLE / blocked_reason='edge_below_minimum'
(workflow_orchestrator raev<=-999 seam) — and fork_suggestions_for_cohorts
selected only status IN ('pending','staged'), so the raw-EV shadow experiment
never observed exactly the divergence cases it exists to measure (the
2026-07-13 SOFI exhibit: ev_raw 30.73 clears the $15 edge, calibrated ev 15.37
does not, raev=-999 → zero clones).

§9 discipline: every route test drives fork_suggestions_for_cohorts itself
through a faithful fake supabase (filter semantics implemented, writes
recorded). The champion fence is a golden effect-set comparison. One failure
is injected at its real query origin (the pre-rejection SELECT raising) and
asserted at the route's typed return.
"""
import os
import unittest
from unittest.mock import patch

from packages.quantum.policy_lab import fork as fork_mod
from packages.quantum.policy_lab.config import PolicyConfig


# ---------------------------------------------------------------------------
# Faithful fake supabase: filter semantics + write capture
# ---------------------------------------------------------------------------

class _Q:
    def __init__(self, client, table):
        self._c = client
        self._t = table
        self._filters = []
        self._op = None
        self._payload = None
        self._limit = None
        self._single = False
        self._count = None

    # -- builders -----------------------------------------------------------
    def select(self, *_a, **kw):
        self._op = self._op or "select"
        self._count = kw.get("count")
        return self

    def insert(self, rows):
        self._op, self._payload = "insert", rows
        return self

    def update(self, values):
        self._op, self._payload = "update", values
        return self

    def upsert(self, rows, on_conflict=None):
        self._op, self._payload = "upsert", rows
        return self

    def eq(self, col, val):
        self._filters.append(("eq", col, val))
        return self

    def is_(self, col, val):
        self._filters.append(("is", col, val))
        return self

    def in_(self, col, vals):
        self._filters.append(("in", col, list(vals)))
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def single(self):
        self._single = True
        return self

    # -- execution ----------------------------------------------------------
    def _match(self, row):
        for kind, col, val in self._filters:
            v = row.get(col)
            if kind == "eq" and v != val:
                return False
            if kind == "is" and val == "null" and v is not None:
                return False
            if kind == "in" and v not in val:
                return False
        return True

    def execute(self):
        if self._t in self._c.raise_on_select and self._op == "select":
            raise RuntimeError(f"injected origin failure on {self._t}")
        rows = self._c.tables.setdefault(self._t, [])
        if self._op == "select":
            out = [r for r in rows if self._match(r)]
            if self._limit is not None:
                out = out[: self._limit]

            class _R:
                pass

            r = _R()
            r.data = (out[0] if out else {}) if self._single else out
            r.count = len(out) if self._count else None
            return r
        if self._op == "insert":
            payload = self._payload if isinstance(self._payload, list) else [self._payload]
            for row in payload:
                rows.append(dict(row))
            self._c.writes.setdefault(self._t, []).append(("insert", payload))
        elif self._op == "update":
            for row in rows:
                if self._match(row):
                    row.update(self._payload)
            self._c.writes.setdefault(self._t, []).append(
                ("update", self._payload, list(self._filters)))
        elif self._op == "upsert":
            self._c.writes.setdefault(self._t, []).append(("upsert", self._payload))

        class _R2:
            data = [{}]
            count = None
        return _R2()


class FakeSupabase:
    def __init__(self):
        self.tables = {}
        self.writes = {}
        self.raise_on_select = set()

    def table(self, name):
        return _Q(self, name)


# ---------------------------------------------------------------------------
# Fixtures — today's live shapes
# ---------------------------------------------------------------------------

UID = "u-test"


def _pending_qqq(sid="src-qqq"):
    """The champion's executable IC (today's 16:00Z shape)."""
    return {
        "id": sid, "user_id": UID, "window": "midday_entry",
        "cycle_date": fork_mod.date.today().isoformat(),
        "ticker": "QQQ", "strategy": "IRON_CONDOR", "direction": "neutral",
        "status": "pending", "cohort_name": None,
        "ev": 18.61, "ev_raw": 37.22, "risk_adjusted_ev": 0.045881,
        "legs_fingerprint": "fp-qqq",
        "order_json": {"contracts": 1, "legs": [
            {"symbol": "QQQ_C1", "side": "sell", "quantity": 1, "mid": 1.0},
            {"symbol": "QQQ_C2", "side": "buy", "quantity": 1, "mid": 0.5},
        ]},
        "sizing_metadata": {"score": 72.0, "contracts": 1, "max_loss_total": 372.0},
    }


def _prerejected_sofi(sid="src-sofi", ev_raw=30.73):
    """The calibrated-rejected exhibit (today's 15:02Z SOFI shape)."""
    return {
        "id": sid, "user_id": UID, "window": "midday_entry",
        "cycle_date": fork_mod.date.today().isoformat(),
        "ticker": "SOFI", "strategy": "LONG_CALL_DEBIT_SPREAD", "direction": "long",
        "status": "NOT_EXECUTABLE", "blocked_reason": "edge_below_minimum",
        "cohort_name": None,
        "ev": 15.37, "ev_raw": ev_raw, "risk_adjusted_ev": -999.0,
        "legs_fingerprint": "fp-sofi",
        "order_json": {"contracts": 1, "legs": [
            {"symbol": "SOFI_C1", "side": "buy", "quantity": 1, "mid": 0.6},
            {"symbol": "SOFI_C2", "side": "sell", "quantity": 1, "mid": 0.3},
        ]},
        "sizing_metadata": {"score": 65.0, "contracts": 1, "max_loss_total": 60.0},
    }


def _quality_blocked(sid="src-dark"):
    """Stale/dark/unpriceable class — must NEVER be resurrected."""
    return {
        **_prerejected_sofi(sid=sid),
        "ticker": "XLE",
        "blocked_reason": "marketdata_quality_gate",
        "legs_fingerprint": "fp-xle",
    }


def _seed(client, *suggestion_rows):
    client.tables["trade_suggestions"] = [dict(r) for r in suggestion_rows]
    client.tables["policy_lab_cohorts"] = [
        {"user_id": UID, "cohort_name": "aggressive", "portfolio_id": "pf-agg",
         "id": "c-agg", "is_active": True},
        {"user_id": UID, "cohort_name": "neutral", "portfolio_id": "pf-neu",
         "id": "c-neu", "is_active": True},
    ]
    client.tables["paper_portfolios"] = [
        {"id": "pf-agg", "cash_balance": 2000, "net_liq": 2000},
        {"id": "pf-neu", "cash_balance": 10000, "net_liq": 10000},
    ]
    client.tables["paper_positions"] = []


def _run_fork(client):
    with patch.object(fork_mod, "is_policy_lab_enabled", return_value=True), \
         patch.object(fork_mod, "load_cohort_configs", return_value={
             "aggressive": PolicyConfig(),
             "neutral": PolicyConfig(min_score_threshold=0.0),
         }), \
         patch.object(fork_mod, "get_current_champion", return_value="aggressive"):
        return fork_mod.fork_suggestions_for_cohorts(UID, client)


def _clones(client, **field_filters):
    rows = client.tables.get("trade_suggestions", [])
    out = [r for r in rows if r.get("cohort_name") == "neutral"]
    for k, v in field_filters.items():
        out = [r for r in out if r.get(k) == v]
    return out


class _EnvRawOn(unittest.TestCase):
    def setUp(self):
        os.environ.pop("SHADOW_RAW_EV_ENABLED", None)  # default ON

    def tearDown(self):
        os.environ.pop("SHADOW_RAW_EV_ENABLED", None)


# ---------------------------------------------------------------------------
# Defect reproduction (against the OLD selection semantics)
# ---------------------------------------------------------------------------

class TestDefectReproduction(_EnvRawOn):
    def test_prerejected_source_produces_shadow_verdict_now(self):
        """OLD behavior (current main): the SOFI row is invisible to the fork
        (status filter) → 0 clones, 0 verdicts. NEW behavior: exactly one
        NOT_EXECUTABLE raw-basis clone + one decision row is retained, while
        the champion still rejects it."""
        client = FakeSupabase()
        _seed(client, _pending_qqq(), _prerejected_sofi())
        res = _run_fork(client)

        self.assertEqual(res["status"], "ok")
        sofi_clones = _clones(client, ticker="SOFI")
        self.assertEqual(len(sofi_clones), 1)
        c = sofi_clones[0]
        # champion rejection preserved on the SOURCE row
        src = [r for r in client.tables["trade_suggestions"]
               if r.get("id") == "src-sofi"][0]
        self.assertEqual(src["status"], "NOT_EXECUTABLE")
        self.assertEqual(src["blocked_reason"], "edge_below_minimum")
        # exactly one verdict row for the pre-rejection source
        verdicts = [row for op, payload in client.writes.get("policy_decisions", [])
                    if op == "upsert"
                    for row in payload if row["suggestion_id"] == "src-sofi"]
        self.assertEqual(len(verdicts), 1)
        self.assertEqual(verdicts[0]["decision"], "accepted")
        self.assertIn("prerejection_shadow_observation", verdicts[0]["reason_codes"])
        self.assertEqual(verdicts[0]["features_snapshot"]["ev_raw"], 30.73)
        self.assertEqual(verdicts[0]["features_snapshot"]["blocked_reason"],
                         "edge_below_minimum")


# ---------------------------------------------------------------------------
# Clone invariants
# ---------------------------------------------------------------------------

class TestPrerejectionCloneInvariants(_EnvRawOn):
    def _clone(self):
        client = FakeSupabase()
        _seed(client, _pending_qqq(), _prerejected_sofi())
        _run_fork(client)
        return client, _clones(client, ticker="SOFI")[0]

    def test_clone_is_not_executable_and_cannot_reach_submit(self):
        client, c = self._clone()
        self.assertEqual(c["status"], "NOT_EXECUTABLE")
        self.assertEqual(c["blocked_reason"], "shadow_prerejection_fork")
        # The executor's selection predicate (status='pending') — driven
        # against the same store — must NOT see it.
        exec_visible = _Q(client, "trade_suggestions").select("*") \
            .eq("user_id", UID).eq("cohort_name", "neutral") \
            .eq("status", "pending").execute().data
        self.assertNotIn("SOFI", [r.get("ticker") for r in exec_visible])

    def test_explicit_raw_basis_persisted_and_readable(self):
        _, c = self._clone()
        self.assertEqual(c["ev"], 30.73)
        self.assertEqual(c["ev_raw"], 30.73)
        sz = c["sizing_metadata"]
        self.assertEqual(sz["ev_basis"], "raw")
        self.assertIn(sz["raev_basis"],
                      ("raw_portfolio_blind", "unknown_recompute_failed"))
        self.assertTrue(sz["prerejection_fork"])
        self.assertEqual(sz["champion_blocked_reason"], "edge_below_minimum")
        self.assertEqual(sz["source_suggestion_id"], "src-sofi")
        # raev recomputed on the clone's own basis — never the champion's -999
        self.assertNotEqual(c["risk_adjusted_ev"], -999.0)

    def test_source_identity_and_fingerprint_namespace(self):
        _, c = self._clone()
        self.assertTrue(c["legs_fingerprint"].endswith("_prerej_neutral"))
        self.assertNotEqual(c["trace_id"],
                            _prerejected_sofi().get("trace_id"))


# ---------------------------------------------------------------------------
# Exclusions: what must NOT be resurrected / cloned
# ---------------------------------------------------------------------------

class TestExclusions(_EnvRawOn):
    def test_quality_gate_rejects_never_cloned(self):
        """Stale/dark/malformed/unpriceable candidates carry
        blocked_reason='marketdata_quality_gate' (or never became rows at
        all) — no clone, ever."""
        client = FakeSupabase()
        _seed(client, _pending_qqq(), _quality_blocked())
        _run_fork(client)
        self.assertEqual(_clones(client, ticker="XLE"), [])

    def test_missing_ev_raw_is_typed_refusal_never_default(self):
        client = FakeSupabase()
        _seed(client, _pending_qqq(), _prerejected_sofi(ev_raw=None))
        _run_fork(client)
        self.assertEqual(_clones(client, ticker="SOFI"), [])
        verdicts = [row for op, payload in client.writes.get("policy_decisions", [])
                    if op == "upsert"
                    for row in payload if row["suggestion_id"] == "src-sofi"]
        self.assertEqual(len(verdicts), 1)
        self.assertEqual(verdicts[0]["decision"], "rejected")
        self.assertEqual(verdicts[0]["reason_codes"], ["missing_ev_basis"])

    def test_lever_off_disables_prerejection_source(self):
        os.environ["SHADOW_RAW_EV_ENABLED"] = "0"
        client = FakeSupabase()
        _seed(client, _pending_qqq(), _prerejected_sofi())
        _run_fork(client)
        self.assertEqual(_clones(client, ticker="SOFI"), [])


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

class TestIdempotency(_EnvRawOn):
    def test_second_run_creates_no_duplicates(self):
        client = FakeSupabase()
        _seed(client, _pending_qqq(), _prerejected_sofi())
        _run_fork(client)
        n_after_first = len(client.tables["trade_suggestions"])
        _run_fork(client)
        self.assertEqual(len(client.tables["trade_suggestions"]), n_after_first)
        self.assertEqual(len(_clones(client, ticker="SOFI")), 1)
        self.assertEqual(len(_clones(client, ticker="QQQ")), 1)


# ---------------------------------------------------------------------------
# Champion fence — golden effect-set
# ---------------------------------------------------------------------------

class TestChampionFence(_EnvRawOn):
    #: every key the legacy clone shape carried (from current-main
    #: _clone_suggestion_for_cohort) + the ONLY sanctioned additions.
    LEGACY_CLONE_KEYS = {
        "user_id", "window", "ticker", "strategy", "direction", "status",
        "ev", "risk_adjusted_ev", "max_loss_total", "order_json",
        "sizing_metadata", "cohort_name", "cycle_date", "legs_fingerprint",
        "trace_id", "model_version", "features_hash", "regime",
        "decision_lineage", "lineage_hash", "agent_signals", "agent_summary",
        "created_at",
    }
    SANCTIONED_NEW_KEYS = {"ev_raw"}

    def test_champion_effects_identical_without_prerejection_rows(self):
        """Golden: with NO pre-rejection rows present, the fork's observable
        effect-set matches current-main behavior — champion tagging touches
        exactly the pending source ids, the normal clone set is unchanged in
        count/status/ordering inputs, and no pre-rejection artifacts appear."""
        client = FakeSupabase()
        _seed(client, _pending_qqq())
        res = _run_fork(client)

        self.assertEqual(res["status"], "ok")
        self.assertNotIn("prerejection_error", res)
        # champion tag update hit exactly the pending source id
        tag_updates = [w for w in client.writes.get("trade_suggestions", [])
                       if w[0] == "update"]
        self.assertEqual(len(tag_updates), 1)
        self.assertEqual(tag_updates[0][1], {"cohort_name": "aggressive"})
        self.assertIn(("eq", "id", "src-qqq"), tag_updates[0][2])
        # source row itself: tagged champion, still pending, EV fields untouched
        src = [r for r in client.tables["trade_suggestions"] if r.get("id") == "src-qqq"][0]
        self.assertEqual(
            (src["status"], src["ev"], src["ev_raw"], src["risk_adjusted_ev"],
             src["cohort_name"]),
            ("pending", 18.61, 37.22, 0.045881, "aggressive"))
        # exactly one neutral clone, status pending (legacy behavior)
        clones = _clones(client)
        self.assertEqual(len(clones), 1)
        self.assertEqual(clones[0]["status"], "pending")
        # no key drift beyond the sanctioned additive provenance
        drift = set(clones[0].keys()) - self.LEGACY_CLONE_KEYS - self.SANCTIONED_NEW_KEYS
        self.assertEqual(drift, set(), f"unsanctioned clone keys: {drift}")
        # created summary carries no prerejection bucket when none exist
        self.assertNotIn("neutral_prerejection", res["created"])

    def test_champion_effects_identical_WITH_prerejection_rows(self):
        """The pre-rejection source must not perturb ANY champion-side
        effect: same tag updates, same source-row state, same normal-clone
        count as the golden run."""
        client = FakeSupabase()
        _seed(client, _pending_qqq(), _prerejected_sofi())
        _run_fork(client)
        tag_updates = [w for w in client.writes.get("trade_suggestions", [])
                       if w[0] == "update"]
        self.assertEqual(len(tag_updates), 1)          # never tags NOT_EXECUTABLE
        self.assertIn(("eq", "id", "src-qqq"), tag_updates[0][2])
        src_sofi = [r for r in client.tables["trade_suggestions"]
                    if r.get("id") == "src-sofi"][0]
        self.assertIsNone(src_sofi.get("cohort_name"))  # source stays untagged
        self.assertEqual(len(_clones(client, status="pending")), 1)  # QQQ only

    def test_already_champion_eligible_no_duplicate_no_alteration(self):
        client = FakeSupabase()
        _seed(client, _pending_qqq())
        _run_fork(client)
        agg_rows = [r for r in client.tables["trade_suggestions"]
                    if r.get("cohort_name") == "aggressive"]
        self.assertEqual(len(agg_rows), 1)              # tagged in place, never cloned
        self.assertEqual(agg_rows[0]["id"], "src-qqq")


# ---------------------------------------------------------------------------
# Origin-injected failure → typed truth at the route return
# ---------------------------------------------------------------------------

class TestOriginFailureTyped(_EnvRawOn):
    def test_prerejection_query_failure_is_typed_and_champion_unaffected(self):
        """Inject the failure at the REAL query origin (the second SELECT
        raising). The route must return a TYPED prerejection_error while the
        champion path completes identically — never a silent empty."""
        client = FakeSupabase()
        _seed(client, _pending_qqq(), _prerejected_sofi())

        real_table = client.table
        calls = {"n": 0}

        def flaky_table(name):
            q = real_table(name)
            if name == "trade_suggestions":
                calls["n"] += 1
                if calls["n"] == 2:  # 1st = pending source; 2nd = pre-rejection
                    client.raise_on_select.add("trade_suggestions")
                else:
                    client.raise_on_select.discard("trade_suggestions")
            return q

        client.table = flaky_table
        res = _run_fork(client)
        client.raise_on_select.discard("trade_suggestions")

        self.assertEqual(res["status"], "ok")
        self.assertIn("prerejection_error", res)
        self.assertIn("RuntimeError", res["prerejection_error"])
        # champion effects intact
        src = [r for r in client.tables["trade_suggestions"] if r.get("id") == "src-qqq"][0]
        self.assertEqual(src["cohort_name"], "aggressive")
        self.assertEqual(len(_clones(client, ticker="QQQ")), 1)
        # and no SOFI artifacts
        self.assertEqual(_clones(client, ticker="SOFI"), [])


if __name__ == "__main__":
    unittest.main()
