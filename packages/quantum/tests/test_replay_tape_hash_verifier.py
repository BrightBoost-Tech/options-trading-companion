"""Persisted replay-tape hash reader contract."""

from types import SimpleNamespace

from packages.quantum.services.replay.canonical import compute_aggregate_hash
from packages.quantum.services.replay.tape_hash_verifier import (
    verify_decision_tape_hashes,
)


class _Query:
    def __init__(self, client, table):
        self.client = client
        self.table = table

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, _column, value):
        self.decision_id = value
        return self

    def single(self):
        self.is_single = True
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def execute(self):
        if self.table == "decision_runs" and getattr(self, "is_single", False):
            value = self.client.headers.get(self.decision_id)
        else:
            value = self.client.rows[self.table]
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(data=value)


class _Client:
    def __init__(self, rows, headers=None):
        self.rows = rows
        run = rows.get("decision_runs")
        self.headers = headers or (
            {run.get("decision_id"): run} if isinstance(run, dict) else {}
        )

    def table(self, name):
        return _Query(self, name)


def _rows():
    input_hashes = ["b" * 64, "a" * 64]
    feature_hashes = ["d" * 64, "c" * 64]
    return {
        "decision_runs": {
            "decision_id": "decision",
            "input_hash": compute_aggregate_hash(sorted(input_hashes)),
            "features_hash": compute_aggregate_hash(sorted(feature_hashes)),
            "inputs_count": 2,
            "features_count": 2,
            "tape_integrity": "complete",
        },
        "decision_inputs": [{"blob_hash": value} for value in input_hashes],
        "decision_features": [
            {"features_hash": value} for value in feature_hashes
        ],
    }


def test_complete_tape_recomputes_both_aggregate_hashes_and_counts():
    result = verify_decision_tape_hashes(_Client(_rows()), "decision")

    assert result["status"] == "ok"
    assert result["mismatches"] == []
    assert result["counts"]["errors"] == 0


def test_tampered_feature_link_is_typed_mismatch():
    rows = _rows()
    rows["decision_features"][0]["features_hash"] = "e" * 64

    result = verify_decision_tape_hashes(_Client(rows), "decision")

    assert result["status"] == "mismatch"
    assert result["reason"] == "tape_hash_mismatch"
    assert "features_hash" in result["mismatches"]
    assert result["counts"]["errors"] == 1


def test_read_failure_is_not_a_clean_empty_tape():
    rows = _rows()
    rows["decision_inputs"] = RuntimeError("database unavailable")

    result = verify_decision_tape_hashes(_Client(rows), "decision")

    assert result["status"] == "error"
    assert result["reason"] == "tape_read_failed"
    assert result["counts"]["errors"] == 1


def test_missing_decision_is_typed_error():
    rows = _rows()
    rows["decision_runs"] = None

    result = verify_decision_tape_hashes(_Client(rows), "missing")

    assert result["status"] == "error"
    assert result["reason"] == "decision_not_found"


def test_job_handler_reads_recent_complete_tapes_and_surfaces_mismatch():
    from packages.quantum.jobs.handlers import replay_integrity_check

    first = _rows()
    second = _rows()
    second["decision_runs"] = dict(second["decision_runs"], decision_id="second")
    second["decision_runs"]["features_hash"] = "e" * 64
    client = _Client(
        {
            "decision_runs": [
                {"decision_id": "decision"},
                {"decision_id": "second"},
            ],
            "decision_inputs": first["decision_inputs"],
            "decision_features": first["decision_features"],
        },
        headers={
            "decision": first["decision_runs"],
            "second": second["decision_runs"],
        },
    )
    original = replay_integrity_check.get_admin_client
    replay_integrity_check.get_admin_client = lambda: client
    try:
        result = replay_integrity_check.run({"limit": 20})
    finally:
        replay_integrity_check.get_admin_client = original

    # The fake returns the same child rows for both headers; the second header
    # therefore disagrees with those rows and must make the top-level job
    # partial rather than green.
    assert result["status"] == "partial"
    assert result["counts"] == {"checked": 2, "mismatches": 1, "errors": 1}
    assert result["live_reads"] == 0
