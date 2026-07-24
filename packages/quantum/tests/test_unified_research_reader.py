"""Tests for the unified counterfactual research reader.

Covers: deterministic render via a mocked paginating client; the six-state
honesty vocabulary (FAILED-FETCH != HONEST-EMPTY != UNAVAILABLE); absent-table
tolerance (typed UNAVAILABLE so the reader merges cleanly regardless of sibling
lane merge order); explicit pagination proven (a >ceiling table pages completely
AND a typed hard cap); read-only (any write verb raises); and cohorts never
conflated.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from scripts.analytics.unified_research_reader import (
    ACTUAL,
    COUNTERFACTUAL,
    FAILED_FETCH,
    HONEST_EMPTY,
    OBSERVE_ONLY,
    SECTION_STATES,
    STUDY_SQL,
    TABLE_SPECS,
    UNAVAILABLE,
    TableSpec,
    build_report,
    fetch_all,
    paginate,
    render_markdown,
)

GENERATED = "2026-07-23T00:00:00+00:00"


# ── paginating mock client ──────────────────────────────────────────────────
class _Query:
    def __init__(self, client, table):
        self.client = client
        self.table = table
        self.filters = []
        self._order = []
        self._range = None

    def select(self, columns):
        self.columns = columns
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def order(self, column, desc=False):
        self._order.append((column, desc))
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    # Write verbs must never be reached by a read-only reader.
    def insert(self, *a, **k):
        raise AssertionError("insert() called — reader must be READ-ONLY")

    def update(self, *a, **k):
        raise AssertionError("update() called — reader must be READ-ONLY")

    def delete(self, *a, **k):
        raise AssertionError("delete() called — reader must be READ-ONLY")

    def upsert(self, *a, **k):
        raise AssertionError("upsert() called — reader must be READ-ONLY")

    def execute(self):
        if self.table in self.client.absent:
            raise RuntimeError(
                f'relation "public.{self.table}" does not exist (SQLSTATE 42P01)'
            )
        if self.table in self.client.fail_hard:
            raise RuntimeError(f"{self.table}: connection reset by peer")
        rows = [dict(r) for r in self.client.tables.get(self.table, [])]
        for column, value in self.filters:
            rows = [r for r in rows if r.get(column) == value]
        for column, desc in reversed(self._order):
            rows.sort(
                key=lambda r: (
                    r.get(column) is None,
                    r.get(column) if r.get(column) is not None else "",
                ),
                reverse=desc,
            )
        if self._range is not None:
            start, end = self._range
            rows = rows[start:end + 1]
        return SimpleNamespace(data=rows)


class _Client:
    def __init__(self, tables=None, *, absent=(), fail_hard=()):
        self.tables = tables or {}
        self.absent = set(absent)
        self.fail_hard = set(fail_hard)

    def table(self, name):
        return _Query(self, name)

    def rpc(self, *a, **k):
        raise AssertionError("rpc() called — reader must be READ-ONLY")


# ── sample data covering every sink ─────────────────────────────────────────
def _scan_rows():
    return [
        {  # resolved winner, emitted, debit
            "cycle_id": "C1", "candidate_fingerprint": "F1",
            "challenger_model_version": "m1", "symbol": "SPY",
            "strategy": "debit_spread", "emitted": True,
            "baseline_pop": 0.5, "baseline_ev": 10.0,
            "challenger_pop": 0.6, "challenger_ev": 12.0,
            "production_pop": 0.55, "production_ev": 11.0,
            "outcome_status": "resolved", "realized_pnl": 100.0,
            "realized_win": True, "reject_gate": None,
            "baseline_abstain_reason": None, "challenger_abstain_reason": None,
        },
        {  # rejected credit spread — EV-gate FLIP (base<0, challenger>=0)
            "cycle_id": "C1", "candidate_fingerprint": "F2",
            "challenger_model_version": "m1", "symbol": "SPY",
            "strategy": "credit_spread", "emitted": False,
            "baseline_pop": 0.4, "baseline_ev": -1.0,
            "challenger_pop": 0.45, "challenger_ev": 2.0,
            "production_pop": None, "production_ev": None,
            "outcome_status": "counterfactual_unmarkable", "realized_pnl": None,
            "realized_win": None, "reject_gate": "execution_cost",
            "baseline_abstain_reason": None, "challenger_abstain_reason": None,
        },
        {  # rejected condor — drives a rank swap in C1
            "cycle_id": "C1", "candidate_fingerprint": "F3",
            "challenger_model_version": "m1", "symbol": "SPY",
            "strategy": "iron_condor", "emitted": False,
            "baseline_pop": 0.7, "baseline_ev": 11.0,
            "challenger_pop": 0.3, "challenger_ev": 1.0,
            "production_pop": None, "production_ev": None,
            "outcome_status": "counterfactual_unmarkable", "realized_pnl": None,
            "realized_win": None, "reject_gate": "spread",
            "baseline_abstain_reason": None, "challenger_abstain_reason": None,
        },
        {  # resolved loser, emitted, single candidate in C2
            "cycle_id": "C2", "candidate_fingerprint": "F4",
            "challenger_model_version": "m1", "symbol": "QQQ",
            "strategy": "debit_spread", "emitted": True,
            "baseline_pop": 0.5, "baseline_ev": 5.0,
            "challenger_pop": 0.5, "challenger_ev": 5.0,
            "production_pop": 0.5, "production_ev": 5.0,
            "outcome_status": "resolved", "realized_pnl": -50.0,
            "realized_win": False, "reject_gate": None,
            "baseline_abstain_reason": None, "challenger_abstain_reason": None,
        },
        {  # open, challenger ABSTAINS (challenger_pop null)
            "cycle_id": "C2", "candidate_fingerprint": "F5",
            "challenger_model_version": "m1", "symbol": "QQQ",
            "strategy": "debit_spread", "emitted": True,
            "baseline_pop": 0.5, "baseline_ev": 5.0,
            "challenger_pop": None, "challenger_ev": None,
            "production_pop": 0.5, "production_ev": 5.0,
            "outcome_status": "open", "realized_pnl": None,
            "realized_win": None, "reject_gate": None,
            "baseline_abstain_reason": None,
            "challenger_abstain_reason": "insufficient_iv",
        },
    ]


def _regime_rows():
    return [
        {"scope": "global", "cycle_id": "C1", "symbol": None, "code_sha": "sha1",
         "v3_global_state": "NORMAL", "v3_state": "NORMAL", "v4_label": "normal",
         "state_agree": True, "scoring_regime_agree": True, "status": "ok",
         "selection_delta": None, "missing_inputs": []},
        {"scope": "global", "cycle_id": "C2", "symbol": None, "code_sha": "sha1",
         "v3_global_state": "CHOP", "v3_state": "CHOP", "v4_label": "elevated",
         "state_agree": False, "scoring_regime_agree": False, "status": "ok",
         "selection_delta": None, "missing_inputs": []},
        {"scope": "symbol", "cycle_id": "C1", "symbol": "SPY", "code_sha": "sha1",
         "scoring_regime_agree": True, "status": "ok",
         "selection_delta": {"added": ["iron_condor"], "removed": [], "changed": True},
         "missing_inputs": ["vix_unavailable_no_entitlement"]},
        {"scope": "symbol", "cycle_id": "C1", "symbol": "QQQ", "code_sha": "sha1",
         "scoring_regime_agree": True, "status": "ok",
         "selection_delta": {"added": [], "removed": [], "changed": False},
         "missing_inputs": ["vix_unavailable_no_entitlement"]},
    ]


def _fleet_runs_rows():
    return [
        {"run_id": "r1", "source_decision_id": "C1", "shadow_micro_account_id": "acc1",
         "policy_registration_id": "p1", "status": "succeeded",
         "evaluator_version": "fleet-eval/1",
         "counts": {"candidates_seen": 5, "selected": 1,
                    "policy_rejected": 3, "capital_rejected": 1}},
        {"run_id": "r2", "source_decision_id": "C1", "shadow_micro_account_id": "acc2",
         "policy_registration_id": "p2", "status": "partial",
         "evaluator_version": "fleet-eval/1",
         "counts": {"candidates_seen": 5, "selected": 0,
                    "policy_rejected": 4, "capital_rejected": 1}},
    ]


def _fleet_decisions_rows():
    # decision_event_id E1 appears for BOTH micro-accounts — evidence n must be
    # DISTINCT decision_event_id (2), never the row count (4).
    return [
        {"id": "d1", "run_id": "r1", "shadow_micro_account_id": "acc1",
         "decision_event_id": "E1", "disposition": "selected"},
        {"id": "d2", "run_id": "r1", "shadow_micro_account_id": "acc1",
         "decision_event_id": "E2", "disposition": "policy_rejected"},
        {"id": "d3", "run_id": "r2", "shadow_micro_account_id": "acc2",
         "decision_event_id": "E1", "disposition": "policy_rejected"},
        {"id": "d4", "run_id": "r2", "shadow_micro_account_id": "acc2",
         "decision_event_id": "E2", "disposition": "capital_rejected"},
    ]


def _fleet_readiness_rows():
    fleets = [{"id": "fx", "epoch_name": "small_tier_v1",
               "status": "pending_legacy_terminal", "micro_account_count": 50,
               "capital_per_account": 2000, "shared_capital_enabled": False}]
    micro = [{"fleet_id": "fx", "slot_number": i,
              "policy_registration_id": None, "state": "inactive"} for i in (1, 2, 3)]
    return fleets, micro


def _full_client(**kw):
    fleets, micro = _fleet_readiness_rows()
    return _Client({
        "terminal_distribution_scan_scores": _scan_rows(),
        "regime_v4_comparisons": _regime_rows(),
        "fleet_policy_decision_runs": _fleet_runs_rows(),
        "fleet_policy_decisions": _fleet_decisions_rows(),
        "shadow_fleets": fleets,
        "shadow_micro_accounts": micro,
    }, **kw)


def _sections(report):
    return {s.name: s for s in report.sections}


# ── tests ───────────────────────────────────────────────────────────────────
def test_paginate_pages_completely_and_caps():
    spec = TableSpec("big_table", "x", ("x",))
    big = _Client({"big_table": [{"x": i} for i in range(2500)]})

    # Pages through the whole 2500-row table in 1000-row pages.
    full = paginate(big, spec, page_size=1000, max_rows=100000)
    assert full.status == "ok"
    assert full.n_fetched == 2500
    assert full.pages == 3
    assert full.truncated is False
    assert [r["x"] for r in full.rows] == list(range(2500))

    # A hard cap below the table size returns a TYPED truncation, not a silent
    # partial read.
    capped = paginate(big, spec, page_size=1000, max_rows=2000)
    assert capped.truncated is True
    assert capped.n_fetched == 2000
    assert capped.pages == 2


def test_truncation_surfaces_in_report_and_render():
    spec = TABLE_SPECS["scan_scores"]
    # 3 scan rows but a max_rows of 2 forces a cap on the scan sink.
    fetched = fetch_all(_full_client(), max_rows=2, page_size=2)
    assert fetched["scan_scores"].truncated is True
    report = build_report(fetched, generated_at=GENERATED)
    assert report.any_truncation is True
    secs = _sections(report)
    assert secs["td_coverage"].truncated is True
    md = render_markdown(report)
    assert "TRUNCATION" in md
    assert "LOWER BOUND" in md
    # spec unused beyond documenting the sink under test
    assert spec.table == "terminal_distribution_scan_scores"


def test_render_is_deterministic_with_mock_client():
    fetched = fetch_all(_full_client())
    r1 = build_report(fetched, generated_at=GENERATED, cycle_date="2026-07-23")
    r2 = build_report(fetch_all(_full_client()), generated_at=GENERATED,
                      cycle_date="2026-07-23")
    assert render_markdown(r1) == render_markdown(r2)
    assert json.dumps(r1.as_dict(), sort_keys=True, default=str) == \
        json.dumps(r2.as_dict(), sort_keys=True, default=str)


def test_six_state_vocabulary_and_state_summary_exact():
    report = build_report(fetch_all(_full_client()), generated_at=GENERATED)
    for sec in report.sections:
        assert sec.state in SECTION_STATES
    summary = report.as_dict()["state_summary"]
    assert set(summary.keys()) == set(SECTION_STATES)
    # Every sink readable & populated: 1 ACTUAL, 4 COUNTERFACTUAL, 3 OBSERVE_ONLY.
    assert summary[ACTUAL] == 1
    assert summary[COUNTERFACTUAL] == 4
    assert summary[OBSERVE_ONLY] == 3
    assert summary[FAILED_FETCH] == 0
    assert summary[UNAVAILABLE] == 0
    assert summary[HONEST_EMPTY] == 0


def test_absent_lane_tables_are_unavailable_not_failed():
    # The three sibling lanes have NOT merged their tables yet.
    client = _full_client(absent=(
        "terminal_distribution_scan_scores",
        "regime_v4_comparisons",
        "fleet_policy_decision_runs",
        "fleet_policy_decisions",
    ))
    report = build_report(fetch_all(client), generated_at=GENERATED)
    secs = _sections(report)
    for name in ("td_coverage", "td_head_to_head", "regime_global",
                 "regime_symbol", "fleet_runs", "fleet_decisions"):
        assert secs[name].state == UNAVAILABLE, name
        assert "table_absent" in (secs[name].reason or "")
    # The pre-existing fleet readiness tables still read fine.
    assert secs["fleet_readiness"].state == OBSERVE_ONLY
    # cohort_linked's primary surface (scan_scores) is absent -> UNAVAILABLE.
    assert secs["cohort_linked"].state == UNAVAILABLE


def test_failed_fetch_is_distinct_from_honest_empty():
    # scan_scores present-but-empty (HONEST-EMPTY); regime read errors hard
    # (FAILED-FETCH). The two must never collapse to the same state.
    fleets, micro = _fleet_readiness_rows()
    client = _Client({
        "terminal_distribution_scan_scores": [],
        "regime_v4_comparisons": [],
        "fleet_policy_decision_runs": [],
        "fleet_policy_decisions": [],
        "shadow_fleets": fleets,
        "shadow_micro_accounts": micro,
    }, fail_hard=("regime_v4_comparisons",))
    report = build_report(fetch_all(client), generated_at=GENERATED)
    secs = _sections(report)
    assert secs["td_coverage"].state == HONEST_EMPTY
    assert secs["regime_global"].state == FAILED_FETCH
    assert secs["regime_global"].reason  # carries the error string
    assert secs["fleet_runs"].state == HONEST_EMPTY
    assert HONEST_EMPTY != FAILED_FETCH


def test_reader_is_read_only():
    # A full fetch completes with a client whose write verbs raise on contact.
    client = _full_client()
    fetched = fetch_all(client)  # must NOT raise
    assert all(fr.status == "ok" for fr in fetched.values())
    # And the guard is real — a write verb raises.
    import pytest
    with pytest.raises(AssertionError):
        client.table("terminal_distribution_scan_scores").insert({"x": 1})
    with pytest.raises(AssertionError):
        client.rpc("anything")


def test_cohorts_are_never_conflated():
    report = build_report(fetch_all(_full_client()), generated_at=GENERATED)
    sec = _sections(report)["cohort_linked"]
    assert sec.state == ACTUAL
    summary = sec.summary
    # Two explicitly separate buckets.
    scan_bucket = summary["scan_attribution_unavailable"]
    fleet_bucket = summary["fleet_shadow"]
    assert scan_bucket["cohort_label"] == "scan_attribution_unavailable"
    assert fleet_bucket["cohort_label"] == "fleet_shadow"
    # Realized aggregates computed WITHIN the scan bucket only.
    assert scan_bucket["n_resolved"] == 2
    assert scan_bucket["realized_pnl_total"] == 50.0  # 100 + (-50)
    assert scan_bucket["realized_pnl_mean"] == 25.0
    assert scan_bucket["win_rate_of_resolved"] == 0.5
    assert scan_bucket["n_counterfactual_unmarkable"] == 2
    # Fleet-shadow bucket is separate, shadow_only, never pooled with the scan
    # realized total.
    assert fleet_bucket["routing"] == "shadow_only"
    assert fleet_bucket["n_selected_would_execute"] == 1
    # There is no key that sums the two cohorts together.
    assert "realized_pnl_total" not in fleet_bucket
    assert "combined" not in summary and "total" not in summary


def test_terminal_distribution_coverage_and_head_to_head_numbers():
    report = build_report(fetch_all(_full_client()), generated_at=GENERATED)
    secs = _sections(report)
    cov = secs["td_coverage"].summary
    assert cov["n_candidates"] == 5
    assert cov["n_emitted"] == 3 and cov["n_rejected"] == 2
    assert cov["credit_spread_coverage"] == 1
    assert cov["condor_coverage"] == 1
    assert cov["n_baseline_scored"] == 5
    assert cov["n_challenger_scored"] == 4  # F5 challenger abstained
    assert cov["challenger_abstain_reasons"] == {"insufficient_iv": 1}
    assert cov["by_strategy"] == {"credit_spread": 1, "debit_spread": 3,
                                  "iron_condor": 1}

    h2h = secs["td_head_to_head"].summary
    assert h2h["n_jointly_scored"] == 4  # F5 excluded (challenger null)
    assert h2h["ev_gate_flips"] == 1  # F2: baseline -1 < 0, challenger 2 >= 0
    assert h2h["baseline_only_scored"] == 1  # F5
    assert h2h["rank_swaps"]["n_cycles_ranked"] == 1  # only C1 has >=2 joint
    assert h2h["rank_swaps"]["cycles_with_rank_swap"] == 1
    assert h2h["rank_swaps"]["total_position_changes"] == 3


def test_regime_agreement_and_selection_deltas():
    report = build_report(fetch_all(_full_client()), generated_at=GENERATED)
    secs = _sections(report)
    g = secs["regime_global"].summary
    assert g["n_global_rows"] == 2
    assert g["state_agree"]["rate"] == 0.5
    assert g["scoring_regime_agree"]["rate"] == 0.5
    s = secs["regime_symbol"].summary
    assert s["n_symbol_rows"] == 2
    assert s["n_selection_changed"] == 1
    assert s["added_strategies"] == {"iron_condor": 1}
    assert s["missing_inputs"] == {"vix_unavailable_no_entitlement": 2}


def test_fleet_runs_and_evidence_n_distinct_decision_event():
    report = build_report(fetch_all(_full_client()), generated_at=GENERATED)
    secs = _sections(report)
    runs = secs["fleet_runs"].summary
    assert runs["n_runs"] == 2
    assert runs["by_status"] == {"partial": 1, "succeeded": 1}
    assert runs["counts_total"] == {"candidates_seen": 10, "selected": 1,
                                    "policy_rejected": 7, "capital_rejected": 2}
    assert runs["n_distinct_source_events"] == 1
    assert runs["n_distinct_policies"] == 2

    dec = secs["fleet_decisions"].summary
    assert dec["n_decision_rows"] == 4
    # The doctrine unit — DISTINCT decision_event_id, NOT the 4 rows.
    assert dec["evidence_n_distinct_decision_events"] == 2
    assert dec["by_disposition"] == {"capital_rejected": 1,
                                     "policy_rejected": 2, "selected": 1}


def test_fleet_readiness_reports_inactive_no_op():
    report = build_report(fetch_all(_full_client()), generated_at=GENERATED)
    r = _sections(report)["fleet_readiness"].summary
    assert r["readiness_verdict"] == "inactive_no_op"
    assert r["fleet_status_distribution"] == {"pending_legacy_terminal": 1}
    assert r["n_bound_to_policy"] == 0
    assert r["n_active"] == 0


def test_emit_sql_is_read_only_and_guarded():
    sql = STUDY_SQL.lower()
    assert "to_regclass" in sql
    for spec in TABLE_SPECS.values():
        assert spec.table in sql
    for verb in ("insert", "update", "delete", "drop", "alter", "upsert"):
        assert verb not in sql
