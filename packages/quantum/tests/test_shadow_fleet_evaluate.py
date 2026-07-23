"""Unit tests for the recurring independent shadow-fleet evaluator (C1).

Covers: dark no-op (enqueue + child), fail-closed reads, the ONE-universe
50-policy load path, idempotent replay, per-policy failure isolation, typed
dispositions, no-provider/no-broker isolation, and byte-identity of the filter
precedence with the parent Policy-Lab fork.
"""

from pathlib import Path

import pytest

from packages.quantum.services import shadow_fleet_evaluate as sfe
from packages.quantum.services.shadow_fleet_evaluate import (
    FleetPolicyEvidenceWriter,
    PolicyDecision,
    UniverseUnavailable,
    build_candidate_universe,
    evaluate_policy,
    load_fleet_readiness,
    maybe_enqueue_fleet_policy_eval,
    run_fleet_policy_eval,
)

USER = "44444444-4444-4444-4444-444444444444"
DECISION = "33333333-3333-3333-3333-333333333333"
JOB_RUN = "22222222-2222-2222-2222-222222222222"
FLEET_ID = "11111111-1111-1111-1111-111111111111"
AS_OF = "2026-07-23T16:00:00+00:00"


# ─────────────────────────────────────────────────────────────────────────────
# Fake read-only client for the readiness-ordering tests.
# ─────────────────────────────────────────────────────────────────────────────
class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, table, owner):
        self._table = table
        self._owner = owner

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def is_(self, *a, **k):
        return self

    def execute(self):
        return _Resp(list(self._owner.tables.get(self._table, [])))


class FakeReadClient:
    """Records which tables were queried; returns canned rows per table."""

    def __init__(self, tables):
        self.tables = tables
        self.touched = []

    def table(self, name):
        self.touched.append(name)
        return _Query(name, self)


APPROVED_POLICY = {
    "policy_registration_id": "aggressive_anchor",
    "effective_epoch": "small_tier_v1",
    "approval_status": "approved",
    "config_hash": "a" * 64,
    "schema_version": 1,
    "policy_config": {
        "max_risk_pct_per_trade": 0.035,
        "risk_multiplier": 1.2,
        "sizing_method": "budget_proportional",
        "budget_cap_pct": 0.35,
        "max_suggestions_per_day": 4,
        "min_score_threshold": 30.0,
        "max_positions_open": 4,
        "stop_loss_pct": 0.30,
        "target_profit_pct": 0.50,
        "max_dte_to_enter": 45,
        "min_dte_to_exit": 7,
    },
}


def test_readiness_inactive_fleet_reads_only_status_table():
    client = FakeReadClient(
        {"shadow_fleets": [{"id": FLEET_ID, "user_id": USER, "status": "pending_legacy_terminal"}]}
    )
    result = load_fleet_readiness(client, USER)
    assert result["status"] == "fleet_inactive"
    assert result["ready"] is False
    assert result["errors"] == 0
    assert result["accounts"] == []
    # Readiness read FIRST: no micro-account / policy read happened.
    assert client.touched == ["shadow_fleets"]


def test_readiness_absent_fleet_is_typed_noop():
    client = FakeReadClient({"shadow_fleets": []})
    result = load_fleet_readiness(client, USER)
    assert result["status"] == "fleet_absent"
    assert result["ready"] is False
    assert client.touched == ["shadow_fleets"]


def test_readiness_active_but_unbound_is_noop():
    client = FakeReadClient(
        {
            "shadow_fleets": [{"id": FLEET_ID, "user_id": USER, "status": "active"}],
            "shadow_micro_accounts": [
                {"id": "m1", "fleet_id": FLEET_ID, "slot_number": 1, "policy_registration_id": None, "state": "active", "initial_cash": 2000},
            ],
        }
    )
    result = load_fleet_readiness(client, USER)
    assert result["status"] == "no_active_bound_accounts"
    assert result["accounts"] == []


def test_readiness_active_bound_returns_accounts():
    client = FakeReadClient(
        {
            "shadow_fleets": [{"id": FLEET_ID, "user_id": USER, "status": "active"}],
            "shadow_micro_accounts": [
                {"id": "m1", "fleet_id": FLEET_ID, "slot_number": 1, "policy_registration_id": "aggressive_anchor", "state": "active", "initial_cash": 2000},
            ],
            "policy_registrations": [APPROVED_POLICY],
        }
    )
    result = load_fleet_readiness(client, USER)
    assert result["ready"] is True
    assert len(result["accounts"]) == 1
    acct = result["accounts"][0]
    assert acct["policy_registration_id"] == "aggressive_anchor"
    assert acct["deployable_capital"] == 2000.0


def test_readiness_fleet_read_failure_fails_closed():
    class Boom(FakeReadClient):
        def table(self, name):
            raise RuntimeError("connection reset")

    result = load_fleet_readiness(Boom({}), USER)
    assert result["status"] == "fleet_read_failed"
    assert result["ready"] is False
    assert result["errors"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Enqueue seam
# ─────────────────────────────────────────────────────────────────────────────
def _inactive_readiness(*a, **k):
    return {"status": "fleet_inactive", "ready": False, "errors": 0, "accounts": []}


def _ready_readiness(*a, **k):
    return {
        "status": "ready",
        "ready": True,
        "errors": 0,
        "fleet_id": FLEET_ID,
        "accounts": [
            {
                "shadow_micro_account_id": "m1",
                "fleet_id": FLEET_ID,
                "slot_number": 1,
                "portfolio_id": "p1",
                "policy_registration_id": "aggressive_anchor",
                "policy_config": APPROVED_POLICY["policy_config"],
                "deployable_capital": 2000.0,
            }
        ],
    }


def test_enqueue_is_true_noop_when_fleet_inactive():
    calls = []
    result = maybe_enqueue_fleet_policy_eval(
        object(),
        user_id=USER,
        source_job_run_id=None,
        source_decision_id=None,
        source_code_sha=None,
        as_of=None,
        parent_origin=None,
        readiness_loader=_inactive_readiness,
        enqueue_fn=lambda **kw: calls.append(kw),
    )
    assert result == {"status": "fleet_inactive", "enqueued": False, "errors": 0}
    assert calls == []


def test_enqueue_read_failure_fails_closed_no_enqueue():
    calls = []
    result = maybe_enqueue_fleet_policy_eval(
        object(),
        user_id=USER,
        source_job_run_id=JOB_RUN,
        source_decision_id=DECISION,
        source_code_sha="b" * 40,
        as_of=AS_OF,
        parent_origin="scheduler",
        readiness_loader=lambda *a, **k: {"status": "fleet_read_failed", "ready": False, "errors": 1},
        enqueue_fn=lambda **kw: calls.append(kw),
    )
    assert result["status"] == "fleet_read_failed"
    assert result["enqueued"] is False
    assert result["errors"] == 1
    assert calls == []


def test_operator_or_forced_parent_cannot_enqueue():
    calls = []
    result = maybe_enqueue_fleet_policy_eval(
        object(),
        user_id=USER,
        source_job_run_id=JOB_RUN,
        source_decision_id=DECISION,
        source_code_sha="b" * 40,
        as_of=AS_OF,
        parent_origin="operator_signed_endpoint",
        readiness_loader=_ready_readiness,
        enqueue_fn=lambda **kw: calls.append(kw),
    )
    assert result["status"] == "non_natural_parent"
    assert result["enqueued"] is False
    assert calls == []


def test_natural_parent_enqueues_one_attributable_child():
    calls = []

    def enqueue(**kw):
        calls.append(kw)
        return {"job_run_id": "66666666-6666-6666-6666-666666666666", "rq_job_id": "rq-1", "status": "queued"}

    def origin(event, **kw):
        return {"origin": "event", "trigger_actor_class": event, **kw}

    result = maybe_enqueue_fleet_policy_eval(
        object(),
        user_id=USER,
        source_job_run_id=JOB_RUN,
        source_decision_id=DECISION,
        source_code_sha="b" * 40,
        as_of=AS_OF,
        parent_origin="scheduler",
        readiness_loader=_ready_readiness,
        enqueue_fn=enqueue,
        origin_builder=origin,
    )
    assert result["enqueued"] is True
    assert result["errors"] == 0
    assert len(calls) == 1
    call = calls[0]
    assert call["job_name"] == "shadow_fleet_evaluate"
    assert call["idempotency_key"] == f"shadow_fleet_evaluate:{DECISION}:small_tier_v1"
    assert call["queue_name"] == "background"
    assert call["payload"]["source_decision_id"] == DECISION
    assert call["origin"]["parent_job_run_id"] == JOB_RUN


# ─────────────────────────────────────────────────────────────────────────────
# Child body: universe, dispositions, load, isolation, idempotency
# ─────────────────────────────────────────────────────────────────────────────
class FakeWriter:
    instances = []

    def __init__(self, *a, **k):
        self.kwargs = k
        self.run_id = f"run-{k['shadow_micro_account_id']}"
        self.decisions = []
        self.finished = None
        self._counters = {"runs_started": 0, "decisions_written": 0, "write_failures": 0, "table_missing_noops": 0, "duplicate_acks": 0}
        type(self).instances.append(self)

    def begin_run(self):
        self._counters["runs_started"] = 1
        return self.run_id

    def record_decision(self, decision, **k):
        self.decisions.append(decision)
        self._counters["decisions_written"] += 1
        return True

    def finish_run(self, *, status, counts=None, error_details=None):
        self.finished = {"status": status, "counts": counts}
        return True

    def counters_dict(self):
        return dict(self._counters)


def _accounts(n):
    return [
        {
            "shadow_micro_account_id": f"m{i}",
            "fleet_id": FLEET_ID,
            "slot_number": i,
            "portfolio_id": f"p{i}",
            "policy_registration_id": f"pol_{i}",
            "policy_config": APPROVED_POLICY["policy_config"],
            "deployable_capital": 2000.0,
        }
        for i in range(1, n + 1)
    ]


def _readiness_with(accounts):
    def loader(*a, **k):
        return {"status": "ready", "ready": True, "errors": 0, "fleet_id": FLEET_ID, "accounts": accounts}

    return loader


def _universe(n):
    # Small, affordable structures. Aggressive anchor max_risk = 2000*0.035*1.2
    # = $84, so a $50-max-loss structure affords 1 contract at the $2k tier.
    return [
        {
            "id": f"cand-{i}",
            "sizing_metadata": {"score": 80.0, "max_loss_total": 50.0},
            "order_json": {"contracts": 1},
            "ev": 25.0,
            "ev_raw": 25.0,
        }
        for i in range(1, n + 1)
    ]


def _payload():
    return {
        "user_id": USER,
        "source_job_run_id": JOB_RUN,
        "source_decision_id": DECISION,
        "source_code_sha": "b" * 40,
        "source_as_of": AS_OF,
        "fleet_epoch": "small_tier_v1",
    }


def test_child_is_noop_when_readiness_not_ready():
    FakeWriter.instances = []
    calls = {"universe": 0}

    def spy_universe(client, decision_id):
        calls["universe"] += 1
        return []

    result = run_fleet_policy_eval(
        _payload(),
        client=object(),
        readiness_loader=_inactive_readiness,
        universe_builder=spy_universe,
        writer_factory=FakeWriter,
    )
    assert result["status"] == "fleet_inactive"
    assert result["counts"]["runs_written"] == 0
    assert FakeWriter.instances == []
    # The universe is never even read while inactive.
    assert calls["universe"] == 0


def test_fifty_policies_share_ONE_universe_read():
    FakeWriter.instances = []
    calls = {"universe": 0}
    uni = _universe(3)

    def spy_universe(client, decision_id):
        calls["universe"] += 1
        return uni

    result = run_fleet_policy_eval(
        _payload(),
        client=object(),
        readiness_loader=_readiness_with(_accounts(50)),
        universe_builder=spy_universe,
        writer_factory=FakeWriter,
    )
    # ONE universe read shared across all 50 policies (never 50 scans).
    assert calls["universe"] == 1
    assert result["status"] == "succeeded"
    assert result["counts"]["policies"] == 50
    assert result["counts"]["runs_written"] == 50
    assert len(FakeWriter.instances) == 50
    # 3 candidates x 50 policies = 150 decision rows.
    assert result["counts"]["decisions_written"] == 150
    # aggressive anchor (min_score 30, max_positions 4, max_suggestions 4):
    # all 3 affordable candidates selected per policy.
    assert result["counts"]["selected"] == 150


def test_universe_read_failure_is_data_unavailable_for_all():
    FakeWriter.instances = []

    def boom_universe(client, decision_id):
        raise UniverseUnavailable("trade_suggestions read failed")

    result = run_fleet_policy_eval(
        _payload(),
        client=object(),
        readiness_loader=_readiness_with(_accounts(5)),
        universe_builder=boom_universe,
        writer_factory=FakeWriter,
    )
    assert result["status"] == "partial"
    assert result["counts"]["data_unavailable_runs"] == 5
    assert result["counts"]["selected"] == 0
    assert all(w.finished["status"] == "data_unavailable" for w in FakeWriter.instances)


def test_empty_universe_is_no_candidate():
    FakeWriter.instances = []
    result = run_fleet_policy_eval(
        _payload(),
        client=object(),
        readiness_loader=_readiness_with(_accounts(4)),
        universe_builder=lambda c, d: [],
        writer_factory=FakeWriter,
    )
    assert result["status"] == "succeeded"
    assert result["counts"]["no_candidate_runs"] == 4
    assert result["counts"]["decisions_written"] == 0
    assert all(w.finished["status"] == "no_candidate" for w in FakeWriter.instances)


def test_per_policy_failure_isolation():
    FakeWriter.instances = []
    uni = _universe(2)

    # Inject a failure in ONE policy's evaluation via a poisoned config that
    # blows up PolicyConfig arithmetic — the other policies are untouched.
    accounts = _accounts(3)
    accounts[1]["policy_config"] = {"budget_cap_pct": "not-a-number", "min_score_threshold": 30.0}

    def flaky_eval(universe, policy_config, *, open_positions, deployable_capital):
        # Route the real evaluator but force one policy to raise.
        if policy_config.get("budget_cap_pct") == "not-a-number":
            raise ValueError("injected policy failure")
        return evaluate_policy(universe, policy_config, open_positions=open_positions, deployable_capital=deployable_capital)

    # Monkeypatch the module-level evaluate_policy used inside run().
    orig = sfe.evaluate_policy
    sfe.evaluate_policy = flaky_eval
    try:
        result = run_fleet_policy_eval(
            _payload(),
            client=object(),
            readiness_loader=_readiness_with(accounts),
            universe_builder=lambda c, d: uni,
            writer_factory=FakeWriter,
        )
    finally:
        sfe.evaluate_policy = orig

    assert result["status"] == "partial"
    assert result["counts"]["evaluator_failed_runs"] == 1
    assert result["counts"]["errors"] == 1
    # The other two policies produced real decisions.
    assert result["counts"]["policies"] == 3
    failed = [w for w in FakeWriter.instances if w.finished["status"] == "evaluator_failed"]
    ok = [w for w in FakeWriter.instances if w.finished["status"] == "succeeded"]
    assert len(failed) == 1
    assert len(ok) == 2


def test_capital_rejected_when_micro_account_cannot_afford():
    FakeWriter.instances = []
    # A structure whose per-contract max-loss ($3,000) exceeds the $2k tier.
    uni = [{"id": "big", "sizing_metadata": {"score": 90.0, "max_loss_total": 3000.0}, "order_json": {"contracts": 1}, "ev": 1, "ev_raw": 1}]
    result = run_fleet_policy_eval(
        _payload(),
        client=object(),
        readiness_loader=_readiness_with(_accounts(1)),
        universe_builder=lambda c, d: uni,
        writer_factory=FakeWriter,
    )
    assert result["counts"]["capital_rejected"] == 1
    assert result["counts"]["selected"] == 0
    d = FakeWriter.instances[0].decisions[0]
    assert d.disposition == "capital_rejected"
    assert d.reason_codes == ["insufficient_risk_budget"]


def test_missing_max_loss_basis_is_capital_rejected_not_fabricated():
    FakeWriter.instances = []
    uni = [{"id": "nomaxloss", "sizing_metadata": {"score": 90.0}, "order_json": {"contracts": 1}, "ev": 1, "ev_raw": 1}]
    result = run_fleet_policy_eval(
        _payload(),
        client=object(),
        readiness_loader=_readiness_with(_accounts(1)),
        universe_builder=lambda c, d: uni,
        writer_factory=FakeWriter,
    )
    d = FakeWriter.instances[0].decisions[0]
    assert d.disposition == "capital_rejected"
    assert d.reason_codes == ["max_loss_basis_unavailable"]


def test_missing_score_is_routing_decision_unavailable():
    decisions = evaluate_policy(
        [{"id": "x", "sizing_metadata": {}, "order_json": {"contracts": 1}}],
        APPROVED_POLICY["policy_config"],
        open_positions=0,
        deployable_capital=2000.0,
    )
    assert decisions[0].disposition == "policy_rejected"
    assert decisions[0].reason_codes == ["routing_decision_unavailable"]


# ─────────────────────────────────────────────────────────────────────────────
# Idempotent replay at the writer level (unique violation -> duplicate ack).
# ─────────────────────────────────────────────────────────────────────────────
class _DupTable:
    def __init__(self, owner, name):
        self._owner = owner
        self._name = name
        self._payload = None

    def insert(self, payload):
        self._payload = payload
        return self

    def update(self, payload):
        self._payload = payload
        return self

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        if self._name == "fleet_policy_decision_runs" and self._payload and self._payload.get("status") == "running":
            return _Resp([{"run_id": "run-1"}])
        if self._name == "fleet_policy_decisions":
            self._owner.decision_inserts += 1
            if self._owner.decision_inserts > 1:
                raise RuntimeError("duplicate key value violates unique constraint (23505)")
            return _Resp([{"id": "d1"}])
        return _Resp([{"run_id": "run-1"}])


class _DupClient:
    def __init__(self):
        self.decision_inserts = 0

    def table(self, name):
        return _DupTable(self, name)


def test_writer_idempotent_replay_is_duplicate_ack_not_crash():
    client = _DupClient()
    writer = FleetPolicyEvidenceWriter(
        client,
        fleet_id=FLEET_ID,
        fleet_epoch="small_tier_v1",
        shadow_micro_account_id="m1",
        policy_registration_id="pol_1",
        source_decision_id=DECISION,
        source_job_run_id=JOB_RUN,
        user_id=USER,
    )
    assert writer.begin_run() == "run-1"
    dec = PolicyDecision("cand-1", "selected", [], 1, 80.0, {"contracts": 1})
    assert writer.record_decision(dec) is True  # first insert
    assert writer.record_decision(dec) is True  # replay -> duplicate ack, no crash
    counters = writer.counters_dict()
    assert counters["decisions_written"] == 1
    assert counters["duplicate_acks"] == 1
    assert counters["write_failures"] == 0


def test_writer_table_missing_is_typed_noop():
    class _MissingTable:
        def __init__(self, name):
            self._name = name

        def insert(self, payload):
            return self

        def select(self, *a, **k):
            return self

        def eq(self, *a, **k):
            return self

        def limit(self, *a, **k):
            return self

        def execute(self):
            raise RuntimeError("Could not find the table 'public.fleet_policy_decision_runs' in the schema cache (PGRST205)")

    class _MissingClient:
        def table(self, name):
            return _MissingTable(name)

    writer = FleetPolicyEvidenceWriter(
        _MissingClient(),
        fleet_id=FLEET_ID,
        fleet_epoch="small_tier_v1",
        shadow_micro_account_id="m1",
        policy_registration_id="pol_1",
        source_decision_id=DECISION,
        source_job_run_id=JOB_RUN,
        user_id=USER,
    )
    assert writer.begin_run() is None
    assert writer.counters_dict()["table_missing_noops"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Universe builder: fail-closed vs honest-empty
# ─────────────────────────────────────────────────────────────────────────────
def test_universe_read_error_raises_not_empty():
    class Boom:
        def table(self, name):
            raise RuntimeError("network")

    with pytest.raises(UniverseUnavailable):
        build_candidate_universe(Boom(), DECISION)


def test_universe_excludes_fork_clones_and_sorts_by_score():
    rows = [
        {"id": "c-low", "sizing_metadata": {"score": 10.0}, "order_json": {}, "ev": 1, "ev_raw": 1},
        {"id": "c-high", "sizing_metadata": {"score": 90.0}, "order_json": {}, "ev": 1, "ev_raw": 1},
    ]

    class Client:
        def table(self, name):
            assert name == "trade_suggestions"
            return self

        def select(self, *a, **k):
            return self

        def eq(self, *a, **k):
            return self

        def is_(self, col, val):
            # The cohort_name IS NULL filter must be applied.
            assert (col, val) == ("cohort_name", "null")
            return self

        def execute(self):
            return _Resp(rows)

    universe = build_candidate_universe(Client(), DECISION)
    assert [c["id"] for c in universe] == ["c-high", "c-low"]  # score desc


# ─────────────────────────────────────────────────────────────────────────────
# Parent byte-identity: the filter precedence matches Policy-Lab fork exactly.
# ─────────────────────────────────────────────────────────────────────────────
def test_filter_precedence_byte_identical_to_fork():
    from packages.quantum.policy_lab.config import PolicyConfig
    from packages.quantum.policy_lab.fork import _evaluate_cohort_policy

    config = PolicyConfig.from_dict(
        {
            "max_positions_open": 2,
            "max_suggestions_per_day": 3,
            "min_score_threshold": 50.0,
            "max_risk_pct_per_trade": 0.03,
            "risk_multiplier": 1.0,
            "budget_cap_pct": 0.35,
        }
    )
    # Ordered so each branch is exercised BEFORE capacity is exhausted (capacity
    # binds first in fork, so any candidate after the 2nd accept is a capacity
    # rejection regardless of its score).
    suggestions = [
        {"id": "s1", "sizing_metadata": {"score": 90.0}},   # accepted (slot 1)
        {"id": "s2", "sizing_metadata": {}},                # missing score
        {"id": "s3", "sizing_metadata": {"score": 40.0}},   # score_below_min
        {"id": "s4", "sizing_metadata": {"score": 70.0}},   # accepted (slot 2)
        {"id": "s5", "sizing_metadata": {"score": 80.0}},   # capacity exhausted
    ]
    fork_decisions = _evaluate_cohort_policy(suggestions, config, open_positions=0)

    # Large capital so sizing NEVER capital-rejects -> 'selected' == fork accepted.
    universe = [dict(s, order_json={"contracts": 1}, sizing_metadata=dict(s["sizing_metadata"], max_loss_total=100.0)) for s in suggestions]
    mine = evaluate_policy(universe, config.to_dict(), open_positions=0, deployable_capital=1_000_000.0)

    fork_accepted = [d.suggestion_id for d in fork_decisions if d.accepted]
    mine_selected = [d.candidate_id for d in mine if d.disposition == "selected"]
    assert mine_selected == fork_accepted == ["s1", "s4"]

    # Rejection reasons line up candidate-for-candidate (score/capacity/missing).
    fork_reasons = {d.suggestion_id: d.reason_codes for d in fork_decisions if not d.accepted}
    mine_reasons = {d.candidate_id: d.reason_codes for d in mine if d.disposition != "selected"}
    assert mine_reasons == fork_reasons
    assert mine_reasons["s2"] == ["routing_decision_unavailable"]
    assert mine_reasons["s3"] == ["score_below_min"]
    assert mine_reasons["s5"] == ["daily_limit_reached"]


# ─────────────────────────────────────────────────────────────────────────────
# Isolation: no broker / no live-provider path is importable from the evaluator.
# ─────────────────────────────────────────────────────────────────────────────
def test_evaluator_imports_no_broker_or_live_provider():
    src = Path(sfe.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "place_option_order",
        "submit_to_broker",
        "alpaca_order_handler",
        "AlpacaClient",
        "MarketDataTruthLayer",
        "PolygonService",
        "snapshot_many",
        "option_chain",
    ):
        assert forbidden not in src, f"evaluator must not reference {forbidden}"
