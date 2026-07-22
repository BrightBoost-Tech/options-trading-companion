from types import SimpleNamespace

from packages.quantum.jobs.runner import _build_handler_payload
from packages.quantum.services.single_leg_shadow_scan import (
    StoredDecisionTruthLayer,
    build_underlying_contexts,
    maybe_enqueue_single_leg_shadow_scan,
    run_single_leg_shadow_scan,
)
from packages.quantum.strategies.single_leg_experiment import (
    SingleLegCandidate,
    SingleLegGenerationResult,
    SingleLegRejection,
)
from packages.quantum.strategies.single_leg_selection import (
    SelectedContract,
    SingleLegSelectionResult,
)


READY_BINDING = {
    "policy_registration_id": "sl_exp_throughput_v1",
    "portfolio_id": "55555555-5555-5555-5555-555555555555",
    "user_id": "44444444-4444-4444-4444-444444444444",
    "role": "experimental",
    "routing_mode": "shadow_only",
    "execution_mode": "internal_paper",
    "enabled": True,
    "policy_config": {"single_leg_experiment_enabled": True},
    "config_hash": "a" * 64,
}


def _ready(*args, **kwargs):
    return {"status": "ready", "ready": True, "errors": 0, "bindings": [READY_BINDING]}


def _disabled(*args, **kwargs):
    return {"status": "epoch_not_enabled", "ready": False, "errors": 0, "bindings": []}


def test_enqueue_is_true_noop_when_epoch_disabled():
    calls = []

    result = maybe_enqueue_single_leg_shadow_scan(
        object(),
        user_id=READY_BINDING["user_id"],
        source_job_run_id=None,
        source_decision_id=None,
        source_code_sha=None,
        as_of=None,
        parent_origin=None,
        readiness_loader=_disabled,
        enqueue_fn=lambda **kwargs: calls.append(kwargs),
    )

    assert result == {
        "status": "epoch_not_enabled",
        "enqueued": False,
        "errors": 0,
    }
    assert calls == []


def test_operator_or_forced_parent_cannot_enqueue_experiment():
    calls = []
    result = maybe_enqueue_single_leg_shadow_scan(
        object(),
        user_id=READY_BINDING["user_id"],
        source_job_run_id="22222222-2222-2222-2222-222222222222",
        source_decision_id="33333333-3333-3333-3333-333333333333",
        source_code_sha="b" * 40,
        as_of="2026-07-22T16:00:00+00:00",
        parent_origin="operator_signed_endpoint",
        readiness_loader=_ready,
        enqueue_fn=lambda **kwargs: calls.append(kwargs),
    )

    assert result["status"] == "non_natural_parent"
    assert result["enqueued"] is False
    assert calls == []


def test_natural_parent_enqueues_one_attributable_child():
    calls = []

    def enqueue(**kwargs):
        calls.append(kwargs)
        return {
            "job_run_id": "66666666-6666-6666-6666-666666666666",
            "rq_job_id": "rq-1",
            "status": "queued",
        }

    def origin(event, **kwargs):
        return {"origin": "event", "trigger_actor_class": event, **kwargs}

    result = maybe_enqueue_single_leg_shadow_scan(
        object(),
        user_id=READY_BINDING["user_id"],
        source_job_run_id="22222222-2222-2222-2222-222222222222",
        source_decision_id="33333333-3333-3333-3333-333333333333",
        source_code_sha="b" * 40,
        as_of="2026-07-22T16:00:00+00:00",
        parent_origin="scheduler",
        readiness_loader=_ready,
        enqueue_fn=enqueue,
        origin_builder=origin,
    )

    assert result["enqueued"] is True
    assert result["errors"] == 0
    assert len(calls) == 1
    call = calls[0]
    assert call["job_name"] == "single_leg_shadow_scan"
    assert call["idempotency_key"] == (
        "single_leg_shadow_scan:"
        "33333333-3333-3333-3333-333333333333:"
        "single_leg_experiment_v1"
    )
    assert call["payload"]["source_job_run_id"].startswith("2222")
    assert call["origin"]["origin"] == "event"
    assert call["origin"]["parent_job_run_id"].startswith("2222")


class FakeReplay:
    def __init__(self):
        self.decision_run = {
            "decision_id": "33333333-3333-3333-3333-333333333333",
            "user_id": READY_BINDING["user_id"],
            "as_of_ts": "2026-07-22T16:00:00+00:00",
            "git_sha": "b" * 40,
            "tape_integrity": "complete",
        }
        self.features_map = {
            ("SPY", "symbol_features"): {
                "features": {
                    "iv_rank": 10.0,
                    "iv_rv_spread": -0.02,
                    "raw_features": {},
                }
            }
        }
        self.inputs_map = {
            ("SPY:bars:2026-04-01:2026-07-22", "bars"): {
                "blob_hash": "bars"
            },
            ("SPY:polygon:snapshot_v4", "quote"): {"blob_hash": "quote"},
            ("SPY:chain:all", "chain"): {"blob_hash": "chain"},
        }
        self.payloads = {
            ("SPY:bars:2026-04-01:2026-07-22", "bars"): {
                "payload": [{"c": 100 + i} for i in range(25)],
                "metadata": {"symbol": "SPY"},
            },
            ("SPY:polygon:snapshot_v4", "quote"): {
                "payload": {"quote": {"last": 124.0}},
                "metadata": {"canon_symbol": "SPY"},
            },
            ("SPY:chain:all", "chain"): {
                "payload": [
                    {
                        "contract": "SPY260821C00125000",
                        "expiry": "2026-08-21",
                        "right": "call",
                        "strike": 125.0,
                        "quote": {"bid": 0.90, "ask": 1.00, "mid": 0.95},
                        "greeks": {"delta": 0.50, "iv": 0.18},
                        "oi": 500,
                        "volume": 200,
                        "source": "alpaca",
                    }
                ],
                "metadata": {"provider": "alpaca"},
            },
        }

    def get_stored_input(self, key, snapshot_type):
        return self.payloads.get((key, snapshot_type))


def test_context_builder_and_chain_view_use_only_stored_tape():
    replay = FakeReplay()
    contexts = build_underlying_contexts(replay)
    assert len(contexts) == 1
    assert contexts[0]["symbol"] == "SPY"
    assert contexts[0]["spot"] == 124.0
    assert contexts[0]["iv_rank"] == 10.0
    assert contexts[0]["iv_rv_spread"] == -0.02
    assert len(contexts[0]["closes"]) == 25

    chain = StoredDecisionTruthLayer(replay).option_chain(
        "SPY",
        min_expiry="2026-08-01",
        max_expiry="2026-09-01",
        spot=124.0,
    )
    assert [row["contract"] for row in chain] == ["SPY260821C00125000"]


class FakeWriter:
    instances = []

    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs
        self.run_id = "77777777-7777-7777-7777-777777777777"
        self.attempts = []
        self.events = []
        self.finished = None
        self.counters = {
            "runs_started": 0,
            "attempts_written": 0,
            "events_written": 0,
            "write_failures": 0,
            "table_missing_noops": 0,
        }
        type(self).instances.append(self)

    def begin_run(self):
        self.counters["runs_started"] = 1
        return self.run_id

    def record_attempt(self, **kwargs):
        self.attempts.append(kwargs)
        self.counters["attempts_written"] += 1
        return True

    def record_event(self, **kwargs):
        self.events.append(kwargs)
        self.counters["events_written"] += 1
        return True

    def finish_run(self, **kwargs):
        self.finished = kwargs
        return True

    def counters_dict(self):
        return dict(self.counters)


def _selection_result():
    selected = SelectedContract(
        symbol="SPY",
        option_type="call",
        occ_symbol="SPY260821C00125000",
        strike=125.0,
        expiry="2026-08-21",
        dte_days=30.0,
        debit_per_contract=95.0,
        delta=0.50,
        ev_expected_value=20.0,
        ev_pop=0.55,
        ev_source="single_leg_adapter",
        ev_version="single_leg@1.0.0",
        ev_known_at="2026-07-22T16:00:00+00:00",
        considered=10,
        viable=1,
        chain_source="alpaca",
        scan_context={},
    )
    candidate = SingleLegCandidate(
        symbol="SPY",
        option_type="call",
        strategy_type="long_call",
        strike=125.0,
        expiry="2026-08-21",
        debit_per_contract=95.0,
        ev_expected_value=20.0,
        ev_pop=0.55,
        ev_basis="raw",
        ev_model="lognormal_v1",
        iv=0.18,
        spot=124.0,
        dte_days=30.0,
        known_at="2026-07-22T16:00:00+00:00",
        vrp_iv_rv_spread=-0.02,
        vrp_multiplier=1.0,
        vrp_source="test",
        occ_symbol="SPY260821C00125000",
    )
    generation = SingleLegGenerationResult(
        enabled=True,
        routing_mode="shadow_only",
        candidates=[candidate],
        rejections=[
            SingleLegRejection(
                symbol="QQQ",
                reason_code="iv_not_low",
                detail="iv rank above experiment ceiling",
            )
        ],
    )
    return SingleLegSelectionResult(
        generation=generation,
        selections=[selected],
        selection_rejections=[
            SingleLegRejection(
                symbol="IWM",
                reason_code="chain_unavailable",
                detail="source decision carried no option chain",
            )
        ],
    )


def test_child_persists_typed_rejections_candidate_and_event():
    FakeWriter.instances = []
    replay = FakeReplay()

    result = run_single_leg_shadow_scan(
        {
            "source_job_run_id": "22222222-2222-2222-2222-222222222222",
            "source_decision_id": "33333333-3333-3333-3333-333333333333",
            "source_code_sha": "b" * 40,
            "source_as_of": "2026-07-22T16:00:00+00:00",
            "user_id": READY_BINDING["user_id"],
            "policy_epoch": "single_leg_experiment_v1",
        },
        client=object(),
        readiness_loader=_ready,
        replay_factory=lambda client, decision_id: replay,
        context_builder=lambda replay, max_symbols=None: [{"symbol": "SPY"}],
        selector=lambda *args, **kwargs: _selection_result(),
        writer_factory=FakeWriter,
        estimator=lambda request: SimpleNamespace(expected_value=1.0),
    )

    assert result["ok"] is True
    assert result["status"] == "succeeded"
    assert result["counts"]["policies"] == 1
    assert result["counts"]["selection_rejected"] == 1
    assert result["counts"]["gate_rejected"] == 1
    assert result["counts"]["candidates_generated"] == 1

    writer = FakeWriter.instances[0]
    assert [row["stage"] for row in writer.attempts] == [
        "selection_rejected",
        "gate_rejected",
        "candidate_generated",
    ]
    assert writer.events[0]["event_type"] == "candidate_generated"
    assert writer.events[0]["payload"]["contracts"] == 1
    assert writer.events[0]["payload"]["routing"] == "shadow_only"
    assert writer.finished["status"] == "succeeded"


class BrokenWriter(FakeWriter):
    def record_attempt(self, **kwargs):
        self.attempts.append(kwargs)
        self.counters["write_failures"] += 1
        return False


def test_evidence_write_failure_makes_child_partial():
    FakeWriter.instances = []
    replay = FakeReplay()
    result = run_single_leg_shadow_scan(
        {
            "source_job_run_id": "22222222-2222-2222-2222-222222222222",
            "source_decision_id": "33333333-3333-3333-3333-333333333333",
            "user_id": READY_BINDING["user_id"],
        },
        client=object(),
        readiness_loader=_ready,
        replay_factory=lambda client, decision_id: replay,
        context_builder=lambda replay, max_symbols=None: [{"symbol": "SPY"}],
        selector=lambda *args, **kwargs: _selection_result(),
        writer_factory=BrokenWriter,
        estimator=lambda request: SimpleNamespace(expected_value=1.0),
    )

    assert result["status"] == "partial"
    assert result["counts"]["errors"] > 0


def test_runner_injects_parent_job_id_without_mutating_db_payload():
    stored = {"payload": {"origin": {"origin": "scheduler"}}, "job_name": "suggestions_open"}
    original = dict(stored["payload"])
    payload = _build_handler_payload(
        stored,
        "22222222-2222-2222-2222-222222222222",
    )
    assert stored["payload"] == original
    assert payload["_job_run_id"].startswith("2222")
    assert payload["_job_name"] == "suggestions_open"
    assert payload["origin"]["origin"] == "scheduler"
