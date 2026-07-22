from datetime import datetime, timezone
from types import SimpleNamespace

from packages.quantum.services.single_leg_shadow_lifecycle import (
    CLOSE_RPC,
    OPEN_RPC,
    execute_run_candidates,
    settle_expired_positions,
)


RUN = {
    "run_id": "11111111-1111-1111-1111-111111111111",
    "source_job_run_id": "22222222-2222-2222-2222-222222222222",
    "source_decision_id": "33333333-3333-3333-3333-333333333333",
    "source_code_sha": "a" * 40,
    "policy_epoch": "single_leg_experiment_v1",
    "policy_registration_id": "sl_exp_throughput_v1",
    "portfolio_id": "55555555-5555-5555-5555-555555555555",
    "user_id": "44444444-4444-4444-4444-444444444444",
    "as_of": "2026-07-22T16:00:00+00:00",
    "status": "running",
}

ATTEMPT = {
    "attempt_id": "66666666-6666-6666-6666-666666666666",
    "run_id": RUN["run_id"],
    "policy_registration_id": RUN["policy_registration_id"],
    "user_id": RUN["user_id"],
    "symbol": "SPY",
    "strategy_type": "long_call",
    "candidate_fingerprint": "f" * 64,
    "occ_symbol": "SPY260821C00125000",
    "strike": 125.0,
    "expiry": "2026-08-21",
    "debit_per_contract": 95.0,
    "known_at": "2026-07-22T16:00:00+00:00",
    "evidence": {},
    "stage": "candidate_generated",
}


class FakeQuery:
    def __init__(self, client, table):
        self.client = client
        self.table = table
        self.filters = []
        self.operation = "select"
        self.payload = None

    def select(self, columns):
        self.columns = columns
        self.operation = "select"
        return self

    def insert(self, payload):
        self.operation = "insert"
        self.payload = payload
        return self

    def update(self, payload):
        self.operation = "update"
        self.payload = payload
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def lte(self, column, value):
        self.filters.append((column, ("lte", value)))
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def _filtered(self):
        rows = [dict(row) for row in self.client.tables.get(self.table, [])]
        for column, value in self.filters:
            if isinstance(value, tuple) and value[0] == "lte":
                rows = [row for row in rows if str(row.get(column)) <= str(value[1])]
            else:
                rows = [row for row in rows if row.get(column) == value]
        return rows

    def execute(self):
        if self.operation == "insert":
            # EvidenceWriter.begin_run retries the already-existing run and then
            # fetches it, mirroring the real unique-key idempotency path.
            if self.table == "single_leg_shadow_runs":
                raise RuntimeError("23505 duplicate key")
            self.client.inserts.setdefault(self.table, []).append(self.payload)
            return SimpleNamespace(data=[self.payload])
        if self.operation == "update":
            return SimpleNamespace(data=self._filtered())
        return SimpleNamespace(data=self._filtered())


class FakeClient:
    def __init__(self, *, attempt=None, policy_cap=150.0, positions=None):
        self.tables = {
            "single_leg_shadow_runs": [RUN],
            "single_leg_shadow_attempts": [attempt or ATTEMPT],
            "policy_registrations": [
                {
                    "policy_registration_id": RUN["policy_registration_id"],
                    "approval_status": "approved",
                    "policy_config": {
                        "single_leg_experiment_enabled": True,
                        "single_leg_max_debit_per_contract": policy_cap,
                    },
                }
            ],
            "single_leg_shadow_positions": positions or [],
        }
        self.inserts = {}

    def table(self, name):
        return FakeQuery(self, name)


class FakeReplay:
    def __init__(self, contract):
        self.inputs_map = {("SPY:chain:all", "chain"): {"blob_hash": "x"}}
        self.contract = contract

    def get_stored_input(self, key, snapshot_type):
        if (key, snapshot_type) == ("SPY:chain:all", "chain"):
            return {"payload": [self.contract], "metadata": {}}
        return None


def _contract(bid=0.90, ask=1.00):
    return {
        "contract": ATTEMPT["occ_symbol"],
        "expiry": ATTEMPT["expiry"],
        "strike": ATTEMPT["strike"],
        "right": "call",
        "quote": {"bid": bid, "ask": ask, "mid": (bid + ask) / 2},
        "source": "alpaca",
        "provider_ts": "2026-07-22T16:00:00+00:00",
    }


def test_internal_fill_uses_source_tape_ask_and_never_broker_shape():
    client = FakeClient()
    calls = []

    def rpc(name, params):
        calls.append((name, params))
        return SimpleNamespace(
            data={
                "status": "filled_internal",
                "idempotent_replay": False,
                "order_id": "o1",
                "position_id": "p1",
            }
        )

    result = execute_run_candidates(
        client,
        RUN["run_id"],
        replay=FakeReplay(_contract()),
        rpc_caller=rpc,
    )

    assert result["status"] == "succeeded"
    assert result["counts"]["filled_internal"] == 1
    assert result["counts"]["execution_rejected"] == 0
    assert [name for name, _ in calls] == [OPEN_RPC]
    params = calls[0][1]
    assert params["p_fill_price_per_share"] == 1.0
    assert params["p_option_type"] == "call"
    assert params["p_strategy_type"] == "long_call"
    assert params["p_occ_symbol"] == ATTEMPT["occ_symbol"]
    assert "broker" not in params
    assert "account" not in params


def test_crossed_quote_is_typed_rejection_and_no_rpc():
    client = FakeClient()
    calls = []

    result = execute_run_candidates(
        client,
        RUN["run_id"],
        replay=FakeReplay(_contract(bid=1.20, ask=1.00)),
        rpc_caller=lambda *args: calls.append(args),
    )

    assert result["counts"]["filled_internal"] == 0
    assert result["counts"]["execution_rejected"] == 1
    assert calls == []
    attempts = client.inserts["single_leg_shadow_attempts"]
    assert attempts[0]["stage"] == "execution_rejected"
    assert attempts[0]["reason_code"] == "execution_quote_crossed"
    events = client.inserts["single_leg_shadow_lifecycle_events"]
    assert events[0]["event_type"] == "execution_rejected"


def test_execution_revalidates_policy_debit_cap():
    client = FakeClient(policy_cap=90.0)
    calls = []
    result = execute_run_candidates(
        client,
        RUN["run_id"],
        replay=FakeReplay(_contract(bid=0.90, ask=1.00)),
        rpc_caller=lambda *args: calls.append(args),
    )
    assert result["counts"]["execution_rejected"] == 1
    assert calls == []
    assert client.inserts["single_leg_shadow_attempts"][0]["reason_code"] == (
        "execution_debit_exceeds_max"
    )


def _position():
    return {
        "position_id": "77777777-7777-7777-7777-777777777777",
        "run_id": RUN["run_id"],
        "policy_registration_id": RUN["policy_registration_id"],
        "portfolio_id": RUN["portfolio_id"],
        "user_id": RUN["user_id"],
        "candidate_fingerprint": ATTEMPT["candidate_fingerprint"],
        "symbol": "SPY",
        "expiry": "2026-07-22",
        "status": "open",
    }


def test_expiry_settlement_uses_market_truth_and_internal_close_rpc():
    client = FakeClient(positions=[_position()])
    calls = []

    def rpc(name, params):
        calls.append((name, params))
        return SimpleNamespace(
            data={
                "status": "closed",
                "idempotent_replay": False,
                "outcome_id": "outcome-1",
            }
        )

    result = settle_expired_positions(
        client,
        RUN["user_id"],
        as_of=datetime(2026, 7, 22, 20, 0, tzinfo=timezone.utc),
        snapshot_fetcher=lambda symbols: {
            "SPY": SimpleNamespace(quote=SimpleNamespace(last=130.0, mid=129.9, bid=129.8))
        },
        rpc_caller=rpc,
    )

    assert result["status"] == "succeeded"
    assert result["counts"]["closed"] == 1
    assert [name for name, _ in calls] == [CLOSE_RPC]
    assert calls[0][1]["p_terminal_spot"] == 130.0
    assert calls[0][1]["p_close_reason"] == "expiry"


def test_missing_expiry_spot_defers_without_fabricating_zero():
    client = FakeClient(positions=[_position()])
    calls = []
    result = settle_expired_positions(
        client,
        RUN["user_id"],
        as_of=datetime(2026, 7, 22, 20, 0, tzinfo=timezone.utc),
        snapshot_fetcher=lambda symbols: {"SPY": SimpleNamespace(quote=SimpleNamespace())},
        rpc_caller=lambda *args: calls.append(args),
    )
    assert result["counts"]["closed"] == 0
    assert result["counts"]["deferred"] == 1
    assert calls == []
    event = client.inserts["single_leg_shadow_lifecycle_events"][0]
    assert event["event_type"] == "settlement_deferred"
    assert event["payload"]["reason"] == "terminal_spot_unavailable"
