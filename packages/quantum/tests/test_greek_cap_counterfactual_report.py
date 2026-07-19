"""Tests for the greek-cap counterfactual would-block frequency runner
(``scripts/analytics/greek_cap_counterfactual_report.py``).

OBSERVE-ONLY glue over the ``risk_envelope`` counterfactual, read from the
monitor's accrued ``job_runs.result`` summaries. Pinned with SYNTHETIC payloads
(NO live DB):

1. build_study tallies would_block states per reference row (True → block,
   False → no-block, None → typed UNAVAILABLE, COUNTED not scored).
2. an available:false cycle marks EVERY reference row unavailable (H9 — the
   whole cycle's greeks were dark; never scored as "would not block").
3. blocking-greek attribution + block-rate-of-evaluable arithmetic.
4. malformed / partial elements are skipped, never crash the study.
5. render_markdown smoke, incl. the double-dormancy note when all-unavailable.
6. STUDY_SQL is a strictly read-only single SELECT over job_runs.
"""

from scripts.analytics.greek_cap_counterfactual_report import (
    STUDY_SQL,
    build_study,
    render_markdown,
)


def _avail(rows):
    return {"greek_cap_counterfactual": {"available": True, "rows": rows}}


def _row(name, would_block, blocking=(), unavailable=()):
    return {"name": name, "would_block": would_block,
            "blocking_greeks": list(blocking), "unavailable_greeks": list(unavailable)}


def _payload(elements):
    return {"generated_at": "2026-07-18", "source": "test",
            "model_version": "greek-cap-counterfactual-report/1.0", "rows": elements}


def test_tallies_block_noblock_unavailable_states():
    payload = _payload([
        _avail([_row("tight", True, blocking=["vega"]),
                _row("medium", False),
                _row("loose", None)]),
        _avail([_row("tight", True, blocking=["vega", "delta"]),
                _row("medium", True, blocking=["delta"]),
                _row("loose", False)]),
    ])
    study = build_study(payload)
    rows = {r.name: r for r in study.rows}
    assert study.n_cycles == 2
    assert study.n_available_cycles == 2 and study.n_unavailable_cycles == 0
    assert rows["tight"].n_block == 2 and rows["tight"].n_no_block == 0
    assert rows["tight"].blocking_greeks == {"vega": 2, "delta": 1}
    assert rows["medium"].n_block == 1 and rows["medium"].n_no_block == 1
    # loose: one False, one None(unavailable)
    assert rows["loose"].n_no_block == 1 and rows["loose"].n_unavailable == 1


def test_available_false_cycle_marks_all_rows_unavailable():
    payload = _payload([
        {"greek_cap_counterfactual": {"available": False,
                                      "reason": "greeks_coverage_incomplete"}},
    ])
    study = build_study(payload)
    assert study.n_unavailable_cycles == 1 and study.n_available_cycles == 0
    for r in study.rows:
        assert r.n_unavailable == 1
        assert r.n_block == 0 and r.n_no_block == 0
        assert r.block_rate_of_evaluable is None  # nothing evaluable → not 0


def test_block_rate_of_evaluable_excludes_unavailable():
    payload = _payload([
        _avail([_row("tight", True, blocking=["vega"])]),
        _avail([_row("tight", False)]),
        _avail([_row("tight", None)]),  # unavailable — excluded from the rate
    ])
    study = build_study(payload)
    tight = {r.name: r for r in study.rows}["tight"]
    assert tight.n_block == 1 and tight.n_no_block == 1 and tight.n_unavailable == 1
    assert tight.block_rate_of_evaluable == 0.5  # 1 of 2 evaluable, not 1 of 3


def test_malformed_elements_are_skipped_not_crashed():
    payload = _payload([
        {"no_cf_here": 1},                      # skipped (no summary)
        {"greek_cap_counterfactual": "not-a-dict"},  # skipped
        _avail([_row("tight", True, blocking=["vega"])]),
    ])
    study = build_study(payload)
    assert study.n_cycles == 1  # only the one real summary counted


def test_render_markdown_smoke_and_dormancy_note():
    # All cycles greeks-unavailable → the double-dormancy note must appear.
    payload = _payload([
        {"greek_cap_counterfactual": {"available": False, "reason": "x"}},
    ])
    md = render_markdown(build_study(payload))
    assert "would-block frequencies" in md
    assert "double-dormancy" in md
    assert "OBSERVE-ONLY" in md


def test_study_sql_is_read_only_single_select():
    lowered = STUDY_SQL.lower()
    assert lowered.count("select") >= 1
    for verb in ("insert", "update", "delete", "drop", "alter", "truncate", "merge"):
        assert verb not in lowered, verb
    assert "job_runs" in lowered
    assert "greek_cap_counterfactual" in lowered
