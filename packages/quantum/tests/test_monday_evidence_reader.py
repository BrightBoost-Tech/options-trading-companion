"""Tests for the Monday natural-evidence CONSOLIDATED reader
(``scripts/analytics/monday_evidence_reader.py``).

OBSERVE-ONLY read/aggregate glue over twelve natural-evidence sinks. SYNTHETIC
fixtures only (NO live DB). Pins:

1. STUDY_SQL is strictly READ-ONLY (single SELECT, no write verbs), targets every
   source table/path, carries all twelve section keys + to_regclass guards, and
   --emit-sql substitutes / validates the cycle-date.
2. The core typing contract: HONEST-EMPTY vs FAILED-FETCH vs NOT-FETCHED vs OK
   are FOUR distinct per-section states — a failed fetch is never scored as empty.
3. Every section builder: present / empty shapes, cohort separation, and the two
   named measurement limits (greek-cap headroom unavailable-by-construction;
   provenance writer counters log-only).
4. Determinism: identical rows -> byte-identical JSON + markdown.
5. render_markdown smoke incl. the clock-mismatch caveat.
"""

import json
import unittest

from scripts.analytics.monday_evidence_reader import (
    STATUS_EMPTY,
    STATUS_FAILED,
    STATUS_NOT_FETCHED,
    STATUS_OK,
    STUDY_SQL,
    build_report,
    render_markdown,
    _emit_sql,
    cohort_class,
)


# --- fixture helpers --------------------------------------------------------
def _ok(**kw):
    d = {"fetch_status": "ok"}
    d.update(kw)
    return d


def _payload(cycle_date="2026-07-20", **sections):
    return {
        "schema_version": 1,
        "model_version": "monday-evidence-reader/1.0",
        "generated_at": "2026-07-20",
        "cycle_date": cycle_date,
        "sections": sections,
    }


def _section(report, name):
    return next(s for s in report.sections if s.name == name)


# --- 1. STUDY_SQL -----------------------------------------------------------
class TestStudySQL(unittest.TestCase):
    def test_read_only_single_select(self):
        s = STUDY_SQL.lower()
        for verb in ("insert", "update", "delete", "drop", "alter",
                     "truncate", "create", "grant", "merge", "into"):
            self.assertNotIn(f" {verb} ", f" {s} ", verb)
        # exactly one top-level statement (one trailing semicolon).
        self.assertEqual(STUDY_SQL.rstrip().count(";"), 1)
        self.assertIn("select", s)

    def test_targets_every_source(self):
        for token in (
            "decision_runs", "candidate_terminal_dispositions",
            "option_quote_provenance", "paper_orders", "trade_suggestions",
            "policy_registrations", "job_runs",
            "tcm_v2_proposal", "greek_cap_counterfactual", "tier_taper",
            "single_leg_experiment_enabled", "entry_underlying_spot",
            "h7_dropped", "cycle_results", "intraday_risk_monitor",
            "suggestions_open",
        ):
            self.assertIn(token, STUDY_SQL, token)

    def test_has_all_twelve_section_keys(self):
        for key in (
            "'cycle_identity'", "'h7_finals'", "'terminal_dispositions'",
            "'quote_provenance'", "'oi_floor'", "'scan_capture'",
            "'tier_taper'", "'greek_cap'", "'tcm_stamps'", "'single_leg'",
            "'model_review'", "'writer_counters'",
        ):
            self.assertIn(key, STUDY_SQL, key)

    def test_table_absent_guards(self):
        # Optional tables are guarded so a missing table yields a typed FAILED
        # section, not a whole-query error.
        self.assertIn("to_regclass('public.candidate_terminal_dispositions')", STUDY_SQL)
        self.assertIn("to_regclass('public.option_quote_provenance')", STUDY_SQL)
        self.assertIn("to_regclass('public.policy_registrations')", STUDY_SQL)

    def test_emit_sql_substitutes_cycle_date(self):
        sql = _emit_sql("2026-07-20")
        self.assertIn("DATE '2026-07-20'", sql)
        self.assertNotIn("__CYCLE_DATE__", sql)

    def test_emit_sql_placeholder_when_no_date(self):
        sql = _emit_sql(None)
        self.assertIn("__CYCLE_DATE__", sql)
        self.assertIn("Replace", sql)

    def test_emit_sql_rejects_bad_date(self):
        with self.assertRaises(ValueError):
            _emit_sql("2026/07/20")
        with self.assertRaises(ValueError):
            _emit_sql("not-a-date")


# --- 2. section typing: EMPTY vs FAILED vs NOT_FETCHED vs OK -----------------
class TestSectionTyping(unittest.TestCase):
    def test_failed_fetch_not_scored_as_empty(self):
        report = build_report(_payload(
            h7_finals={"fetch_status": "failed", "reason": "table_absent"}))
        sec = _section(report, "h7_finals")
        self.assertEqual(sec.status, STATUS_FAILED)
        self.assertEqual(sec.reason, "table_absent")
        # A failed section carries no fabricated summary.
        self.assertEqual(sec.summary, {})

    def test_absent_section_is_not_fetched(self):
        # payload with NO sections at all -> every section NOT_FETCHED.
        report = build_report(_payload())
        for sec in report.sections:
            self.assertEqual(sec.status, STATUS_NOT_FETCHED, sec.name)
            self.assertEqual(sec.reason, "section_absent_from_payload")

    def test_empty_section_is_honest_empty(self):
        report = build_report(_payload(
            terminal_dispositions=_ok(n_total=0, n_final=0,
                                      n_cost_reconciliation=0, rows=[])))
        self.assertEqual(_section(report, "terminal_dispositions").status, STATUS_EMPTY)

    def test_ok_section(self):
        report = build_report(_payload(
            terminal_dispositions=_ok(
                n_total=3, n_final=2, n_cost_reconciliation=1,
                rows=[{"cohort": "aggressive", "disposition": "filled", "n": 3, "n_final": 2}])))
        self.assertEqual(_section(report, "terminal_dispositions").status, STATUS_OK)

    def test_malformed_section_is_failed(self):
        report = build_report(_payload(h7_finals="not-a-dict"))
        self.assertEqual(_section(report, "h7_finals").status, STATUS_FAILED)

    def test_status_summary_counts(self):
        report = build_report(_payload(
            terminal_dispositions=_ok(n_total=1, n_final=1, rows=[
                {"cohort": "aggressive", "disposition": "filled", "n": 1}]),
            h7_finals={"fetch_status": "failed", "reason": "x"},
            # the other 10 are absent -> NOT_FETCHED
        ))
        d = report.as_dict()["status_summary"]
        self.assertEqual(d[STATUS_OK], 1)
        self.assertEqual(d[STATUS_FAILED], 1)
        self.assertEqual(d[STATUS_NOT_FETCHED], 10)


# --- 3a. cycle_identity -----------------------------------------------------
class TestCycleIdentity(unittest.TestCase):
    def test_multiple_git_shas_flagged(self):
        report = build_report(_payload(cycle_identity=_ok(
            decision_runs=[
                {"git_sha": "a" * 40, "status": "ok", "as_of_ts": "2026-07-20T14:00:00Z",
                 "tape_integrity": "complete"},
                {"git_sha": "b" * 40, "status": "ok", "as_of_ts": "2026-07-20T15:00:00Z",
                 "tape_integrity": "complete"},
            ],
            n_suggestions=4, suggestion_code_shas=["abc123abc123"],
            disposition_code_shas=[])))
        sec = _section(report, "cycle_identity")
        self.assertEqual(sec.status, STATUS_OK)
        self.assertEqual(len(sec.summary["git_shas"]), 2)
        md = render_markdown(report)
        self.assertIn("MULTIPLE SHAs", md)

    def test_empty_when_no_runs_no_suggestions(self):
        report = build_report(_payload(cycle_identity=_ok(
            decision_runs=[], n_suggestions=0,
            suggestion_code_shas=[], disposition_code_shas=[])))
        self.assertEqual(_section(report, "cycle_identity").status, STATUS_EMPTY)


# --- 3b. h7_finals ----------------------------------------------------------
class TestH7Finals(unittest.TestCase):
    def test_distribution_and_cohort_separation(self):
        report = build_report(_payload(h7_finals=_ok(rows=[
            {"cohort": "aggressive", "h7_subreason": "roundtrip_bp",
             "sizing_outcome": None, "reason": "h7_prefilter", "n": 2},
            {"cohort": "neutral", "h7_subreason": "sizing_zero",
             "sizing_outcome": None, "reason": "round_trip_bp_insufficient", "n": 5},
            {"cohort": "aggressive", "h7_subreason": "quality_gate",
             "sizing_outcome": "marketdata_quality_gate", "reason": "quality_gate_e4_fatal", "n": 1},
        ], taxonomy_violations=0)))
        sec = _section(report, "h7_finals")
        self.assertEqual(sec.status, STATUS_OK)
        self.assertEqual(sec.summary["n_h7_finals"], 8)
        # live (aggressive) and shadow (neutral) are SEPARATE — shadow's 5 never
        # pool into live.
        self.assertEqual(sec.summary["by_cohort_subreason"]["live"], {"roundtrip_bp": 2, "quality_gate": 1})
        self.assertEqual(sec.summary["by_cohort_subreason"]["shadow"], {"sizing_zero": 5})
        self.assertEqual(sec.summary["by_sizing_outcome"], {"marketdata_quality_gate": 1})

    def test_taxonomy_violation_surfaced(self):
        report = build_report(_payload(h7_finals=_ok(rows=[
            {"cohort": "aggressive", "h7_subreason": "unspecified",
             "sizing_outcome": None, "n": 1}], taxonomy_violations=1)))
        self.assertEqual(_section(report, "h7_finals").summary["taxonomy_violations"], 1)
        self.assertIn("taxonomy violations", render_markdown(report))


# --- 3c. quote_provenance ---------------------------------------------------
class TestQuoteProvenance(unittest.TestCase):
    def test_source_429_freshness(self):
        report = build_report(_payload(quote_provenance=_ok(
            n_rows=10, by_record_type={"fetch_event": 6, "leg_set": 4},
            by_source={"alpaca": 7, "polygon": 3}, by_verdict={"passed": 4, "rejected": 6},
            by_fallback_reason={"NULL": 7, "primary_dark": 3},
            n_rows_with_429=2,
            freshness={"n_with_stale_age": 8, "n_stale_gt_60s": 1, "median_stale_ms": 1234.5})))
        sec = _section(report, "quote_provenance")
        self.assertEqual(sec.status, STATUS_OK)
        self.assertEqual(sec.summary["n_rows_with_429"], 2)
        self.assertEqual(sec.summary["by_source"], {"alpaca": 7, "polygon": 3})
        self.assertEqual(sec.summary["freshness"]["median_stale_ms"], 1234.5)


# --- 3d. oi_floor -----------------------------------------------------------
def _oi_leg_set(leg_ois, floor_verdicts, verdict="rejected", selected=False):
    legs = [{"oi": v, "oi_available": v is not None} for v in leg_ois]
    avail = [v for v in leg_ois if v is not None]
    return {
        "verdict": verdict, "selected": selected,
        "oi": {
            "legs_total": len(leg_ois), "legs_oi_available": len(avail),
            "any_oi_unavailable": len(avail) != len(leg_ois),
            "min_leg_oi": (min(avail) if avail else None), "legs": legs,
            "counterfactuals": [{"floor": f, "verdict": v} for f, v in floor_verdicts],
        },
    }


class TestOIFloor(unittest.TestCase):
    def test_pass_fail_indeterminate_and_zero_counted(self):
        report = build_report(_payload(oi_floor=_ok(rows=[
            _oi_leg_set([0, 5000], [(100, "fail"), (500, "fail")]),   # real 0 fails
            _oi_leg_set([1500, 2000], [(100, "pass"), (500, "pass")]),
            _oi_leg_set([None, 9999], [(100, "indeterminate"), (500, "indeterminate")]),
        ])))
        sec = _section(report, "oi_floor")
        self.assertEqual(sec.status, STATUS_OK)
        d = sec.summary["distribution"]
        # available OI values: 0, 5000, 1500, 2000, 9999 -> 5, one real zero.
        self.assertEqual(d["n_leg_values"], 5)
        self.assertEqual(d["n_zero_oi_legs"], 1)
        f500 = sec.summary["floors"]["500"]
        self.assertEqual((f500["pass"], f500["fail"], f500["indeterminate"]), (1, 1, 1))
        # would-fail rate is over EVALUABLE (pass+fail=2), not the 3 total.
        self.assertEqual(f500["n_evaluable"], 2)
        self.assertAlmostEqual(f500["would_fail_rate_of_evaluable"], 0.5)

    def test_empty_when_no_leg_sets(self):
        report = build_report(_payload(oi_floor=_ok(rows=[])))
        self.assertEqual(_section(report, "oi_floor").status, STATUS_EMPTY)


# --- 3e. scan_capture -------------------------------------------------------
class TestScanCapture(unittest.TestCase):
    def test_capture_rates(self):
        report = build_report(_payload(scan_capture=_ok(rows=[
            {"cohort": "aggressive", "spot_status": "populated_at_stage",
             "n_legs": 2, "n_iv_populated": 2, "n_delta_populated": 1},
            {"cohort": "aggressive", "spot_status": "unavailable_at_stage",
             "n_legs": 2, "n_iv_populated": 0, "n_delta_populated": 0},
        ])))
        sec = _section(report, "scan_capture")
        self.assertEqual(sec.status, STATUS_OK)
        self.assertEqual(sec.summary["n_open_orders"], 2)
        self.assertAlmostEqual(sec.summary["spot_capture_rate"], 0.5)   # 1 of 2 orders
        self.assertAlmostEqual(sec.summary["iv_capture_rate"], 0.5)     # 2 of 4 legs
        self.assertAlmostEqual(sec.summary["delta_capture_rate"], 0.25)  # 1 of 4 legs


# --- 3f. tier_taper ---------------------------------------------------------
class TestTierTaper(unittest.TestCase):
    def test_verdict_and_current_proposed(self):
        report = build_report(_payload(tier_taper=_ok(rows=[
            {"verdict": "would_tighten", "effective_tier_state": "micro",
             "raw_tier": "micro", "current": {"tier": "small"},
             "proposed": {"tier": "micro"},
             "difference": {"envelope_pct": -0.1, "per_trade_ceiling_pct": -0.05}},
        ])))
        sec = _section(report, "tier_taper")
        self.assertEqual(sec.status, STATUS_OK)
        self.assertEqual(sec.summary["by_verdict"], {"would_tighten": 1})
        o = sec.summary["observations"][0]
        self.assertEqual(o["current_tier"], "small")
        self.assertEqual(o["proposed_tier"], "micro")
        self.assertEqual(o["difference_envelope_pct"], -0.1)

    def test_engine_versions_never_pooled(self):
        # v1-era and v2-era samples MUST be partitioned by engine_version — a
        # reader must never pool [900,1100]-era with [800,1000]-era evidence.
        report = build_report(_payload(tier_taper=_ok(rows=[
            {"engine_version": "tier_taper.v1", "verdict": "would_loosen",
             "current": {"tier": "small"}, "proposed": {"tier": "small"},
             "difference": {"envelope_pct": 0.01}},
            {"engine_version": "tier_taper.v2", "verdict": "would_tighten",
             "current": {"tier": "micro"}, "proposed": {"tier": "micro"},
             "difference": {"envelope_pct": -0.02}},
            {"engine_version": "tier_taper.v2", "verdict": "identical",
             "current": {"tier": "micro"}, "proposed": {"tier": "micro"},
             "difference": {"envelope_pct": 0.0}},
        ])))
        sec = _section(report, "tier_taper")
        bev = sec.summary["by_engine_version"]
        self.assertEqual(sec.summary["engine_versions"],
                         ["tier_taper.v1", "tier_taper.v2"])
        # v1 bucket holds ONLY the v1 sample; v2 bucket ONLY the v2 samples.
        self.assertEqual(bev["tier_taper.v1"],
                         {"n_observations": 1, "by_verdict": {"would_loosen": 1}})
        self.assertEqual(bev["tier_taper.v2"]["n_observations"], 2)
        self.assertEqual(bev["tier_taper.v2"]["by_verdict"],
                         {"identical": 1, "would_tighten": 1})
        # would_loosen (a v1-only verdict) NEVER leaks into the v2 bucket.
        self.assertNotIn("would_loosen", bev["tier_taper.v2"]["by_verdict"])
        # Every observation is version-tagged.
        self.assertTrue(all(o.get("engine_version") in
                            ("tier_taper.v1", "tier_taper.v2")
                            for o in sec.summary["observations"]))
        # The rendered report flags the multi-version split explicitly.
        self.assertIn("NEVER pooled", render_markdown(report))


# --- 3g. greek_cap ----------------------------------------------------------
class TestGreekCap(unittest.TestCase):
    def test_would_block_tally_and_headroom_unavailable(self):
        report = build_report(_payload(greek_cap=_ok(rows=[
            {"available": True, "greeks_coverage_complete": True,
             "rows": [{"name": "tight", "would_block": True, "blocking_greeks": ["vega"]},
                      {"name": "loose", "would_block": False}]},
            {"available": False, "reason": "greeks_coverage_incomplete"},
        ])))
        sec = _section(report, "greek_cap")
        self.assertEqual(sec.status, STATUS_OK)
        self.assertEqual(sec.summary["n_cycles"], 2)
        self.assertEqual(sec.summary["n_available_cycles"], 1)
        self.assertEqual(sec.summary["n_unavailable_cycles"], 1)
        self.assertEqual(sec.summary["by_reference_row"]["tight"]["would_block"], 1)
        # HEADROOM must be typed unavailable-by-construction, never fabricated.
        self.assertEqual(sec.summary["headroom_status"], "unavailable_by_construction")
        self.assertIn("UNAVAILABLE-BY-CONSTRUCTION", render_markdown(report))


# --- 3h. tcm_stamps ---------------------------------------------------------
class TestTcmStamps(unittest.TestCase):
    def test_current_vs_v2_counts_cohort_separate(self):
        report = build_report(_payload(tcm_stamps=_ok(
            rows=[
                {"cohort": "aggressive", "n_orders": 4, "n_tcm_current": 4, "n_tcm_v2": 0},
                {"cohort": "neutral", "n_orders": 6, "n_tcm_current": 6, "n_tcm_v2": 2},
            ],
            v2_by_model_version={"tcm_v2_proposal/0.1.0": 2},
            v2_by_routing={"shadow": 2})))
        sec = _section(report, "tcm_stamps")
        self.assertEqual(sec.status, STATUS_OK)
        self.assertEqual(sec.summary["n_orders"], 10)
        self.assertEqual(sec.summary["n_tcm_current"], 10)
        self.assertEqual(sec.summary["n_tcm_v2"], 2)
        self.assertEqual(sec.summary["by_cohort"]["live"]["n_tcm_v2"], 0)
        self.assertEqual(sec.summary["by_cohort"]["shadow"]["n_tcm_v2"], 2)


# --- 3i. single_leg ---------------------------------------------------------
class TestSingleLeg(unittest.TestCase):
    def test_opt_in_zero_with_populated_registry_is_ok_not_empty(self):
        report = build_report(_payload(single_leg=_ok(
            n_registrations=50, n_opt_in=0, by_approval_status={"approved": 50})))
        sec = _section(report, "single_leg")
        # Fleet-state: 0 opt-ins with a populated registry is the EXPECTED dark
        # status (OK), not EMPTY.
        self.assertEqual(sec.status, STATUS_OK)
        self.assertEqual(sec.summary["n_opt_in"], 0)
        self.assertEqual(sec.summary["opt_in_key"], "single_leg_experiment_enabled")

    def test_empty_only_when_registry_empty(self):
        report = build_report(_payload(single_leg=_ok(
            n_registrations=0, n_opt_in=0, by_approval_status={})))
        self.assertEqual(_section(report, "single_leg").status, STATUS_EMPTY)


# --- 3j. model_review -------------------------------------------------------
class TestModelReview(unittest.TestCase):
    def test_scorable_count_and_trigger_state(self):
        report = build_report(_payload(model_review=_ok(rows=[
            {"job_name": "paper_learning_ingest", "started_at": "2026-07-20T21:00:00Z",
             "review": {"scorable_count": 3, "status": "no_scorable_closes",
                        "boundary_crossed": False}},
            {"job_name": "model_review_event", "started_at": "2026-07-20T21:05:00Z",
             "review": {"scorable_count": 8, "status": "queued", "boundary_crossed": True,
                        "ok": True}},
        ])))
        sec = _section(report, "model_review")
        self.assertEqual(sec.status, STATUS_OK)
        self.assertEqual(sec.summary["max_scorable_count"], 8)
        self.assertEqual(sec.summary["latest_status"], "queued")


# --- 3k. writer_counters ----------------------------------------------------
class TestWriterCounters(unittest.TestCase):
    def test_all_zero_is_empty(self):
        report = build_report(_payload(writer_counters=_ok(
            disposition={"finals_recorded": 0, "n_runs": 0, "attempts_recorded": 0,
                         "write_failures": 0, "table_missing_noops": 0,
                         "writer_taxonomy_violation": 0},
            provenance={"fetch_status": "ok", "rows_persisted": 0, "by_record_type": {}},
            quality_gate={"modes": [], "n_quality_gate_dispositions": 0})))
        self.assertEqual(_section(report, "writer_counters").status, STATUS_EMPTY)

    def test_counters_and_provenance_failed_subfetch(self):
        report = build_report(_payload(writer_counters=_ok(
            disposition={"finals_recorded": 5, "n_runs": 2, "attempts_recorded": 20,
                         "write_failures": 1, "table_missing_noops": 0,
                         "writer_taxonomy_violation": 0},
            provenance={"fetch_status": "failed", "reason": "table_absent"},
            quality_gate={"modes": ["soft"], "n_quality_gate_dispositions": 3})))
        sec = _section(report, "writer_counters")
        self.assertEqual(sec.status, STATUS_OK)
        self.assertEqual(sec.summary["disposition"]["finals_recorded"], 5)
        self.assertEqual(sec.summary["provenance"]["fetch_status"], "failed")
        md = render_markdown(report)
        # provenance sub-fetch FAILED -> its own failed line, not the log-only note.
        self.assertIn("provenance writer: FAILED FETCH", md)

    def test_provenance_ok_notes_log_only_limit(self):
        report = build_report(_payload(writer_counters=_ok(
            disposition={"finals_recorded": 0, "n_runs": 0, "attempts_recorded": 0,
                         "write_failures": 0, "table_missing_noops": 0,
                         "writer_taxonomy_violation": 0},
            provenance={"fetch_status": "ok", "rows_persisted": 12,
                        "by_record_type": {"fetch_event": 8, "leg_set": 4}},
            quality_gate={"modes": ["soft"], "n_quality_gate_dispositions": 0})))
        sec = _section(report, "writer_counters")
        self.assertEqual(sec.status, STATUS_OK)  # provenance rows make it non-empty
        self.assertEqual(sec.summary["provenance"]["rows_persisted"], 12)
        self.assertIn("LOG-ONLY", render_markdown(report))


# --- 4. determinism ---------------------------------------------------------
class TestDeterminism(unittest.TestCase):
    def _mixed(self):
        return _payload(
            cycle_identity=_ok(decision_runs=[
                {"git_sha": "a" * 40, "status": "ok", "as_of_ts": "2026-07-20T14:00:00Z",
                 "tape_integrity": "complete"}], n_suggestions=2,
                suggestion_code_shas=["s1"], disposition_code_shas=[]),
            h7_finals={"fetch_status": "failed", "reason": "table_absent"},
            tcm_stamps=_ok(rows=[
                {"cohort": "aggressive", "n_orders": 4, "n_tcm_current": 4, "n_tcm_v2": 0}],
                v2_by_model_version={}, v2_by_routing={}),
            single_leg=_ok(n_registrations=50, n_opt_in=0, by_approval_status={"approved": 50}),
        )

    def test_same_rows_byte_identical(self):
        r1 = build_report(self._mixed())
        r2 = build_report(self._mixed())
        self.assertEqual(json.dumps(r1.as_dict(), sort_keys=True),
                         json.dumps(r2.as_dict(), sort_keys=True))
        self.assertEqual(render_markdown(r1), render_markdown(r2))


# --- 5. render smoke + clock mismatch ---------------------------------------
class TestRenderAndClock(unittest.TestCase):
    def test_render_smoke_mixed_states(self):
        report = build_report(_payload(
            terminal_dispositions=_ok(n_total=0, n_final=0, rows=[]),      # empty
            h7_finals={"fetch_status": "failed", "reason": "table_absent"},  # failed
            single_leg=_ok(n_registrations=50, n_opt_in=0,
                           by_approval_status={"approved": 50})))           # ok
        md = render_markdown(report)
        self.assertIn("Monday natural-evidence consolidated reader", md)
        self.assertIn("HONEST-EMPTY", md)
        self.assertIn("FAILED-FETCH", md)
        self.assertIn("NOT-FETCHED", md)  # the 9 absent sections

    def test_clock_mismatch_caveat(self):
        report = build_report(_payload(cycle_date="2026-07-20"),
                              cycle_date_requested="2026-07-19")
        self.assertTrue(report.cycle_date_mismatch)
        self.assertIn("CLOCK MISMATCH", render_markdown(report))

    def test_no_mismatch_when_aligned(self):
        report = build_report(_payload(cycle_date="2026-07-20"),
                              cycle_date_requested="2026-07-20")
        self.assertFalse(report.cycle_date_mismatch)


# --- cohort helper ----------------------------------------------------------
class TestCohortClass(unittest.TestCase):
    def test_mapping(self):
        self.assertEqual(cohort_class("aggressive"), "live")
        self.assertEqual(cohort_class("neutral"), "shadow")
        self.assertEqual(cohort_class("conservative"), "shadow")
        self.assertEqual(cohort_class(None), "unattributed")
        self.assertEqual(cohort_class("weird"), "unattributed")


if __name__ == "__main__":
    unittest.main()
