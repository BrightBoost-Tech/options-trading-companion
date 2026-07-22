from types import SimpleNamespace

from packages.quantum.services.single_leg_shadow_reader import (
    fetch_single_leg_shadow_sections,
    summarize_single_leg_shadow_sections,
)
from scripts.analytics.single_leg_shadow_report import (
    redacted_report_payload,
    render_markdown,
)


USER = "44444444-4444-4444-4444-444444444444"


class Query:
    def __init__(self, client, table):
        self.client = client
        self.table = table
        self.filters = []

    def select(self, columns):
        self.columns = columns
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def execute(self):
        if self.table in self.client.fail:
            raise RuntimeError(f"{self.table} unavailable")
        rows = [dict(row) for row in self.client.tables.get(self.table, [])]
        for column, value in self.filters:
            rows = [row for row in rows if row.get(column) == value]
        return SimpleNamespace(data=rows)


class Client:
    def __init__(self, fail=()):
        self.fail = set(fail)
        self.tables = {
            "single_leg_experiment_epochs": [
                {
                    "epoch_name": "single_leg_experiment_v1",
                    "state": "enabled",
                    "routing_mode": "shadow_only",
                    "max_contracts": 1,
                    "live_submit_allowed": False,
                    "version": 1,
                }
            ],
            "policy_registrations": [
                {
                    "policy_registration_id": "sl_exp_throughput_v1",
                    "effective_epoch": "single_leg_experiment_v1",
                    "approval_status": "approved",
                    "policy_config": {"single_leg_experiment_enabled": True},
                },
                {
                    "policy_registration_id": "sl_ctrl_throughput_v1",
                    "effective_epoch": "single_leg_experiment_v1",
                    "approval_status": "approved",
                    "policy_config": {},
                },
            ],
            "single_leg_experiment_bindings": [
                {
                    "policy_registration_id": "sl_exp_throughput_v1",
                    "epoch_name": "single_leg_experiment_v1",
                    "user_id": USER,
                    "role": "experimental",
                    "enabled": True,
                    "routing_mode": "shadow_only",
                    "execution_mode": "internal_paper",
                }
            ],
            "single_leg_shadow_runs": [
                {
                    "run_id": "run-1",
                    "policy_epoch": "single_leg_experiment_v1",
                    "policy_registration_id": "sl_exp_throughput_v1",
                    "user_id": USER,
                    "status": "succeeded",
                    "as_of": "2026-07-22T16:00:00Z",
                }
            ],
            "single_leg_shadow_attempts": [
                {
                    "attempt_id": "a1",
                    "run_id": "run-1",
                    "policy_registration_id": "sl_exp_throughput_v1",
                    "user_id": USER,
                    "stage": "selection_rejected",
                    "reason_code": "directional_signal_weak",
                    "symbol": "IWM",
                },
                {
                    "attempt_id": "a2",
                    "run_id": "run-1",
                    "policy_registration_id": "sl_exp_throughput_v1",
                    "user_id": USER,
                    "stage": "candidate_generated",
                    "reason_code": None,
                    "symbol": "SPY",
                },
            ],
            "single_leg_shadow_lifecycle_events": [
                {
                    "event_id": "e1",
                    "run_id": "run-1",
                    "policy_registration_id": "sl_exp_throughput_v1",
                    "user_id": USER,
                    "event_type": "filled_internal",
                }
            ],
            "single_leg_shadow_orders": [
                {
                    "order_id": "o1",
                    "run_id": "run-1",
                    "policy_registration_id": "sl_exp_throughput_v1",
                    "user_id": USER,
                    "contracts": 1,
                    "routing_mode": "shadow_only",
                    "execution_mode": "internal_paper",
                    "live_submit_allowed": False,
                    "filled_at": "2026-07-22T16:00:01Z",
                }
            ],
            "single_leg_shadow_positions": [
                {
                    "position_id": "p1",
                    "policy_registration_id": "sl_exp_throughput_v1",
                    "user_id": USER,
                    "status": "closed",
                    "routing_mode": "shadow_only",
                    "execution_mode": "internal_paper",
                    "live_submit_allowed": False,
                }
            ],
            "single_leg_shadow_outcomes": [
                {
                    "outcome_id": "out1",
                    "policy_registration_id": "sl_exp_throughput_v1",
                    "user_id": USER,
                    "realized_pnl": "25.50",
                    "execution_mode": "internal_paper",
                    "closed_at": "2026-08-21T20:00:00Z",
                }
            ],
            "single_leg_shadow_cash_events": [],
        }

    def table(self, name):
        return Query(self, name)


def test_reader_keeps_empty_and_failed_sections_distinct():
    sections = fetch_single_leg_shadow_sections(
        Client(fail={"single_leg_shadow_cash_events"}), USER
    )
    assert sections["cash_events"]["status"] == "FAILED-FETCH"
    assert sections["events"]["status"] == "OK"
    assert sections["positions"]["status"] == "OK"

    summary = summarize_single_leg_shadow_sections(sections)
    assert summary["status"] == "PARTIAL"
    assert summary["failed_sections"] == ["cash_events"]
    assert summary["headline"]["runs"] == 1
    assert summary["headline"]["attempts"] == 2
    assert summary["headline"]["generated_candidates"] == 1
    assert summary["headline"]["internal_fills"] == 1
    assert summary["headline"]["closed_positions"] == 1
    assert summary["headline"]["outcomes"] == 1
    assert summary["headline"]["realized_pnl"] == 25.5


def test_reader_preserves_policy_control_and_isolation_axes():
    sections = fetch_single_leg_shadow_sections(Client(), USER)
    summary = summarize_single_leg_shadow_sections(sections)
    assert summary["status"] == "OK"
    assert summary["policy_counts"]["opt_in_policy_ids"] == [
        "sl_exp_throughput_v1"
    ]
    assert summary["policies"]["sl_exp_throughput_v1"][
        "matched_control_family"
    ] == "aggressive"
    assert summary["isolation"] == {
        "routing_modes": ["shadow_only"],
        "execution_modes": ["internal_paper"],
        "live_submit_true_rows": 0,
        "non_one_contract_orders": 0,
    }
    assert summary["rejections"] == [
        {
            "stage": "selection_rejected",
            "reason_code": "directional_signal_weak",
            "count": 1,
        }
    ]


def test_report_artifacts_are_deterministic_and_redact_user_rows():
    sections = fetch_single_leg_shadow_sections(Client(), USER)
    raw = {
        "epoch": "single_leg_experiment_v1",
        "generated_at": "2026-07-22T20:00:00+00:00",
        "summary": summarize_single_leg_shadow_sections(sections),
        "sections": sections,
    }
    payload = redacted_report_payload(raw)
    first = render_markdown(payload)
    second = render_markdown(payload)
    assert first == second
    assert USER not in first
    assert USER not in str(payload)
    assert payload["sections"]["orders"]["row_count"] == 1
    assert "internal_paper" in first
    assert "live_submit_allowed=true rows: **0**" in first
