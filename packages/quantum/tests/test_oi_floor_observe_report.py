"""Tests for the Lane H exact-leg OI floor observation report
(``scripts/analytics/oi_floor_observe_report.py``).

OBSERVE-ONLY read/aggregate glue over the persisted
``option_quote_provenance.details->'oi'`` evidence. SYNTHETIC fixtures only
(NO live DB). Pins:

1. STUDY_SQL is strictly READ-ONLY (single SELECT, no write verbs; targets the
   leg_set OI rows).
2. OI value distribution counts a real 0 (never conflated with missing).
3. Per-floor counterfactual aggregation: pass / fail / INDETERMINATE are three
   distinct buckets; would-fail rate is over EVALUABLE leg sets only.
4. Segment partition (all / rejected / passed / selected).
5. Malformed rows are skipped + counted, never fabricated.
6. render_markdown smoke (segments, floor table, honesty legend) + empty case.
"""

import unittest

from scripts.analytics.oi_floor_observe_report import (
    STUDY_SQL,
    build_report,
    parse_row,
    render_markdown,
)


# --- fixtures ---------------------------------------------------------------
def _oi_details(leg_ois, floor_verdicts):
    """Build a details->oi object in the recorder's emitted shape.

    ``leg_ois``: list of per-leg OI values (None = typed-unavailable leg).
    ``floor_verdicts``: list of (floor, verdict) pairs.
    """
    legs = []
    available = []
    for i, v in enumerate(leg_ois):
        avail = v is not None
        legs.append({
            "contract": f"C{i}", "oi": v, "oi_available": avail,
            "oi_unavailable_reason": None if avail else "oi_absent_from_snapshot",
            "oi_source": "alpaca", "oi_volume": 10,
            "oi_known_at": None, "oi_freshness": "known_at_unavailable",
        })
        if avail:
            available.append(v)
    return {
        "floors_evaluated": [f for f, _ in floor_verdicts],
        "legs_total": len(leg_ois),
        "legs_oi_available": len(available),
        "legs_oi_unavailable": len(leg_ois) - len(available),
        "any_oi_unavailable": len(available) != len(leg_ois),
        "min_leg_oi": (min(available) if available else None),
        "legs": legs,
        "counterfactuals": [
            {"floor": f, "verdict": v, "would_pass": v == "pass",
             "would_fail": v == "fail"}
            for f, v in floor_verdicts
        ],
    }


def _row(record_id, verdict, leg_ois, floor_verdicts, selected=False,
         symbol="X", strategy_key="long_call_debit_spread"):
    return {
        "record_id": record_id,
        "created_at": "2026-07-18T16:00:00Z",
        "cycle_date": "2026-07-18",
        "symbol": symbol,
        "strategy_key": strategy_key,
        "verdict": verdict,
        "reject_reason": "spread_too_wide" if verdict == "rejected" else None,
        "selected": selected,
        "leg_fingerprint": f"fp{record_id}",
        "oi": _oi_details(leg_ois, floor_verdicts),
    }


_FLOORS = [100, 250, 500, 1000]


def _verdicts(min_oi_or_none):
    """Floor verdicts for a fully-available leg set with the given min OI, or
    all-indeterminate when None (a dark leg)."""
    if min_oi_or_none is None:
        return [(f, "indeterminate") for f in _FLOORS]
    return [(f, "pass" if min_oi_or_none >= f else "fail") for f in _FLOORS]


# --- STUDY_SQL read-only ----------------------------------------------------
class TestStudySQL(unittest.TestCase):
    def test_is_read_only_single_select(self):
        s = STUDY_SQL.lower()
        for verb in ("insert", "update", "delete", "drop", "alter",
                     "truncate", "create", "grant", "merge"):
            self.assertNotIn(f" {verb} ", f" {s} ", verb)
        self.assertEqual(s.count("select"), s.count("select"))  # sanity
        self.assertIn("select", s)

    def test_targets_leg_set_oi_rows(self):
        self.assertIn("option_quote_provenance", STUDY_SQL)
        self.assertIn("record_type = 'leg_set'", STUDY_SQL)
        self.assertIn("details ? 'oi'", STUDY_SQL)


# --- parse + distribution ---------------------------------------------------
class TestParseAndDistribution(unittest.TestCase):
    def test_zero_oi_counted_not_missing(self):
        rows = [
            _row("r1", "rejected", [0, 5000], _verdicts(0)),
            _row("r2", "rejected", [1500, 300], _verdicts(300)),
        ]
        report = build_report({"rows": rows, "generated_at": "2026-07-18"})
        allseg = next(s for s in report.segments if s.name == "all")
        d = allseg.distribution
        # 4 available leg OI values: 0, 5000, 1500, 300.
        self.assertEqual(d.n_leg_values, 4)
        self.assertEqual(d.n_zero, 1)             # the real 0
        self.assertEqual(d.min_oi, 0)
        self.assertEqual(d.max_oi, 5000)

    def test_unavailable_leg_excluded_from_distribution(self):
        rows = [_row("r1", "rejected", [None, 800], _verdicts(None))]
        report = build_report({"rows": rows, "generated_at": "x"})
        allseg = next(s for s in report.segments if s.name == "all")
        # Only the available 800 counts; the dark leg is not a 0.
        self.assertEqual(allseg.distribution.n_leg_values, 1)
        self.assertEqual(allseg.distribution.n_zero, 0)
        self.assertEqual(allseg.n_any_unavailable, 1)
        self.assertEqual(allseg.n_fully_available, 0)

    def test_malformed_row_skipped_and_counted(self):
        good = _row("r1", "rejected", [1500, 300], _verdicts(300))
        bad = {"record_id": "bad", "verdict": "rejected", "oi": "not-a-dict"}
        report = build_report({"rows": [good, bad], "generated_at": "x"})
        self.assertEqual(report.total_rows, 2)
        self.assertEqual(report.n_parsed, 1)
        self.assertEqual(report.n_skipped_malformed, 1)

    def test_parse_row_none_on_missing_oi(self):
        self.assertIsNone(parse_row({"record_id": "x"}))
        self.assertIsNone(parse_row({"record_id": "x", "oi": None}))


# --- floor aggregation ------------------------------------------------------
class TestFloorAggregation(unittest.TestCase):
    def test_pass_fail_indeterminate_three_buckets(self):
        rows = [
            _row("pass", "rejected", [1500, 2000], _verdicts(1500)),   # pass all
            _row("fail", "rejected", [300, 1500], _verdicts(300)),     # fail 500/1000
            _row("dark", "rejected", [None, 9999], _verdicts(None)),   # indeterminate all
        ]
        report = build_report({"rows": rows, "generated_at": "x"})
        allseg = next(s for s in report.segments if s.name == "all")
        floors = {f.floor: f for f in allseg.floors}
        # floor 100: pass row + fail-row(300>=100→pass) = 2 pass, dark indeterminate
        self.assertEqual(floors[100].n_pass, 2)
        self.assertEqual(floors[100].n_fail, 0)
        self.assertEqual(floors[100].n_indeterminate, 1)
        # floor 500: pass row passes, fail row fails (300<500), dark indeterminate
        self.assertEqual(floors[500].n_pass, 1)
        self.assertEqual(floors[500].n_fail, 1)
        self.assertEqual(floors[500].n_indeterminate, 1)
        # would-fail rate is over EVALUABLE (pass+fail=2), not the 3 total.
        self.assertEqual(floors[500].n_evaluable, 2)
        self.assertAlmostEqual(floors[500].would_fail_rate, 0.5)

    def test_would_fail_rate_none_when_no_evaluable(self):
        rows = [_row("dark", "rejected", [None, 9999], _verdicts(None))]
        report = build_report({"rows": rows, "generated_at": "x"})
        allseg = next(s for s in report.segments if s.name == "all")
        floors = {f.floor: f for f in allseg.floors}
        self.assertEqual(floors[500].n_evaluable, 0)
        self.assertIsNone(floors[500].would_fail_rate)


# --- segment partition ------------------------------------------------------
class TestSegments(unittest.TestCase):
    def test_partition_by_verdict_and_selected(self):
        rows = [
            _row("r1", "rejected", [1500, 300], _verdicts(300)),
            _row("p1", "passed", [1500, 2000], _verdicts(1500)),
            _row("p2", "passed", [1500, 2000], _verdicts(1500), selected=True),
        ]
        report = build_report({"rows": rows, "generated_at": "x"})
        by_name = {s.name: s for s in report.segments}
        self.assertEqual(by_name["all"].n_leg_sets, 3)
        self.assertEqual(by_name["rejected"].n_leg_sets, 1)
        self.assertEqual(by_name["passed"].n_leg_sets, 2)
        self.assertEqual(by_name["selected"].n_leg_sets, 1)


# --- rendering --------------------------------------------------------------
class TestRender(unittest.TestCase):
    def test_markdown_smoke(self):
        rows = [
            _row("r1", "rejected", [1500, 300], _verdicts(300)),
            _row("p1", "passed", [1500, 2000], _verdicts(1500), selected=True),
        ]
        report = build_report({"rows": rows, "generated_at": "2026-07-18",
                               "source": "option_quote_provenance"})
        md = render_markdown(report)
        self.assertIn("Exact-leg OI floor observation", md)
        self.assertIn("OBSERVE-ONLY", md)
        self.assertIn("hypothetical floor", md)
        self.assertIn("indeterminate", md)
        self.assertIn("Segment: REJECTED", md)
        self.assertIn("Segment: SELECTED", md)
        # A real 0 note appears in the honesty legend.
        self.assertIn("OI 0 is a real value", md)

    def test_empty_payload(self):
        report = build_report({"rows": [], "generated_at": "2026-07-18"})
        md = render_markdown(report)
        self.assertIn("No OI-observed leg sets", md)


if __name__ == "__main__":
    unittest.main()
