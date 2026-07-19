"""Hard routing guard: a single-leg experiment order can NEVER reach a broker.

Route-driven (§9 doctrine): drive ExecutionRouter.execute_order — the real
broker-submit entrypoint — with a single-leg experiment order in a broker mode
and assert (a) a typed SingleLegLiveRoutingForbidden is raised and (b) the
injected broker client's submit is NEVER called. The failure is asserted at the
TOP (execute_order) with the broker path as the deepest callee that must not run.
"""

import pytest

from packages.quantum.brokers.execution_router import (
    ExecutionMode,
    ExecutionRouter,
    SHADOW_ONLY_ROUTING,
    SingleLegLiveRoutingForbidden,
    assert_single_leg_shadow_only,
    is_single_leg_experiment,
)


class FakeAlpaca:
    def __init__(self):
        self.calls = []

    def submit_option_order(self, order_request):
        self.calls.append(order_request)
        return {"alpaca_order_id": "fake-1", "status": "accepted"}


def _single_leg_order(routing=SHADOW_ONLY_ROUTING):
    return {
        "symbol": "SPY",
        "strategy_type": "long_call",
        "experiment": "single_leg",
        "routing": routing,
        "lifecycle_state": "experimental",
        "legs": [{"symbol": "O:SPY...C", "action": "buy", "quantity": 1, "type": "call", "strike": 500.0}],
    }


def _router(mode, fake):
    r = ExecutionRouter(supabase=None, alpaca_client=fake)
    r.mode = mode  # force mode without depending on EXECUTION_MODE/LIVE_ENABLED env
    return r


def test_execute_order_blocks_single_leg_in_alpaca_live():
    fake = FakeAlpaca()
    router = _router(ExecutionMode.ALPACA_LIVE, fake)
    with pytest.raises(SingleLegLiveRoutingForbidden):
        router.execute_order(_single_leg_order(), user_id="u1")
    assert fake.calls == []  # broker submit never reached


def test_execute_order_blocks_single_leg_in_alpaca_paper():
    fake = FakeAlpaca()
    router = _router(ExecutionMode.ALPACA_PAPER, fake)
    with pytest.raises(SingleLegLiveRoutingForbidden):
        router.execute_order(_single_leg_order(), user_id="u1")
    assert fake.calls == []


def test_single_leg_passes_internal_paper_without_broker():
    fake = FakeAlpaca()
    router = _router(ExecutionMode.INTERNAL_PAPER, fake)
    res = router.execute_order(_single_leg_order(), user_id="u1")
    assert res["status"] == "delegated_to_tcm"
    assert fake.calls == []


def test_single_leg_passes_shadow_mode_without_broker():
    fake = FakeAlpaca()
    router = _router(ExecutionMode.SHADOW, fake)
    res = router.execute_order(_single_leg_order(), user_id="u1")
    assert res["status"] == "shadow_logged"
    assert fake.calls == []


def test_malformed_single_leg_missing_shadow_marker_refused_even_internal():
    # An experiment order that lost its shadow_only routing marker is corrupt —
    # refuse it unconditionally, even in a non-broker mode.
    fake = FakeAlpaca()
    router = _router(ExecutionMode.INTERNAL_PAPER, fake)
    with pytest.raises(SingleLegLiveRoutingForbidden):
        router.execute_order(_single_leg_order(routing="live_eligible"), user_id="u1")
    assert fake.calls == []


def test_non_experiment_order_not_blocked_by_guard():
    # A normal (non-single-leg-experiment) order in alpaca_live is NOT touched
    # by this guard — it reaches the broker submit (proves the guard is a
    # precise no-op for everything else).
    fake = FakeAlpaca()
    router = _router(ExecutionMode.ALPACA_LIVE, fake)
    normal = {
        "symbol": "QQQ",
        "strategy_type": "iron_condor",
        "routing": "live_eligible",
        "legs": [{"action": "sell"}, {"action": "buy"}, {"action": "sell"}, {"action": "buy"}],
    }
    res = router.execute_order(normal, user_id="u1")
    assert res["status"] == "submitted"
    assert len(fake.calls) == 1


def test_guard_blocks_live_eligible_portfolio_routing():
    # Pure guard: even in internal_paper execution mode, a live_eligible
    # portfolio routing_mode is broker-bound -> refuse.
    order = _single_leg_order()
    with pytest.raises(SingleLegLiveRoutingForbidden):
        assert_single_leg_shadow_only(order, execution_mode="internal_paper", routing_mode="live_eligible")
    # Shadow-only portfolio + non-broker mode -> allowed (no raise).
    assert_single_leg_shadow_only(order, execution_mode="internal_paper", routing_mode="shadow_only")


def test_is_single_leg_experiment_marker_detection():
    assert is_single_leg_experiment(_single_leg_order()) is True
    assert is_single_leg_experiment({"experiment": "iron_condor"}) is False
    assert is_single_leg_experiment({"strategy_experiment": "single_leg"}) is True
    assert is_single_leg_experiment({"symbol": "SPY"}) is False
    assert is_single_leg_experiment(None) is False


def test_generator_candidate_order_request_bridges_the_guard():
    # A generator-emitted candidate's order request passes the guard in a
    # non-broker mode and is refused in a broker mode — end to end.
    from packages.quantum.strategies.single_leg_experiment import SingleLegCandidate

    cand = SingleLegCandidate(
        symbol="SPY", option_type="call", strategy_type="long_call", strike=500.0,
        expiry="2026-08-21", debit_per_contract=140.0, ev_expected_value=12.0,
        ev_pop=0.4, ev_basis="raw", ev_model="lognormal_v1", iv=0.18, spot=505.0,
        dte_days=30.0, known_at="2026-07-01T15:00:00Z", occ_symbol="O:SPY...C",
    )
    req = cand.to_order_request()
    assert req["routing"] == SHADOW_ONLY_ROUTING and req["contracts"] == 1
    # non-broker: allowed
    assert_single_leg_shadow_only(req, execution_mode="internal_paper")
    # broker mode: refused
    with pytest.raises(SingleLegLiveRoutingForbidden):
        assert_single_leg_shadow_only(req, execution_mode="alpaca_live")
