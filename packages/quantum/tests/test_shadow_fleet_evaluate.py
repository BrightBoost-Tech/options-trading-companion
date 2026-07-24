"""Unit tests for the recurring independent shadow-fleet evaluator (C1, v2).

v2 universe = the COMPLETE, immutable scan-envelope set (every fully-constructed
candidate — emitted AND rejected-before-persistence), with the emitted subset
enriched by the real routing score + max-loss basis from trade_suggestions. This
suite drives the real routes and asserts at the top:

  * dark no-op (enqueue + child) and fail-closed reads
  * the capture-surface readiness gate (decoupled from the td SCORING flag)
  * v2 universe: rejected candidate present, champion subset no longer defines it,
    clones excluded, fingerprint dedup, distinct structures preserved, query
    scoped to the source decision (cross-user isolation)
  * one shared universe read for 50 policies + per-policy failure isolation
  * typed dispositions incl. candidate-grain data_unavailable (missing field,
    never fabricated)
  * idempotent replay, no-provider/no-broker isolation, byte-identity of the
    SCORED filter precedence with the parent Policy-Lab fork.
"""

from pathlib import Path

import pytest

from packages.quantum.services import shadow_fleet_evaluate as sfe
from packages.quantum.services.shadow_fleet_evaluate import (
    ENRICHMENT_TABLE,
    SCAN_ENVELOPE_TABLE,
    FleetPolicyEvidenceWriter,
    PolicyDecision,
    UniverseUnavailable,
    build_candidate_universe,
    build_trade_suggestions_universe,
    evaluate_policy,
    load_fleet_readiness,
    maybe_enqueue_fleet_policy_eval,
    run_fleet_policy_eval,
)
from packages.quantum.services.options_utils import compute_legs_fingerprint

USER = "44444444-4444-4444-4444-444444444444"
DECISION = "33333333-3333-3333-3333-333333333333"
JOB_RUN = "22222222-2222-2222-2222-222222222222"
FLEET_ID = "11111111-1111-1111-1111-111111111111"
AS_OF = "2026-07-23T16:00:00+00:00"

_ON = lambda: True  # capture-gate stub: surface enabled
_OFF = lambda: False


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
    # Readiness read FIRST: no micro-account / policy / envelope read happened.
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
    result = load_fleet_readiness(client, USER, capture_gate=_ON)
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
    result = load_fleet_readiness(client, USER, capture_gate=_ON)
    assert result["ready"] is True
    assert len(result["accounts"]) == 1
    acct = result["accounts"][0]
    assert acct["policy_registration_id"] == "aggressive_anchor"
    assert acct["deployable_capital"] == 2000.0


def test_readiness_requires_capture_surface():
    # ACTIVE + bound + approved, but the shared capture surface is OFF: readiness
    # is NOT ready (config gate, errors=0). Never a silent empty universe / champion
    # fallback. The gate runs LAST, so the fleet/micro/policy reads still happened.
    client = FakeReadClient(
        {
            "shadow_fleets": [{"id": FLEET_ID, "user_id": USER, "status": "active"}],
            "shadow_micro_accounts": [
                {"id": "m1", "fleet_id": FLEET_ID, "slot_number": 1, "policy_registration_id": "aggressive_anchor", "state": "active", "initial_cash": 2000},
            ],
            "policy_registrations": [APPROVED_POLICY],
        }
    )
    result = load_fleet_readiness(client, USER, capture_gate=_OFF)
    assert result["status"] == "capture_surface_disabled"
    assert result["ready"] is False
    assert result["errors"] == 0
    assert result["accounts"] == []


def test_readiness_capture_gate_fault_fails_closed():
    def boom_gate():
        raise RuntimeError("gate read blew up")

    client = FakeReadClient(
        {
            "shadow_fleets": [{"id": FLEET_ID, "user_id": USER, "status": "active"}],
            "shadow_micro_accounts": [
                {"id": "m1", "fleet_id": FLEET_ID, "slot_number": 1, "policy_registration_id": "aggressive_anchor", "state": "active", "initial_cash": 2000},
            ],
            "policy_registrations": [APPROVED_POLICY],
        }
    )
    result = load_fleet_readiness(client, USER, capture_gate=boom_gate)
    assert result["status"] == "capture_surface_disabled"
    assert result["ready"] is False


def test_readiness_fleet_read_failure_fails_closed():
    class Boom(FakeReadClient):
        def table(self, name):
            raise RuntimeError("connection reset")

    result = load_fleet_readiness(Boom({}), USER)
    assert result["status"] == "fleet_read_failed"
    assert result["ready"] is False
    assert result["errors"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Capture gate (decoupled from the td SCORING flag)
# ─────────────────────────────────────────────────────────────────────────────
def test_capture_gate_decoupled_from_td_scoring_flag(monkeypatch):
    from packages.quantum.services.td_scan_capture import (
        scan_candidate_capture_enabled,
        td_scan_observe_enabled,
    )

    # Neither flag -> OFF.
    monkeypatch.delenv("TERMINAL_DISTRIBUTION_SCAN_OBSERVE_ENABLED", raising=False)
    monkeypatch.delenv("SCAN_CANDIDATE_CAPTURE_ENABLED", raising=False)
    assert scan_candidate_capture_enabled() is False

    # Legacy td flag alone -> ON (backward-compatible with the old gate).
    monkeypatch.setenv("TERMINAL_DISTRIBUTION_SCAN_OBSERVE_ENABLED", "1")
    assert scan_candidate_capture_enabled() is True
    assert scan_candidate_capture_enabled() == td_scan_observe_enabled()

    # Stable capture flag ALONE (td scoring off) -> ON. The fleet does not depend
    # on td scoring staying enabled.
    monkeypatch.delenv("TERMINAL_DISTRIBUTION_SCAN_OBSERVE_ENABLED", raising=False)
    monkeypatch.setenv("SCAN_CANDIDATE_CAPTURE_ENABLED", "yes")
    assert td_scan_observe_enabled() is False
    assert scan_candidate_capture_enabled() is True


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


def test_capture_disabled_readiness_is_true_noop_at_enqueue():
    calls = []
    result = maybe_enqueue_fleet_policy_eval(
        object(),
        user_id=USER,
        source_job_run_id=JOB_RUN,
        source_decision_id=DECISION,
        source_code_sha="b" * 40,
        as_of=AS_OF,
        parent_origin="scheduler",
        readiness_loader=lambda *a, **k: {"status": "capture_surface_disabled", "ready": False, "errors": 0, "accounts": []},
        enqueue_fn=lambda **kw: calls.append(kw),
    )
    assert result["status"] == "capture_surface_disabled"
    assert result["enqueued"] is False
    assert result["errors"] == 0
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
        self.snapshots = []
        self.finished = None
        self._counters = {"runs_started": 0, "decisions_written": 0, "write_failures": 0, "table_missing_noops": 0, "duplicate_acks": 0}
        type(self).instances.append(self)

    def begin_run(self):
        self._counters["runs_started"] = 1
        return self.run_id

    def record_decision(self, decision, *, features_snapshot=None):
        self.decisions.append(decision)
        self.snapshots.append(features_snapshot)
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


def _cand(fp, *, score=80.0, max_loss=50.0, emitted=True, matched=True, suggestion_id=None):
    """A v2 universe candidate dict (post-join shape)."""
    return {
        "candidate_fingerprint": fp,
        "suggestion_id": suggestion_id or (f"sug-{fp}" if matched else None),
        "emitted": emitted,
        "matched_emitted": matched,
        "sizing_metadata": ({"score": score, "max_loss_total": max_loss} if matched else {}),
        "order_json": {"contracts": 1, "legs": [{"symbol": fp}]},
        "ev": 25.0,
        "ev_raw": 25.0,
        "symbol": "SPY",
        "strategy": "IC",
        "reject_reason": None if emitted else "unattributed_post_ev",
        "reject_gate": None if emitted else "post_ev_gate",
    }


def _universe(n):
    # Small, affordable emitted structures. Aggressive anchor max_risk =
    # 2000*0.035*1.2 = $84, so a $50-max-loss structure affords 1 contract.
    return [_cand(f"fp-{i}") for i in range(1, n + 1)]


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

    def spy_universe(client, decision_id, user_id):
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

    def spy_universe(client, decision_id, user_id):
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
    assert result["counts"]["candidates_emitted"] == 3
    assert result["counts"]["candidates_rejected"] == 0


def test_universe_read_failure_is_data_unavailable_for_all():
    FakeWriter.instances = []

    def boom_universe(client, decision_id, user_id):
        raise UniverseUnavailable("scan-envelope read failed")

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
        universe_builder=lambda c, d, u: [],
        writer_factory=FakeWriter,
    )
    assert result["status"] == "succeeded"
    assert result["counts"]["no_candidate_runs"] == 4
    assert result["counts"]["decisions_written"] == 0
    assert all(w.finished["status"] == "no_candidate" for w in FakeWriter.instances)


def test_rejected_candidate_is_data_unavailable_end_to_end():
    # A universe with ONE emitted (scored) candidate + ONE rejected (no routing
    # evidence). The emitted is selected; the rejected is candidate-grain
    # data_unavailable (never fabricated, never a merit rejection), and the
    # emitted/rejected status is stamped as PROVENANCE in features_snapshot.
    FakeWriter.instances = []
    uni = [_cand("emit", emitted=True, matched=True), _cand("rej", emitted=False, matched=False)]
    result = run_fleet_policy_eval(
        _payload(),
        client=object(),
        readiness_loader=_readiness_with(_accounts(1)),
        universe_builder=lambda c, d, u: uni,
        writer_factory=FakeWriter,
    )
    assert result["counts"]["selected"] == 1
    assert result["counts"]["data_unavailable"] == 1
    assert result["counts"]["candidates_emitted"] == 1
    assert result["counts"]["candidates_rejected"] == 1
    w = FakeWriter.instances[0]
    by_fp = {d.candidate_fingerprint: d for d in w.decisions}
    assert by_fp["emit"].disposition == "selected"
    assert by_fp["emit"].suggestion_id == "sug-emit"
    assert by_fp["rej"].disposition == "data_unavailable"
    assert by_fp["rej"].reason_codes == ["routing_score_unavailable"]
    assert by_fp["rej"].suggestion_id is None
    # Provenance threaded to the decision row.
    prov = {d.candidate_fingerprint: s for d, s in zip(w.decisions, w.snapshots)}
    assert prov["rej"]["emitted"] is False
    assert prov["rej"]["matched_emitted"] is False
    assert prov["emit"]["emitted"] is True


def test_per_policy_failure_isolation():
    FakeWriter.instances = []
    uni = _universe(2)
    accounts = _accounts(3)

    # Inject the failure at the EXACT open_positions_loader seam: the loader read
    # raises for ONE micro-account. It is called INSIDE the per-policy try, so it
    # lands as THAT policy's evaluator_failed while the other two are untouched.
    def flaky_loader(client, micro_id):
        if micro_id == "m2":
            raise RuntimeError("open-position read failed")
        return 0

    result = run_fleet_policy_eval(
        _payload(),
        client=object(),
        readiness_loader=_readiness_with(accounts),
        universe_builder=lambda c, d, u: uni,
        writer_factory=FakeWriter,
        open_positions_loader=flaky_loader,
    )

    assert result["status"] == "partial"
    assert result["counts"]["evaluator_failed_runs"] == 1
    assert result["counts"]["errors"] == 1
    assert result["counts"]["policies"] == 3
    failed = [w for w in FakeWriter.instances if w.finished["status"] == "evaluator_failed"]
    ok = [w for w in FakeWriter.instances if w.finished["status"] == "succeeded"]
    assert len(failed) == 1
    assert len(ok) == 2


def test_capital_rejected_when_micro_account_cannot_afford():
    FakeWriter.instances = []
    # A structure whose per-contract max-loss ($3,000) exceeds the $2k tier.
    uni = [_cand("big", score=90.0, max_loss=3000.0)]
    result = run_fleet_policy_eval(
        _payload(),
        client=object(),
        readiness_loader=_readiness_with(_accounts(1)),
        universe_builder=lambda c, d, u: uni,
        writer_factory=FakeWriter,
    )
    assert result["counts"]["capital_rejected"] == 1
    assert result["counts"]["selected"] == 0
    d = FakeWriter.instances[0].decisions[0]
    assert d.disposition == "capital_rejected"
    assert d.reason_codes == ["insufficient_risk_budget"]


def test_missing_max_loss_basis_is_data_unavailable_not_fabricated():
    # An EMITTED (scored) candidate that passed the filter but carries NO canonical
    # max-loss basis: cannot size without fabricating risk -> data_unavailable
    # (doctrine §10), NOT a capital merit rejection.
    FakeWriter.instances = []
    uni = [{
        "candidate_fingerprint": "nomaxloss", "suggestion_id": "sug-nml",
        "emitted": True, "matched_emitted": True,
        "sizing_metadata": {"score": 90.0}, "order_json": {"contracts": 1},
        "ev": 1, "ev_raw": 1, "symbol": "SPY", "strategy": "IC",
    }]
    result = run_fleet_policy_eval(
        _payload(),
        client=object(),
        readiness_loader=_readiness_with(_accounts(1)),
        universe_builder=lambda c, d, u: uni,
        writer_factory=FakeWriter,
    )
    d = FakeWriter.instances[0].decisions[0]
    assert d.disposition == "data_unavailable"
    assert d.reason_codes == ["max_loss_basis_unavailable"]
    assert result["counts"]["data_unavailable"] == 1


def test_missing_score_is_data_unavailable():
    decisions = evaluate_policy(
        [{"candidate_fingerprint": "x", "suggestion_id": None, "sizing_metadata": {}, "order_json": {"contracts": 1}}],
        APPROVED_POLICY["policy_config"],
        open_positions=0,
        deployable_capital=2000.0,
    )
    assert decisions[0].disposition == "data_unavailable"
    assert decisions[0].reason_codes == ["routing_score_unavailable"]
    assert decisions[0].suggestion_id is None


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
            self._owner.last_decision_payload = self._payload
            if self._owner.decision_inserts > 1:
                raise RuntimeError("duplicate key value violates unique constraint (23505)")
            return _Resp([{"id": "d1"}])
        return _Resp([{"run_id": "run-1"}])


class _DupClient:
    def __init__(self):
        self.decision_inserts = 0
        self.last_decision_payload = None

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
    dec = PolicyDecision("fp-1", "sug-1", "selected", [], 1, 80.0, {"contracts": 1})
    assert writer.record_decision(dec) is True  # first insert
    assert writer.record_decision(dec) is True  # replay -> duplicate ack, no crash
    counters = writer.counters_dict()
    assert counters["decisions_written"] == 1
    assert counters["duplicate_acks"] == 1
    assert counters["write_failures"] == 0
    # v2 identity: fingerprint always written; suggestion UUID mirrored on both
    # identity columns (or both NULL for a reject).
    p = client.last_decision_payload
    assert p["candidate_fingerprint"] == "fp-1"
    assert p["decision_event_id"] == "sug-1"
    assert p["candidate_suggestion_id"] == "sug-1"


def test_writer_records_rejected_candidate_with_null_suggestion_id():
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
    writer.begin_run()
    # A rejected candidate: fingerprint only, no suggestion UUID.
    dec = PolicyDecision("rejfp", None, "data_unavailable", ["routing_score_unavailable"], 3, None, {})
    assert writer.record_decision(dec) is True
    p = client.last_decision_payload
    assert p["candidate_fingerprint"] == "rejfp"
    assert p["decision_event_id"] is None
    assert p["candidate_suggestion_id"] is None
    assert p["disposition"] == "data_unavailable"


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
# v2 universe builder: complete scan-envelope source + emitted enrichment.
# ─────────────────────────────────────────────────────────────────────────────
def _legs(sym):
    # A real 2-leg option structure so compute_legs_fingerprint is well-defined.
    return [
        {"symbol": f"{sym}260717C00500000", "side": "buy", "quantity": 1, "type": "call", "strike": 500, "expiry": "2026-07-17"},
        {"symbol": f"{sym}260717C00510000", "side": "sell", "quantity": 1, "type": "call", "strike": 510, "expiry": "2026-07-17"},
    ]


def _fp(sym):
    return compute_legs_fingerprint({"legs": _legs(sym)})


def _envrow(sym, emitted, *, cycle=DECISION):
    return {
        "candidate_fingerprint": _fp(sym),
        "emitted": emitted,
        "reject_reason": None if emitted else "unattributed_post_ev",
        "reject_gate": None if emitted else "post_ev_gate",
        "symbol": sym,
        "strategy": "CALL_DEBIT_SPREAD",
        "cycle_id": cycle,
        "envelope": {"legs": _legs(sym), "contracts": 1, "production_ev": 12.0},
    }


def _sugrow(sym, score, *, sid=None, cohort="aggressive", max_loss=50.0, decision=DECISION):
    return {
        "id": sid or f"sug-{sym}",
        "decision_id": decision,
        "cohort_name": cohort,
        "legs_fingerprint": _fp(sym),
        "sizing_metadata": {"score": score, "max_loss_total": max_loss},
        "order_json": {"contracts": 1, "legs": _legs(sym)},
        "ev": 10.0,
        "ev_raw": 10.0,
    }


class _EnvQuery:
    def __init__(self, rows):
        self._rows = rows
        self._cycle = None

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        if col == "cycle_id":
            self._cycle = val
        return self

    def execute(self):
        return _Resp([r for r in self._rows if r.get("cycle_id") == self._cycle])


class _FilterTradeSuggestions:
    def __init__(self, rows):
        self._rows = rows
        self._decision = None
        self._or = None

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        if col == "decision_id":
            self._decision = val
        return self

    def is_(self, col, val):
        self._or = f"{col}.is.null"
        return self

    def or_(self, expr):
        self._or = expr
        return self

    def _match_cohort(self, cohort):
        for pred in (self._or or "").split(","):
            pred = pred.strip()
            if pred == "cohort_name.is.null" and cohort is None:
                return True
            if pred.startswith("cohort_name.eq.") and cohort == pred.split(".eq.", 1)[1]:
                return True
        return False

    def execute(self):
        out = [
            r for r in self._rows
            if r.get("decision_id") == self._decision and self._match_cohort(r.get("cohort_name"))
        ]
        return _Resp(out)


class _TwoTableClient:
    """Exercises the REAL default loaders (_load_scan_envelopes +
    _load_emitted_enrichment): applies the cycle_id filter on td_scan_envelopes
    and the decision_id + cohort filter on trade_suggestions."""

    def __init__(self, envelopes, suggestions):
        self._env = envelopes
        self._sug = suggestions
        self.touched = []

    def table(self, name):
        self.touched.append(name)
        if name == SCAN_ENVELOPE_TABLE:
            return _EnvQuery(self._env)
        if name == ENRICHMENT_TABLE:
            return _FilterTradeSuggestions(self._sug)
        raise AssertionError(f"unexpected table {name}")


def test_v2_universe_is_complete_envelope_set_enriched_by_emitted():
    # Envelopes: SPY emitted, QQQ REJECTED-before-persistence (no suggestion).
    envelopes = [_envrow("SPY", True), _envrow("QQQ", False)]
    # trade_suggestions has ONLY the emitted SPY (champion) + a neutral CLONE.
    suggestions = [
        _sugrow("SPY", 88.0, cohort="aggressive"),
        _sugrow("SPY", 99.0, cohort="neutral"),  # clone: excluded by cohort filter
    ]
    client = _TwoTableClient(envelopes, suggestions)
    universe = build_candidate_universe(
        client, DECISION, USER, champion_resolver=lambda c, u: "aggressive"
    )
    by_fp = {c["candidate_fingerprint"]: c for c in universe}
    assert set(by_fp) == {_fp("SPY"), _fp("QQQ")}
    # Emitted SPY enriched from the CHAMPION row (score 88), not the neutral clone.
    spy = by_fp[_fp("SPY")]
    assert spy["matched_emitted"] is True
    assert spy["sizing_metadata"]["score"] == 88.0
    assert spy["suggestion_id"] == "sug-SPY"
    # REJECTED QQQ present with NO routing evidence (the champion subset does NOT
    # define the universe) — never fabricated.
    qqq = by_fp[_fp("QQQ")]
    assert qqq["matched_emitted"] is False
    assert qqq["sizing_metadata"] == {}
    assert qqq["suggestion_id"] is None
    assert qqq["emitted"] is False
    # Both tables were read (envelope primary + enrichment); order envelope-first.
    assert client.touched == [SCAN_ENVELOPE_TABLE, ENRICHMENT_TABLE]


def test_v2_universe_dedupes_same_structure_preserves_distinct():
    envelopes = [_envrow("SPY", True), _envrow("SPY", True), _envrow("IWM", False)]
    suggestions = [_sugrow("SPY", 70.0)]
    universe = build_candidate_universe(
        _TwoTableClient(envelopes, suggestions), DECISION, USER,
        champion_resolver=lambda c, u: "aggressive",
    )
    fps = [c["candidate_fingerprint"] for c in universe]
    # Same structure collapsed to one; distinct structure preserved.
    assert fps.count(_fp("SPY")) == 1
    assert _fp("IWM") in fps
    assert len(universe) == 2


def test_v2_universe_scoped_to_source_decision_cross_user_isolation():
    # An envelope + suggestion for a DIFFERENT decision (a different user's cycle)
    # must NOT leak into this decision's universe. The reads are keyed on the
    # source decision id (globally-unique cycle identity).
    other = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    envelopes = [_envrow("SPY", True), _envrow("QQQ", True, cycle=other)]
    suggestions = [_sugrow("SPY", 60.0), _sugrow("QQQ", 95.0, decision=other)]
    universe = build_candidate_universe(
        _TwoTableClient(envelopes, suggestions), DECISION, USER,
        champion_resolver=lambda c, u: "aggressive",
    )
    fps = {c["candidate_fingerprint"] for c in universe}
    assert fps == {_fp("SPY")}
    assert _fp("QQQ") not in fps


def test_v2_universe_sorted_scored_first_rejected_last():
    envelopes = [_envrow("SPY", True), _envrow("QQQ", True), _envrow("IWM", False)]
    suggestions = [_sugrow("SPY", 40.0), _sugrow("QQQ", 90.0)]
    universe = build_candidate_universe(
        _TwoTableClient(envelopes, suggestions), DECISION, USER,
        champion_resolver=lambda c, u: "aggressive",
    )
    order = [c["candidate_fingerprint"] for c in universe]
    # score desc among scored (QQQ 90 before SPY 40), unscored reject last.
    assert order[0] == _fp("QQQ")
    assert order[1] == _fp("SPY")
    assert order[2] == _fp("IWM")


def test_v2_envelope_read_error_raises_not_empty():
    def boom_env(client, decision_id):
        raise RuntimeError("network")

    with pytest.raises(UniverseUnavailable):
        build_candidate_universe(
            object(), DECISION, USER,
            champion_resolver=lambda c, u: "aggressive",
            envelope_loader=boom_env,
        )


def test_v2_enrichment_read_error_raises_not_empty():
    def boom_enrich(client, decision_id, champion):
        raise RuntimeError("enrichment down")

    with pytest.raises(UniverseUnavailable):
        build_candidate_universe(
            object(), DECISION, USER,
            champion_resolver=lambda c, u: "aggressive",
            envelope_loader=lambda c, d: [_envrow("SPY", True)],
            enrichment_loader=boom_enrich,
        )


def test_v2_champion_resolve_failure_fails_closed():
    def boom_resolver(client, user_id):
        raise RuntimeError("champion resolve exploded")

    with pytest.raises(UniverseUnavailable):
        build_candidate_universe(
            object(), DECISION, USER,
            champion_resolver=boom_resolver,
            envelope_loader=lambda c, d: [_envrow("SPY", True)],
        )


def test_v2_empty_envelope_set_is_honest_empty_not_error():
    universe = build_candidate_universe(
        _TwoTableClient([], []), DECISION, USER,
        champion_resolver=lambda c, u: "aggressive",
    )
    assert universe == []


# ─────────────────────────────────────────────────────────────────────────────
# LEGACY trade_suggestions universe: activation-blocked compatibility fallback.
# ─────────────────────────────────────────────────────────────────────────────
class _LegacyFilterClient:
    def __init__(self, rows):
        self._rows = rows

    def table(self, name):
        assert name == ENRICHMENT_TABLE
        return _FilterTradeSuggestions(self._rows)


def test_legacy_universe_is_champion_emitted_only():
    # The pre-v2 surface: champion-tagged emitted rows ONLY, clones excluded. It
    # CANNOT see the rejected candidates — that is exactly why it is not the v2
    # universe and is activation-blocked.
    rows = [
        _sugrow("SPY", 90.0, sid="emit-hi", cohort="aggressive"),
        _sugrow("QQQ", 10.0, sid="emit-lo", cohort="aggressive"),
        _sugrow("IWM", 99.0, sid="clone-neu", cohort="neutral"),
    ]
    universe = build_trade_suggestions_universe(
        _LegacyFilterClient(rows), DECISION, USER, champion_resolver=lambda c, u: "aggressive"
    )
    sids = [c["suggestion_id"] for c in universe]
    assert sids == ["emit-hi", "emit-lo"]  # score desc, clone excluded
    assert all(c["matched_emitted"] for c in universe)


# ─────────────────────────────────────────────────────────────────────────────
# Parent byte-identity: the SCORED filter precedence matches Policy-Lab fork.
# ─────────────────────────────────────────────────────────────────────────────
def test_scored_filter_precedence_byte_identical_to_fork():
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
    # SCORED candidates only (fork never faces a scoreless candidate in prod).
    suggestions = [
        {"id": "s1", "sizing_metadata": {"score": 90.0}},   # accepted (slot 1)
        {"id": "s3", "sizing_metadata": {"score": 40.0}},   # score_below_min
        {"id": "s4", "sizing_metadata": {"score": 70.0}},   # accepted (slot 2)
        {"id": "s5", "sizing_metadata": {"score": 80.0}},   # capacity exhausted
    ]
    fork_decisions = _evaluate_cohort_policy(suggestions, config, open_positions=0)

    # Large capital so sizing NEVER capital-rejects -> 'selected' == fork accepted.
    universe = [
        {
            "candidate_fingerprint": s["id"],
            "suggestion_id": s["id"],
            "order_json": {"contracts": 1},
            "sizing_metadata": dict(s["sizing_metadata"], max_loss_total=100.0),
        }
        for s in suggestions
    ]
    mine = evaluate_policy(universe, config.to_dict(), open_positions=0, deployable_capital=1_000_000.0)

    fork_accepted = [d.suggestion_id for d in fork_decisions if d.accepted]
    mine_selected = [d.suggestion_id for d in mine if d.disposition == "selected"]
    assert mine_selected == fork_accepted == ["s1", "s4"]

    # Reason codes for the SCORED rejections line up candidate-for-candidate.
    fork_reasons = {d.suggestion_id: d.reason_codes for d in fork_decisions if not d.accepted}
    mine_reasons = {d.suggestion_id: d.reason_codes for d in mine if d.disposition == "policy_rejected"}
    assert mine_reasons == fork_reasons
    assert mine_reasons["s3"] == ["score_below_min"]
    assert mine_reasons["s5"] == ["daily_limit_reached"]


def test_unscored_candidate_is_data_unavailable_not_a_capacity_rejection():
    # v2 divergence (honest): a scoreless candidate is unmeasurable, NOT a merit
    # rejection. It never consumes a capacity slot, so the SELECTED set is
    # unchanged vs fork; only its label differs (data_unavailable, not a fork
    # rejection). Ordered scoreless-last as the builder sorts it.
    from packages.quantum.policy_lab.config import PolicyConfig

    config = PolicyConfig.from_dict({"max_positions_open": 2, "max_suggestions_per_day": 3, "min_score_threshold": 50.0})
    universe = [
        {"candidate_fingerprint": "s1", "suggestion_id": "s1", "order_json": {"contracts": 1}, "sizing_metadata": {"score": 90.0, "max_loss_total": 100.0}},
        {"candidate_fingerprint": "s4", "suggestion_id": "s4", "order_json": {"contracts": 1}, "sizing_metadata": {"score": 70.0, "max_loss_total": 100.0}},
        {"candidate_fingerprint": "rej", "suggestion_id": None, "order_json": {"contracts": 1}, "sizing_metadata": {}},
    ]
    decisions = evaluate_policy(universe, config.to_dict(), open_positions=0, deployable_capital=1_000_000.0)
    by = {d.candidate_fingerprint: d for d in decisions}
    assert by["s1"].disposition == "selected"
    assert by["s4"].disposition == "selected"
    assert by["rej"].disposition == "data_unavailable"
    assert by["rej"].reason_codes == ["routing_score_unavailable"]


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
        ".option_chain",
    ):
        assert forbidden not in src, f"evaluator must not reference {forbidden}"
