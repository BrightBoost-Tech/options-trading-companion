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
        "user_id": USER,
        "tape_integrity": "complete",
        "git_sha": "a" * 40,
    }
    inputs_map = {}
    features_map = {}


def _candidate(symbol="SPY"):
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


def test_dry_run_evaluates_only_two_experimental_policies_without_writes():
    client = Client()
    result = run_single_leg_shadow_dry_replay(
        client,
        user_id=USER,
        decision_id=DECISION,
        replay_factory=lambda client, decision_id: Replay(),
        context_builder=lambda replay: [{"symbol": "SPY"}],
        selector=_selector,
        estimator=lambda request: object(),
    )

    assert result["status"] == "CANDIDATES_FOUND"
    assert result["write_mode"] == "NO-WRITE"
    assert result["provider_calls"] == 0
    assert result["broker_calls"] == 0
    assert result["policies_evaluated"] == 2
    assert result["contexts"] == 1
    assert result["attempts"] == 6
    assert result["candidates"] == 2
    assert [row["policy_registration_id"] for row in result["policy_results"]] == [
        "sl_exp_conviction_v1",
        "sl_exp_throughput_v1",
    ]
    assert all(
        row["candidates"][0]["contracts"] == 1
        and row["candidates"][0]["routing"] == "shadow_only"
        for row in result["policy_results"]
    )


def test_dry_run_rejects_hash_drift_before_selector_runs():
    def mutate(rows):
        rows[0]["config_hash"] = "0" * 64

    with pytest.raises(ValueError, match="policy hash mismatch"):
        run_single_leg_shadow_dry_replay(
            Client(mutate=mutate),
            user_id=USER,
            decision_id=DECISION,
            replay_factory=lambda client, decision_id: Replay(),
            context_builder=lambda replay: [],
            selector=lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("selector must not run")
            ),
            estimator=lambda request: object(),
        )


def test_dry_run_rejects_control_opt_in_and_wrong_user_tape():
    def mutate(rows):
        control = next(
            row
            for row in rows
            if row["policy_registration_id"] == "sl_ctrl_throughput_v1"
        )
        control["policy_config"]["single_leg_experiment_enabled"] = True

    with pytest.raises(ValueError, match="control carries single-leg opt-in"):
        run_single_leg_shadow_dry_replay(
            Client(mutate=mutate),
            user_id=USER,
            decision_id=DECISION,
            replay_factory=lambda client, decision_id: Replay(),
            context_builder=lambda replay: [],
            selector=_selector,
            estimator=lambda request: object(),
        )

    class OtherReplay(Replay):
        decision_run = {**Replay.decision_run, "user_id": "other-user"}

    with pytest.raises(ValueError, match="different user"):
        run_single_leg_shadow_dry_replay(
            Client(),
            user_id=USER,
            decision_id=DECISION,
            replay_factory=lambda client, decision_id: OtherReplay(),
            context_builder=lambda replay: [],
            selector=_selector,
            estimator=lambda request: object(),
        )
