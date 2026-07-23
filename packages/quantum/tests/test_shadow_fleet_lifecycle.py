"""Unit tests for the isolated fleet internal-paper lifecycle (C2).

Covers: fail-closed open-position counter, multi-leg normalization, executable-
side entry cost (never mid), the no-op-while-inactive open path, source-tape
gating, and the no-broker-import isolation.
"""

from pathlib import Path

import pytest

from packages.quantum.services import shadow_fleet_lifecycle as lc
from packages.quantum.services.shadow_fleet_lifecycle import (
    compute_entry_net_cost,
    count_open_fleet_positions,
    execute_fleet_run_candidates,
    normalize_fleet_legs,
)

CONDOR = {
    "legs": [
        {"side": "sell", "symbol": "O:SPY260828P00690000", "quantity": 6},
        {"side": "buy", "symbol": "O:SPY260828P00685000", "quantity": 6},
        {"side": "sell", "symbol": "O:SPY260828C00772000", "quantity": 6},
        {"side": "buy", "symbol": "O:SPY260828C00777000", "quantity": 6},
    ],
    "strategy": "IRON_CONDOR",
    "contracts": 6,
    "underlying": "SPY",
    "limit_price": 1.32,
}


class _Resp:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class _Q:
    def __init__(self, table, owner):
        self._t = table
        self._o = owner

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def lte(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        if self._o.raise_on and self._t == self._o.raise_on:
            raise RuntimeError(self._o.raise_msg)
        return _Resp(list(self._o.tables.get(self._t, [])))


class FakeClient:
    def __init__(self, tables, raise_on=None, raise_msg="boom"):
        self.tables = tables
        self.raise_on = raise_on
        self.raise_msg = raise_msg

    def table(self, name):
        return _Q(name, self)


# ── open-position counter (fail-closed) ──────────────────────────────────────
def test_count_open_positions_raises_on_read_error():
    client = FakeClient({}, raise_on="fleet_shadow_positions", raise_msg="connection reset")
    with pytest.raises(RuntimeError):
        count_open_fleet_positions(client, "m1")


def test_count_open_positions_table_missing_is_zero():
    client = FakeClient(
        {}, raise_on="fleet_shadow_positions",
        raise_msg="Could not find the table 'public.fleet_shadow_positions' (PGRST205)",
    )
    assert count_open_fleet_positions(client, "m1") == 0


# ── multi-leg normalization ──────────────────────────────────────────────────
def test_normalize_condor_signs_strikes_and_fleet_sizing():
    norm = normalize_fleet_legs(CONDOR, fleet_contracts=2)
    assert norm is not None
    assert norm["underlying"] == "SPY"
    assert norm["expiry"] == "2026-08-28"
    legs = norm["legs"]
    assert len(legs) == 4
    # ratio = 6/6 = 1; fleet_contracts=2 => leg contracts = 2.
    assert {l["contracts"] for l in legs} == {2}
    by_strike = {l["strike"]: l for l in legs}
    assert by_strike[690.0]["option_type"] == "put" and by_strike[690.0]["sign"] == -1
    assert by_strike[685.0]["option_type"] == "put" and by_strike[685.0]["sign"] == 1
    assert by_strike[772.0]["option_type"] == "call" and by_strike[772.0]["sign"] == -1
    assert by_strike[777.0]["option_type"] == "call" and by_strike[777.0]["sign"] == 1


def test_normalize_rejects_malformed_structures():
    assert normalize_fleet_legs({"legs": [], "contracts": 6}, 1) is None
    assert normalize_fleet_legs({"legs": [{"side": "sell", "symbol": "GARBAGE", "quantity": 6}], "contracts": 6, "underlying": "SPY"}, 1) is None
    # non-integer leg ratio (quantity not a multiple of structure contracts)
    bad_ratio = {"legs": [{"side": "buy", "symbol": "O:SPY260828C00777000", "quantity": 5}], "contracts": 6, "underlying": "SPY"}
    assert normalize_fleet_legs(bad_ratio, 1) is None
    # mixed expiries
    mixed = {
        "legs": [
            {"side": "buy", "symbol": "O:SPY260828C00777000", "quantity": 6},
            {"side": "sell", "symbol": "O:SPY260904C00772000", "quantity": 6},
        ],
        "contracts": 6, "underlying": "SPY",
    }
    assert normalize_fleet_legs(mixed, 1) is None


# ── executable-side entry cost (never mid) ───────────────────────────────────
class FakeReplay:
    def __init__(self, quotes):
        # quotes: {occ_symbol: (bid, ask)}
        self.inputs_map = {("SPY:chain:all", "chain"): {}}
        self._quotes = quotes

    def get_stored_input(self, key, snapshot_type):
        payload = [
            {"contract": occ, "quote": {"bid": bid, "ask": ask}}
            for occ, (bid, ask) in self._quotes.items()
        ]
        return {"payload": payload}


def test_entry_net_cost_uses_executable_side():
    norm = normalize_fleet_legs(CONDOR, fleet_contracts=1)
    replay = FakeReplay(
        {
            "O:SPY260828P00690000": (3.00, 3.10),  # sell -> bid 3.00
            "O:SPY260828P00685000": (1.90, 2.00),  # buy  -> ask 2.00
            "O:SPY260828C00772000": (2.40, 2.50),  # sell -> bid 2.40
            "O:SPY260828C00777000": (1.40, 1.50),  # buy  -> ask 1.50
        }
    )
    cost = compute_entry_net_cost(replay, CONDOR, norm, fleet_contracts=1)
    # buys(ask): 2.00 + 1.50 = 3.50 ; sells(bid): 3.00 + 2.40 = 5.40
    # net per share = 3.50 - 5.40 = -1.90 (credit) ; x1 x100 = -190.00
    assert cost == -190.00


def test_entry_net_cost_rejects_unpriceable_leg():
    norm = normalize_fleet_legs(CONDOR, fleet_contracts=1)
    replay = FakeReplay(
        {
            "O:SPY260828P00690000": (3.00, 3.10),
            "O:SPY260828P00685000": (0.0, 0.0),  # dark leg -> reject, never mid
            "O:SPY260828C00772000": (2.40, 2.50),
            "O:SPY260828C00777000": (1.40, 1.50),
        }
    )
    assert compute_entry_net_cost(replay, CONDOR, norm, fleet_contracts=1) is None


# ── open lifecycle: no-op while inactive; correct params when selected ───────
def test_execute_is_honest_empty_when_no_selected_decisions():
    client = FakeClient(
        {
            "fleet_policy_decision_runs": [{"run_id": "r1", "source_decision_id": "d1", "user_id": "u1", "as_of": "2026-07-23T16:00:00+00:00"}],
            "fleet_policy_decisions": [],  # none selected -> the inactive invariant
        }
    )
    calls = []
    result = execute_fleet_run_candidates(
        client, "r1",
        replay_factory=lambda c, d: FakeReplay({}),
        rpc_caller=lambda n, p: calls.append((n, p)),
    )
    assert result["status"] == "honest_empty"
    assert result["counts"]["filled_internal"] == 0
    assert calls == []  # no RPC, no broker


def test_execute_calls_open_rpc_with_normalized_params():
    client = FakeClient(
        {
            "fleet_policy_decision_runs": [{"run_id": "r1", "source_decision_id": "d1", "user_id": "u1", "as_of": "2026-07-23T16:00:00+00:00"}],
            "fleet_policy_decisions": [
                {
                    "run_id": "r1", "shadow_micro_account_id": "m1", "policy_registration_id": "pol_1",
                    "decision_event_id": "cand-1", "candidate_suggestion_id": "cand-1",
                    "sizing": {"contracts": 1, "max_loss_total": 300.0},
                }
            ],
            "shadow_micro_accounts": [{"id": "m1", "portfolio_id": "pf1", "policy_registration_id": "pol_1", "state": "active"}],
            "trade_suggestions": [{"id": "cand-1", "order_json": CONDOR, "sizing_metadata": {"max_loss_total": 300.0}}],
        }
    )
    calls = []

    def rpc(name, params):
        calls.append((name, params))
        return _Resp([{"status": "filled_internal", "idempotent_replay": False, "order_id": "o1", "position_id": "p1"}])

    replay = FakeReplay(
        {
            "O:SPY260828P00690000": (3.00, 3.10),
            "O:SPY260828P00685000": (1.90, 2.00),
            "O:SPY260828C00772000": (2.40, 2.50),
            "O:SPY260828C00777000": (1.40, 1.50),
        }
    )
    result = execute_fleet_run_candidates(client, "r1", replay_factory=lambda c, d: replay, rpc_caller=rpc)
    assert result["status"] == "succeeded"
    assert result["counts"]["filled_internal"] == 1
    assert len(calls) == 1
    name, params = calls[0]
    assert name == "rpc_open_fleet_shadow_position_v1"
    assert params["p_candidate_suggestion_id"] == "cand-1"
    assert params["p_portfolio_id"] == "pf1"
    assert params["p_contracts"] == 1
    assert params["p_max_loss_total"] == 300.0
    assert params["p_entry_net_cost_total"] == -190.00  # credit, executable side
    assert params["p_underlying"] == "SPY"
    assert params["p_expiry"] == "2026-08-28"
    assert len(params["p_legs"]) == 4
    # legs carry ONLY the normalized economic fields (no occ_symbol leaks in).
    assert set(params["p_legs"][0]) == {"option_type", "strike", "sign", "contracts"}


def test_execute_rejects_when_source_tape_unavailable():
    client = FakeClient(
        {
            "fleet_policy_decision_runs": [{"run_id": "r1", "source_decision_id": "d1", "user_id": "u1", "as_of": "t"}],
            "fleet_policy_decisions": [
                {"run_id": "r1", "shadow_micro_account_id": "m1", "policy_registration_id": "pol_1", "decision_event_id": "c1", "candidate_suggestion_id": "c1", "sizing": {"contracts": 1, "max_loss_total": 300.0}}
            ],
        }
    )
    result = execute_fleet_run_candidates(client, "r1", replay_factory=lambda c, d: None, rpc_caller=lambda n, p: None)
    assert result["status"] == "source_decision_unavailable"
    assert result["counts"]["execution_rejected"] == 1


# ── isolation: no broker adapter referenced by the lifecycle module ──────────
def test_lifecycle_imports_no_broker_submit_path():
    src = Path(lc.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "place_option_order",
        "submit_to_broker",
        "alpaca_order_handler",
        "AlpacaClient",
        "execution_router",
    ):
        assert forbidden not in src, f"lifecycle must not reference {forbidden}"
