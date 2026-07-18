"""Consumer #2 — scanner/unified cost basis threaded into the disposition
reconciliation artifact (observe-only).

Multi-basis cost model phase-2, Lane 3. Consumer #1 (#1258) typed
``scanner_estimate`` / ``scanner_unified_final`` UNAVAILABLE because the
scanner's inputs (``combo_width_share``, the ``drag_map``, the regime snapshot)
are gone at the disposition seam. This consumer carries the scanner's OWN
already-computed cost numbers VERBATIM to the seam:

  producer  options_scanner.build_scanner_cost_capture -> candidate_dict[
            'scanner_cost_basis_capture'] (stamped at scan time)
  consumer  cost_reconciliation_artifact reads that block and types the two
            scanner bases AVAILABLE — no re-run.

Test doctrine (CLAUDE.md v1.4 07-12): drive the PRODUCTION entrypoints, inject
failure at the ORIGIN, assert the truth at the TOP; no source-string pins.

  - ``build_scanner_cost_capture`` is production code — driven directly, fed by
    the REAL ``_determine_execution_cost`` so the captured numbers ARE the
    production formula's output (verbatim, not a re-derivation).
  - ``build_cost_reconciliation`` is driven with capture-bearing candidates
    (vertical + condor, qty>1) — the two scanner bases go AVAILABLE with typed
    units/provenance; a candidate WITHOUT a capture keeps them typed
    UNAVAILABLE (``scanner_cost_capture_absent``), never zero.
  - ``record_final`` (the production disposition write) is driven end-to-end
    against the DB contract fake; assertions read the DURABLE row's
    ``detail.cost_reconciliation``.
  - The full ``suggestions_open.run`` route confirms the capture rides a real
    end-to-end disposition through the real write AND that the decision
    projection is byte-identical with/without the capture (observe-only).
"""

import copy
import json
import unittest
from unittest.mock import patch

from packages.quantum.options_scanner import (
    _determine_execution_cost,
    build_scanner_cost_capture,
)
from packages.quantum.services.cost_reconciliation_artifact import (
    ARTIFACT_VERSION,
    SCANNER_CAPTURE_KEY,
    build_cost_reconciliation,
)
from packages.quantum.services.candidate_disposition import (
    CandidateDispositionRecorder,
)
from packages.quantum.tests.test_prerejection_fork_e19 import FakeSupabase
from packages.quantum.tests.test_cost_reconciliation_artifact import (
    _vertical,
    _condor,
    _final,
    _recorder,
)
from packages.quantum.tests.test_candidate_disposition_route import (
    _RouteBase,
    CAL_BLOB_HALF,
)
from packages.quantum.tests.test_prerejection_full_route_e19 import (
    _scanner_candidate,
)

# ── capture fixtures (production-shaped: fed by the REAL scanner formula) ───
def _vertical_capture(unified=7.25, drag_map=None):
    """SOFI 2-leg vertical capture; scanner_estimate from the REAL
    _determine_execution_cost, unified supplied verbatim."""
    cd = _determine_execution_cost(
        drag_map=drag_map or {}, symbol="SOFI",
        combo_width_share=0.10, num_legs=2, is_limit=True,
    )
    return cd, build_scanner_cost_capture(
        expected_execution_cost=cd["expected_execution_cost"],
        cost_details=cd, unified_execution_cost=unified,
        combo_width_share=0.10, num_legs=2, is_limit_order=True,
    )


def _condor_capture(unified=15.5):
    cd = _determine_execution_cost(
        drag_map={}, symbol="IWM",
        combo_width_share=0.20, num_legs=4, is_limit=True,
    )
    return cd, build_scanner_cost_capture(
        expected_execution_cost=cd["expected_execution_cost"],
        cost_details=cd, unified_execution_cost=unified,
        combo_width_share=0.20, num_legs=4, is_limit_order=True,
    )


def _vertical_with_capture(contracts=4, unified=7.25, **over):
    _cd, cap = _vertical_capture(unified=unified)
    return _vertical(contracts=contracts, **{SCANNER_CAPTURE_KEY: cap}, **over)


def _condor_with_capture(contracts=3, unified=15.5, **over):
    _cd, cap = _condor_capture(unified=unified)
    return _condor(contracts=contracts, **{SCANNER_CAPTURE_KEY: cap}, **over)


# ── the production capture builder ──────────────────────────────────────────
class TestScannerCostCaptureBuilder(unittest.TestCase):
    def test_proxy_wins_captures_verbatim_formula_output(self):
        cd, cap = _vertical_capture()
        # scanner_estimate carries EXACTLY _determine_execution_cost's numbers.
        est = cap["scanner_estimate"]
        self.assertEqual(est["expected_execution_cost"],
                         cd["expected_execution_cost"])
        self.assertEqual(est["proxy_cost_contract"], cd["proxy_cost_contract"])
        self.assertEqual(est["spread_take_frac"], cd["spread_take_frac"])
        self.assertEqual(est["source_used"], "proxy")
        self.assertEqual(est["samples_used"], 0)
        self.assertEqual(cap["scanner_unified_final"]["unified_execution_cost"],
                         7.25)
        # DETERMINISM: no wall-clock in the scan capture (candidate_dict is
        # input-deterministic by contract); source is tagged instead.
        self.assertNotIn("captured_at", cap)
        self.assertEqual(cap["source"], "scanner_scan_time_verbatim")
        self.assertEqual(cap["unit"], "per_structure_contract_usd")
        self.assertEqual(cap["num_legs"], 2)

    def test_capture_is_wall_clock_free_for_determinism(self):
        # Two identical builds are byte-identical — the scan-output determinism
        # contract (test_lifecycle_fail_closed_route healthy-path pin) holds.
        _c1, a = _vertical_capture()
        _c2, b = _vertical_capture()
        self.assertEqual(a, b)

    def test_history_wins_captures_history_source(self):
        # avg_drag 12.0 > proxy 3.8 -> history wins, samples surfaced verbatim.
        cd, cap = _vertical_capture(drag_map={"SOFI": {"avg_drag": 12.0, "n": 9}})
        est = cap["scanner_estimate"]
        self.assertEqual(est["expected_execution_cost"], 12.0)
        self.assertEqual(est["source_used"], "history")
        self.assertEqual(est["samples_used"], 9)

    def test_none_inputs_stay_none_never_zero(self):
        # H9: a missing captured value is None (typed UNAVAILABLE downstream),
        # never a fabricated 0.0.
        cap = build_scanner_cost_capture(
            expected_execution_cost=None, cost_details={},
            unified_execution_cost=None, combo_width_share=None,
            num_legs=2, is_limit_order=True,
        )
        self.assertIsNone(cap["scanner_estimate"]["expected_execution_cost"])
        self.assertIsNone(cap["scanner_estimate"]["proxy_cost_contract"])
        self.assertIsNone(cap["scanner_unified_final"]["unified_execution_cost"])

    def test_capture_is_json_serializable(self):
        _cd, cap = _condor_capture()
        self.assertEqual(json.loads(json.dumps(cap)), cap)


# ── artifact extraction (production assembler) ──────────────────────────────
class TestScannerBasisArtifactExtraction(unittest.TestCase):
    def test_vertical_qty_gt_1_both_scanner_bases_available_and_scaled(self):
        cd, _cap = _vertical_capture()
        art = build_cost_reconciliation(_vertical_with_capture(contracts=4))
        self.assertEqual(art["quantity"], 4.0)

        est = art["bases_status"]["scanner_estimate"]
        self.assertTrue(est["available"])
        self.assertEqual(est["primary"], "expected_execution_cost")
        uni = art["bases_status"]["scanner_unified_final"]
        self.assertTrue(uni["available"])
        self.assertEqual(uni["primary"], "unified_execution_cost")

        n_est = art["normalized"]["scanner_estimate"]
        # ENTRY one-side, per-structure-contract == the verbatim scanner number.
        self.assertEqual(n_est["side"], "entry")
        self.assertAlmostEqual(n_est["per_structure_contract_usd"],
                               cd["expected_execution_cost"], 6)
        # TOTAL = per_structure_contract * qty (the SAME cost at two scales).
        self.assertAlmostEqual(
            n_est["total_usd"], cd["expected_execution_cost"] * 4.0, 6)

        n_uni = art["normalized"]["scanner_unified_final"]
        self.assertAlmostEqual(n_uni["per_structure_contract_usd"], 7.25, 6)
        self.assertAlmostEqual(n_uni["total_usd"], 29.0, 6)

    def test_scanner_vs_stage_delta_and_double_count_flag_live(self):
        art = build_cost_reconciliation(_vertical_with_capture(contracts=4))
        # The commission double-count guard flag fires when both scanner and
        # ranker bases are present (scanner one-side vs ranker round-trip).
        self.assertIn(
            "scanner_commission_one_side_embedded_vs_ranker_round_trip",
            art["flags"])
        # The scanner-modeled vs executable-cross delta is now AVAILABLE.
        d = [x for x in art["deltas"]
             if x["name"] == "scanner_modeled_vs_stage_executable_per_contract"
             ][0]
        self.assertTrue(d["available"])
        # per-structure-contract executable cross ($20) > scanner unified ($7.25)
        self.assertAlmostEqual(d["amount_usd"], 20.0 - 7.25, 5)

    def test_condor_four_leg_qty_gt_1_scanner_bases_available(self):
        cd, _cap = _condor_capture()
        art = build_cost_reconciliation(_condor_with_capture(contracts=3))
        self.assertEqual(art["quantity"], 3.0)
        self.assertTrue(art["bases_status"]["scanner_estimate"]["available"])
        self.assertTrue(
            art["bases_status"]["scanner_unified_final"]["available"])
        n_est = art["normalized"]["scanner_estimate"]
        self.assertAlmostEqual(n_est["per_structure_contract_usd"],
                               cd["expected_execution_cost"], 6)
        self.assertAlmostEqual(
            n_est["total_usd"], cd["expected_execution_cost"] * 3.0, 6)

    def test_absent_capture_types_scanner_unavailable_never_zero(self):
        # A pre-consumer-#2 candidate (no capture) keeps BOTH scanner bases
        # typed UNAVAILABLE with the dedicated reason — regression guard for
        # consumer #1's contract.
        art = build_cost_reconciliation(_vertical(contracts=2))
        for name in ("scanner_estimate", "scanner_unified_final"):
            st = art["bases_status"][name]
            self.assertFalse(st["available"])
            self.assertEqual(st["reason"], "scanner_cost_capture_absent")
            self.assertIsNone(st["primary"])
        # Not present in normalized at all (nothing to normalize), never a 0.
        self.assertNotIn("scanner_estimate", art["normalized"])

    def test_capture_present_but_unified_missing_types_unavailable(self):
        # scanner_estimate available, scanner_unified_final missing its number
        # -> typed UNAVAILABLE (never zero, never dropped).
        cand = _vertical_with_capture(contracts=2)
        cand[SCANNER_CAPTURE_KEY]["scanner_unified_final"][
            "unified_execution_cost"] = None
        art = build_cost_reconciliation(cand)
        self.assertTrue(art["bases_status"]["scanner_estimate"]["available"])
        uni = art["bases_status"]["scanner_unified_final"]
        self.assertFalse(uni["available"])
        self.assertEqual(
            uni["reason"], "scanner_unified_capture_missing:unified_execution_cost")

    def test_provenance_and_shared_components_documented(self):
        art = build_cost_reconciliation(_vertical_with_capture(contracts=4))
        comp = art["normalized"]["scanner_estimate"]
        self.assertEqual(comp["basis"], "estimated")
        # The containment / double-count guidance is carried for readers.
        sc = art["shared_components"]
        self.assertIn("scanner_estimate_vs_unified_final_containment", sc)
        self.assertIn("scanner_one_side_vs_round_trip_bases", sc)

    def test_builder_never_mutates_candidate(self):
        cand = _condor_with_capture(contracts=5)
        before = copy.deepcopy(cand)
        build_cost_reconciliation(cand)
        self.assertEqual(cand, before)

    def test_artifact_json_serializable_with_scanner_bases(self):
        art = build_cost_reconciliation(_condor_with_capture(contracts=3))
        self.assertEqual(json.loads(json.dumps(art))["bases_status"],
                         art["bases_status"])
        self.assertTrue(art["observe_only"])
        self.assertFalse(art["decisional"])
        self.assertEqual(art["artifact_version"], ARTIFACT_VERSION)
        # The observe-only artifact stamps its own disposition-seam assembly
        # timestamp (the honest "when" — the scan output stays wall-clock-free).
        self.assertIsInstance(art["assembled_at"], str)


# ── writer seam (production entrypoint: record_final) ───────────────────────
class TestScannerBasisWriterSeam(unittest.TestCase):
    def test_vertical_final_carries_available_scanner_bases(self):
        client = FakeSupabase()
        rec = _recorder(client)
        cd, _cap = _vertical_capture()
        cand = _vertical_with_capture(contracts=4)
        rec.record_selected([cand])
        rec.record_final(cand, "rank_blocked",
                         detail={"reason": "edge_below_minimum"})
        art = _final(client)["detail"]["cost_reconciliation"]
        self.assertTrue(art["bases_status"]["scanner_estimate"]["available"])
        self.assertTrue(
            art["bases_status"]["scanner_unified_final"]["available"])
        self.assertAlmostEqual(
            art["normalized"]["scanner_estimate"]["per_structure_contract_usd"],
            cd["expected_execution_cost"], 6)
        self.assertAlmostEqual(
            art["normalized"]["scanner_unified_final"][
                "per_structure_contract_usd"], 7.25, 6)

    def test_condor_final_carries_available_scanner_bases(self):
        client = FakeSupabase()
        rec = _recorder(client)
        cd, _cap = _condor_capture()
        cand = _condor_with_capture(contracts=3)
        rec.record_selected([cand])
        rec.record_final(cand, "allocator_dropped",
                         detail={"reason": "not_in_allocator_output"})
        art = _final(client)["detail"]["cost_reconciliation"]
        self.assertTrue(art["bases_status"]["scanner_estimate"]["available"])
        self.assertAlmostEqual(
            art["normalized"]["scanner_estimate"]["total_usd"],
            cd["expected_execution_cost"] * 3.0, 6)


# ── full production route (suggestions_open.run) ────────────────────────────
class TestScannerBasisFullRoute(_RouteBase):
    def _cand_with_capture(self, **over):
        c = _scanner_candidate()
        _cd, cap = _vertical_capture()
        c[SCANNER_CAPTURE_KEY] = cap
        c.update(over)
        return c

    def test_route_rank_blocked_final_carries_scanner_bases(self):
        client = FakeSupabase()
        self._seed(client)
        cd, _cap = _vertical_capture()
        result = self._drive(client, [self._cand_with_capture()],
                             cal_blob=CAL_BLOB_HALF)
        self.assertTrue(result["ok"], result.get("notes"))

        finals = self._finals(client)
        self.assertEqual(len(finals), 1)
        final = finals[0]
        self.assertEqual(final["disposition"], "rank_blocked")
        art = final["detail"]["cost_reconciliation"]
        # The scanner's verbatim scan-time numbers rode the whole cycle to the
        # real disposition write.
        self.assertTrue(art["bases_status"]["scanner_estimate"]["available"])
        self.assertTrue(
            art["bases_status"]["scanner_unified_final"]["available"])
        self.assertAlmostEqual(
            art["normalized"]["scanner_estimate"]["per_structure_contract_usd"],
            cd["expected_execution_cost"], 6)
        self.assertAlmostEqual(
            art["normalized"]["scanner_unified_final"][
                "per_structure_contract_usd"], 7.25, 6)
        # Still observe-only.
        self.assertTrue(art["observe_only"])
        self.assertFalse(art["decisional"])

    def test_route_qty_gt_1_allocator_drop_carries_scaled_scanner_bases(self):
        client = FakeSupabase()
        self._seed(client)
        cd, _cap = _vertical_capture()
        # sizing_metadata rides the candidate so the seam resolves qty>1;
        # allocator forced empty -> allocator_dropped final (AAPL/IWM seam).
        cand = self._cand_with_capture(sizing_metadata={"contracts": 4})
        result = self._drive(
            client, [cand], cal_blob=None,
            extra_patches=(
                patch("packages.quantum.services.portfolio_allocator."
                      "PortfolioAllocator.allocate", lambda self, **kw: []),
            ),
        )
        self.assertTrue(result["ok"], result.get("notes"))
        finals = self._finals(client)
        self.assertEqual(len(finals), 1)
        art = finals[0]["detail"]["cost_reconciliation"]
        self.assertEqual(finals[0]["disposition"], "allocator_dropped")
        self.assertEqual(art["quantity"], 4.0)
        self.assertAlmostEqual(
            art["normalized"]["scanner_estimate"]["total_usd"],
            cd["expected_execution_cost"] * 4.0, 6)

    def test_capture_presence_does_not_change_the_decision(self):
        """Observe-only proof for CONSUMER #2 specifically: the persisted
        trade_suggestions projection is byte-identical whether or not the
        candidate carries the scanner cost capture."""
        def _projection(client):
            rows = client.tables.get("trade_suggestions", [])
            return sorted(
                ((r.get("ticker"), r.get("strategy"), r.get("status"),
                  r.get("blocked_reason"), r.get("ev"), r.get("ev_raw"),
                  r.get("risk_adjusted_ev"), r.get("legs_fingerprint"),
                  str(r.get("order_json", {}).get("legs")),
                  r.get("order_json", {}).get("contracts"))
                 for r in rows),
                key=lambda t: tuple(str(x) for x in t),
            )

        client_with = FakeSupabase()
        self._seed(client_with)
        res_with = self._drive(client_with, [self._cand_with_capture()],
                               cal_blob=CAL_BLOB_HALF)
        self.assertTrue(res_with["ok"], res_with.get("notes"))

        client_without = FakeSupabase()
        self._seed(client_without)
        res_without = self._drive(client_without, [_scanner_candidate()],
                                  cal_blob=CAL_BLOB_HALF)
        self.assertTrue(res_without["ok"], res_without.get("notes"))

        self.assertEqual(_projection(client_with), _projection(client_without))
        # And the scanner bases only exist on the with-capture run.
        art_with = self._finals(client_with)[0]["detail"]["cost_reconciliation"]
        self.assertTrue(
            art_with["bases_status"]["scanner_estimate"]["available"])
        art_without = self._finals(client_without)[0]["detail"][
            "cost_reconciliation"]
        self.assertFalse(
            art_without["bases_status"]["scanner_estimate"]["available"])


if __name__ == "__main__":
    unittest.main()
