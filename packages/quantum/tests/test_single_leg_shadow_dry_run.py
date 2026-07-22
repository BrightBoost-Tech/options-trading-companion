from types import SimpleNamespace

import pytest

from packages.quantum.policy_lab.single_leg_experiment_design import (
    build_registrations,
)
from packages.quantum.strategies.single_leg_experiment import (
    SingleLegCandidate,
    SingleLegGenerationResult,
    SingleLegRejection,
)
from packages.quantum.strategies.single_leg_selection import (
    SingleLegSelectionResult,
)
from scripts.analytics.single_leg_shadow_dry_run import (
    ReadOnlyViolation,
    run_single_leg_shadow_dry_replay,
)


USER = "44444444-4444-4444-4444-444444444444"
DECISION = "33333333-3333-3333-3333-333333333333"


class Query:
    def __init__(self, rows):
        self.rows = [dict(row) for row in rows]
        self.filters = []

    def select(self, columns):
        self.columns = columns
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def execute(self):
        rows = self.rows
        for column, value in self.filters:
            rows = [row for row in rows if row.get(column) == value]
        return SimpleNamespace(data=rows)


class Client:
    def __init__(self, mutate=None):
        rows = []
        for definition in build_registrations():
            row = {
                "policy_registration_id": definition["policy_registration_id"],
                "effective_epoch": definition["effective_epoch"],
                "approval_status": "draft",
                "policy_config": dict(definition["policy_config"]),
                "config_hash": definition["config_hash"],
                "schema_version": definition["schema_version"],
            }
            rows.append(row)
        if mutate:
            mutate(rows)
        self.rows = rows

    def table(self, name):
        assert name == "policy_registrations"
        return Query(self.rows)


class Replay:
    decision_run = {
        "decision_id": DECISION,
        "strategy_name": "suggestions_open",
        "status": "ok",
        "user_id": USER,
        "tape_integrity": "complete",
        "git_sha": "a" * 40,
    }
    inputs_map = {}
    features_map = {}


CONTEXTS = [
    {"symbol": "SPY"},
    {"symbol": "QQQ"},
    {"symbol": "IWM"},
]


def _candidate(symbol="SPY", *, contracts=1):
    return SingleLegCandidate(
        symbol=symbol,
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
        contracts=contracts,
    )


def _selector(contexts, policy_config, **kwargs):
    assert kwargs["routing_mode"] == "shadow_only"
    assert kwargs["truth_layer"] is not None
    assert kwargs["ev_estimator"] is not None
    return SingleLegSelectionResult(
        generation=SingleLegGenerationResult(
            enabled=True,
            routing_mode="shadow_only",
            candidates=[_candidate()],
            rejections=[
                SingleLegRejection(
                    symbol="QQQ",
                    reason_code="iv_not_low",
                    detail="above ceiling",
                )
            ],
        ),
        selections=[],
        selection_rejections=[
            SingleLegRejection(
                symbol="IWM",
                reason_code="chain_unavailable",
                detail="no captured chain",
            )
        ],
    )


def _run(**overrides):
    params = {
        "client": Client(),
        "user_id": USER,
        "decision_id": DECISION,
        "replay_factory": lambda client, decision_id: Replay(),
        "context_builder": lambda replay: list(CONTEXTS),
        "selector": _selector,
        "estimator": lambda request: object(),
    }
    params.update(overrides)
    client = params.pop("client")
    return run_single_leg_shadow_dry_replay(client, **params)


def test_dry_run_evaluates_only_two_experimental_policies_without_writes():
    result = _run()

    assert result["status"] == "CANDIDATES_FOUND"
    assert result["write_mode"] == "NO-WRITE"
    assert result["database_write_attempts"] == 0
    assert result["provider_calls"] == 0
    assert result["broker_calls"] == 0
    assert result["data_source"] == "stored_decision_tape"
    assert result["policies_evaluated"] == 2
    assert result["contexts"] == 3
    assert result["attempts"] == 6
    assert result["candidates"] == 2
    assert [row["policy_registration_id"] for row in result["policy_results"]] == [
        "sl_exp_conviction_v1",
        "sl_exp_throughput_v1",
    ]
    assert all(
        row["candidates"][0]["contracts"] == 1
        and row["candidates"][0]["routing"] == "shadow_only"
        and row["candidates"][0]["lifecycle_state"] == "experimental"
        for row in result["policy_results"]
    )


def test_dry_run_rejects_hash_config_and_schema_drift_before_selector_runs():
    mutations = (
        lambda rows: rows[0].__setitem__("config_hash", "0" * 64),
        lambda rows: rows[0].__setitem__("schema_version", 99),
        lambda rows: rows[0]["policy_config"].__setitem__(
            "single_leg_max_debit_per_contract", 149.0
        ),
    )
    matches = ("policy hash mismatch", "schema-version mismatch", "config mismatch")

    for mutation, match in zip(mutations, matches):
        with pytest.raises(ValueError, match=match):
            _run(
                client=Client(mutate=mutation),
                selector=lambda *args, **kwargs: (_ for _ in ()).throw(
                    AssertionError("selector must not run")
                ),
            )


def test_dry_run_rejects_control_opt_in_and_wrong_user_tape():
    def mutate(rows):
        control = next(
            row
            for row in rows
            if row["policy_registration_id"] == "sl_ctrl_throughput_v1"
        )
        control["policy_config"]["single_leg_experiment_enabled"] = True

    with pytest.raises(ValueError, match="config mismatch|control carries"):
        _run(client=Client(mutate=mutate))

    class OtherReplay(Replay):
        decision_run = {**Replay.decision_run, "user_id": "other-user"}

    with pytest.raises(ValueError, match="different user"):
        _run(replay_factory=lambda client, decision_id: OtherReplay())


def test_dry_run_requires_complete_ok_suggestions_open_tape_and_contexts():
    bad_runs = (
        ({**Replay.decision_run, "tape_integrity": None}, "not complete"),
        ({**Replay.decision_run, "status": "failed"}, "status is not ok"),
        (
            {**Replay.decision_run, "strategy_name": "suggestions_close"},
            "not a suggestions_open",
        ),
    )
    for decision_run, match in bad_runs:
        replay_type = type(
            "BadReplay",
            (Replay,),
            {"decision_run": decision_run},
        )
        with pytest.raises(ValueError, match=match):
            _run(replay_factory=lambda client, decision_id, cls=replay_type: cls())

    with pytest.raises(ValueError, match="zero replayable contexts"):
        _run(context_builder=lambda replay: [])


def test_dry_run_blocks_database_mutation_and_rpc_before_delegation():
    def mutating_replay(client, decision_id):
        client.table("policy_registrations").insert({"forbidden": True})
        return Replay()

    with pytest.raises(ReadOnlyViolation, match="blocked query mutation"):
        _run(replay_factory=mutating_replay)

    def rpc_replay(client, decision_id):
        client.rpc("forbidden_rpc", {})
        return Replay()

    with pytest.raises(ReadOnlyViolation, match="blocked RPC"):
        _run(replay_factory=rpc_replay)


def test_dry_run_fails_on_outcome_coverage_or_candidate_invariant_gap():
    with pytest.raises(ValueError, match="outcome coverage mismatch"):
        _run(context_builder=lambda replay: CONTEXTS + [{"symbol": "DIA"}])

    def bad_candidate_selector(*args, **kwargs):
        result = _selector(*args, **kwargs)
        result.generation.candidates[:] = [_candidate(contracts=2)]
        return result

    with pytest.raises(ValueError, match="candidate invariant violation"):
        _run(selector=bad_candidate_selector)
