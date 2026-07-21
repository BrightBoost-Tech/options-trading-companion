from types import SimpleNamespace

from packages.quantum.services.single_leg_shadow_evidence import (
    SingleLegShadowEvidenceWriter,
    candidate_fingerprint,
)


class FakeQuery:
    def __init__(self, client, table):
        self.client = client
        self.table = table
        self.operation = None
        self.payload = None
        self.filters = []

    def upsert(self, payload, on_conflict=None):
        self.operation = "upsert"
        self.payload = payload
        self.on_conflict = on_conflict
        return self

    def update(self, payload):
        self.operation = "update"
        self.payload = payload
        return self

    def select(self, columns):
        self.operation = "select"
        self.columns = columns
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def limit(self, n):
        self.limit_value = n
        return self

    def execute(self):
        self.client.calls.append(self)
        if self.table == "single_leg_shadow_runs" and self.operation == "upsert":
            return SimpleNamespace(data=[{"run_id": "11111111-1111-1111-1111-111111111111"}])
        return SimpleNamespace(data=[])


class FakeClient:
    def __init__(self):
        self.calls = []

    def table(self, name):
        return FakeQuery(self, name)


def _writer(client=None):
    return SingleLegShadowEvidenceWriter(
        client or FakeClient(),
        source_job_run_id="22222222-2222-2222-2222-222222222222",
        source_decision_id="33333333-3333-3333-3333-333333333333",
        user_id="44444444-4444-4444-4444-444444444444",
        policy_registration_id="sl_exp_throughput_v1",
        portfolio_id="55555555-5555-5555-5555-555555555555",
        source_code_sha="a" * 40,
        as_of="2026-07-21T16:00:00+00:00",
    )


def test_candidate_fingerprint_excludes_changing_economics():
    base = {
        "policy_registration_id": "sl_exp_throughput_v1",
        "symbol": "SPY",
        "strategy_type": "long_call",
        "occ_symbol": "SPY260821C00650000",
        "strike": 650.0,
        "expiry": "2026-08-21",
        "option_type": "call",
        "contracts": 1,
        "debit_per_contract": 100.0,
        "ev_expected_value": 12.0,
    }
    changed = {**base, "debit_per_contract": 120.0, "ev_expected_value": 20.0}
    assert candidate_fingerprint(base) == candidate_fingerprint(changed)


def test_writer_records_run_attempt_event_and_terminal_status():
    client = FakeClient()
    writer = _writer(client)
    assert writer.begin_run() == "11111111-1111-1111-1111-111111111111"

    candidate = {
        "policy_registration_id": "sl_exp_throughput_v1",
        "symbol": "SPY",
        "strategy_type": "long_call",
        "option_type": "call",
        "occ_symbol": "SPY260821C00650000",
        "strike": 650.0,
        "expiry": "2026-08-21",
        "contracts": 1,
        "debit_per_contract": 100.0,
        "ev_expected_value": 15.0,
        "known_at": "2026-07-21T16:00:00+00:00",
    }
    assert writer.record_attempt(
        symbol="SPY",
        stage="candidate_generated",
        direction="bullish",
        strategy_type="long_call",
        candidate=candidate,
        evidence={"iv_rank": 10.0},
        considered_contracts=8,
        viable_contracts=2,
    )
    fp = candidate_fingerprint(candidate)
    assert writer.record_event(
        event_type="candidate_generated",
        entity_type="candidate",
        entity_id=fp,
        candidate_fingerprint_value=fp,
    )
    assert writer.finish_run(status="succeeded", counts={"candidates": 1})

    counters = writer.counters_dict()
    assert counters == {
        "runs_started": 1,
        "attempts_written": 1,
        "events_written": 1,
        "write_failures": 0,
        "table_missing_noops": 0,
    }
    tables = [call.table for call in client.calls]
    assert tables == [
        "single_leg_shadow_runs",
        "single_leg_shadow_attempts",
        "single_leg_shadow_lifecycle_events",
        "single_leg_shadow_runs",
    ]


def test_writer_does_not_write_without_a_run_identity():
    client = FakeClient()
    writer = _writer(client)
    assert not writer.record_attempt(symbol="SPY", stage="gate_rejected")
    assert not writer.record_event(
        event_type="execution_rejected",
        entity_type="candidate",
        entity_id="x",
    )
    assert client.calls == []
