"""Lane 2C — observe-only cost-reconciliation artifact on candidate dispositions.

Multi-basis cost model phase-2, CONSUMER #1. The artifact is assembled at the
DISPOSITION-WRITE SEAM (``CandidateDispositionRecorder.record_final``) and
attached inside the EXISTING ``candidate_terminal_dispositions.detail`` jsonb as
``detail.cost_reconciliation``.

Test doctrine (CLAUDE.md, v1.4 07-12): drive the PRODUCTION entrypoint, inject
failure at its ORIGIN, assert the truth at the TOP; no source-string pins.

  - The builder ``build_cost_reconciliation`` is production code — driven
    directly to pin the multi-basis contract (vertical + condor, qty>1,
    missing-basis, no-mutation, JSON-serializability).
  - The writer ``record_final`` is the production seam that attaches the
    artifact — driven end-to-end against the hardened DB contract fake; the
    assertions read the DURABLE row's ``detail.cost_reconciliation``.
  - Artifact-failure-does-not-break-write injects the failure at the DEEPEST
    callee (``cost_basis.reconcile_cost_bases`` raises; the builder raises) and
    asserts the disposition row still persists with counters intact.
  - The full ``suggestions_open.run`` route confirms the artifact rides a real
    end-to-end disposition AND that the decision projection is unchanged
    (observe-only).
"""

import copy
import json
import unittest
from unittest.mock import patch

from packages.quantum.services.candidate_disposition import (
    TABLE,
    CandidateDispositionRecorder,
    candidate_fingerprint,
)
from packages.quantum.services.cost_reconciliation_artifact import (
    ARTIFACT_VERSION,
    build_cost_reconciliation,
)
from packages.quantum.tests.test_prerejection_fork_e19 import FakeSupabase

# Reuse the route harness (drives the real suggestions_open.run cycle).
from packages.quantum.tests.test_candidate_disposition_route import (
    _RouteBase,
    _scanner_candidate,
)

UID = "9d5f4c1e-0000-4000-8000-000000000001"
CYCLE_DATE = "2026-07-18"


# ── candidate shapes ──────────────────────────────────────────────────────
def _vertical(entry=0.30, contracts=None, **over):
    c = {
        "symbol": "SOFI", "ticker": "SOFI",
        "strategy": "LONG_CALL_DEBIT_SPREAD",
        "type": "LONG_CALL_DEBIT_SPREAD",
        "suggested_entry": entry, "ev": 30.0, "score": 65.0,
        "legs": [
            {"symbol": "SOFI260821C00026000", "side": "buy", "strike": 26.0,
             "type": "call", "expiry": "2026-08-21",
             "bid": 0.55, "ask": 0.65, "quantity": 1},
            {"symbol": "SOFI260821C00028000", "side": "sell", "strike": 28.0,
             "type": "call", "expiry": "2026-08-21",
             "bid": 0.25, "ask": 0.35, "quantity": 1},
        ],
    }
    if contracts is not None:
        c["sizing_metadata"] = {"contracts": contracts}
    c.update(over)
    return c


def _condor(contracts=None, **over):
    """A 4-leg iron condor — each leg (ask-bid)=0.10 -> $10/leg cross ->
    $40 per-structure-contract round-trip cross."""
    c = {
        "symbol": "IWM", "ticker": "IWM",
        "strategy": "IRON_CONDOR", "type": "IRON_CONDOR",
        "suggested_entry": 1.20, "ev": 45.0, "score": 60.0,
        "legs": [
            {"symbol": "IWM260821P00200000", "side": "sell", "strike": 200.0,
             "type": "put", "expiry": "2026-08-21",
             "bid": 1.10, "ask": 1.20, "quantity": 1},
            {"symbol": "IWM260821P00195000", "side": "buy", "strike": 195.0,
             "type": "put", "expiry": "2026-08-21",
             "bid": 0.70, "ask": 0.80, "quantity": 1},
            {"symbol": "IWM260821C00230000", "side": "sell", "strike": 230.0,
             "type": "call", "expiry": "2026-08-21",
             "bid": 1.05, "ask": 1.15, "quantity": 1},
            {"symbol": "IWM260821C00235000", "side": "buy", "strike": 235.0,
             "type": "call", "expiry": "2026-08-21",
             "bid": 0.60, "ask": 0.70, "quantity": 1},
        ],
    }
    if contracts is not None:
        c["sizing_metadata"] = {"contracts": contracts}
    c.update(over)
    return c


def _dark_quotes(cand):
    """Same structure, but every leg is unpriceable (no bid/ask)."""
    c = copy.deepcopy(cand)
    for leg in c["legs"]:
        leg.pop("bid", None)
        leg.pop("ask", None)
    return c


def _recorder(client):
    return CandidateDispositionRecorder(
        client, user_id=UID, cycle_date=CYCLE_DATE,
    )


def _rows(client):
    return client.tables.get(TABLE, [])


def _final(client):
    finals = [r for r in _rows(client) if r.get("is_final")]
    assert len(finals) == 1, f"expected one final, got {len(finals)}"
    return finals[0]


# ── builder contract (production assembler) ───────────────────────────────
class TestBuilderContract(unittest.TestCase):
    def _assert_envelope(self, art):
        self.assertIsNotNone(art)
        self.assertTrue(art["observe_only"])
        self.assertFalse(art["decisional"])
        self.assertEqual(art["artifact_version"], ARTIFACT_VERSION)
        # Must survive the jsonb round trip.
        self.assertEqual(json.loads(json.dumps(art))["flags"], list(art["flags"]))
        # Every canonical basis is typed present/unavailable — never dropped.
        for name in ("scanner_estimate", "scanner_unified_final",
                     "ranker_model", "stage_executable_cross", "tcm",
                     "tcm_legacy", "realized"):
            self.assertIn(name, art["bases_status"])
            st = art["bases_status"][name]
            if not st["available"]:
                self.assertIsNotNone(st["reason"])  # typed reason, not zero

    def test_vertical_qty_gt_1_scales_and_flags_e2(self):
        art = build_cost_reconciliation(_vertical(contracts=4))
        self._assert_envelope(art)
        self.assertEqual(art["quantity"], 4.0)
        stage = art["normalized"]["stage_executable_cross"]
        # 2 legs x $10 cross = $20 per-structure-contract; x4 lots = $80 total.
        self.assertAlmostEqual(stage["per_structure_contract_usd"], 20.0, 3)
        self.assertAlmostEqual(stage["total_usd"], 80.0, 3)
        self.assertTrue(art["bases_status"]["ranker_model"]["available"])
        self.assertTrue(art["bases_status"]["stage_executable_cross"]["available"])
        # The E2 legacy-basis divergence is a TYPED flag at qty>1.
        self.assertIn("legacy_gate_basis_divergent_qty_gt_1", art["flags"])
        qd = [d for d in art["deltas"]
              if d["name"] == "quantity_scaling_stage_total_vs_per_contract"][0]
        self.assertTrue(qd["available"])
        self.assertAlmostEqual(qd["amount_usd"], 60.0, 3)  # 80 - 20

    def test_condor_four_legs_qty_gt_1(self):
        art = build_cost_reconciliation(_condor(contracts=3))
        self._assert_envelope(art)
        self.assertEqual(art["quantity"], 3.0)
        stage = art["normalized"]["stage_executable_cross"]
        # 4 legs x $10 = $40 per-structure-contract; x3 = $120 total.
        self.assertAlmostEqual(stage["per_structure_contract_usd"], 40.0, 3)
        self.assertAlmostEqual(stage["total_usd"], 120.0, 3)
        # ranker fee basis reflects the true 4-leg structure (not legacy 1-leg).
        self.assertTrue(art["bases_status"]["ranker_model"]["available"])

    def test_missing_basis_is_typed_unavailable_never_zero(self):
        # Dark quotes -> the executable cross is UNAVAILABLE (all-or-nothing),
        # never a fabricated zero; the ranker basis still reconstructs.
        art = build_cost_reconciliation(_dark_quotes(_vertical(contracts=2)))
        self._assert_envelope(art)
        stage = art["bases_status"]["stage_executable_cross"]
        self.assertFalse(stage["available"])
        self.assertIsNotNone(stage["reason"])
        # The normalized entry is present but typed UNAVAILABLE (with a
        # reason) — never a fabricated zero, never silently dropped.
        norm_stage = art["normalized"]["stage_executable_cross"]
        self.assertEqual(norm_stage["total_usd"], "UNAVAILABLE")
        self.assertIsNotNone(norm_stage["total_usd_reason"])
        # The slippage delta that needs the cross is typed-unavailable, not 0.
        sd = [d for d in art["deltas"]
              if d["name"] == "slippage_executable_cross_vs_ranker_proxy"][0]
        self.assertFalse(sd["available"])
        self.assertIsNone(sd["amount_usd"])

    def test_no_legs_yields_typed_stage_unavailable(self):
        art = build_cost_reconciliation(
            {"ticker": "X", "strategy": "S", "ev": 12.0})
        self.assertIsNotNone(art)  # ranker legacy basis still builds
        self.assertEqual(
            art["bases_status"]["stage_executable_cross"]["reason"],
            "no_candidate_legs",
        )

    def test_builder_never_mutates_candidate(self):
        cand = _condor(contracts=5)
        before = copy.deepcopy(cand)
        build_cost_reconciliation(cand)
        self.assertEqual(cand, before)

    def test_non_mapping_returns_none(self):
        self.assertIsNone(build_cost_reconciliation(None))
        self.assertIsNone(build_cost_reconciliation(["not", "a", "map"]))


# ── writer seam (production entrypoint: record_final) ─────────────────────
class TestWriterSeamAttachesArtifact(unittest.TestCase):
    def test_vertical_final_carries_artifact(self):
        client = FakeSupabase()
        rec = _recorder(client)
        cand = _vertical(contracts=4)
        rec.record_selected([cand])
        rec.record_final(cand, "rank_blocked",
                         detail={"reason": "edge_below_minimum"})
        row = _final(client)
        self.assertEqual(row["disposition"], "rank_blocked")
        # Caller detail preserved AND the artifact attached alongside it.
        self.assertEqual(row["detail"]["reason"], "edge_below_minimum")
        art = row["detail"]["cost_reconciliation"]
        self.assertTrue(art["observe_only"])
        self.assertFalse(art["decisional"])
        self.assertEqual(art["quantity"], 4.0)
        self.assertTrue(art["bases_status"]["stage_executable_cross"]["available"])

    def test_condor_final_carries_artifact(self):
        client = FakeSupabase()
        rec = _recorder(client)
        cand = _condor(contracts=3)
        rec.record_selected([cand])
        rec.record_final(cand, "allocator_dropped",
                         detail={"reason": "not_in_allocator_output"})
        art = _final(client)["detail"]["cost_reconciliation"]
        self.assertAlmostEqual(
            art["normalized"]["stage_executable_cross"][
                "per_structure_contract_usd"], 40.0, 3)

    def test_artifact_computed_once_per_attempt_across_refinement(self):
        # A re-final of the SAME attempt (ranker seam -> persist seam) must
        # inherit the artifact, never recompute or duplicate it.
        client = FakeSupabase()
        rec = _recorder(client)
        cand = _vertical(contracts=2)
        rec.record_selected([cand])
        rec.record_final(cand, "rank_blocked", detail={"reason": "r1"})
        first = _final(client)["detail"]["cost_reconciliation"]
        with patch("packages.quantum.services.cost_reconciliation_artifact."
                   "build_cost_reconciliation") as spy:
            spy.side_effect = AssertionError("must not recompute on refine")
            rec.record_final(cand, "rank_blocked",
                             detail={"status": "NOT_EXECUTABLE"},
                             suggestion_id="1e8a0f9c-0000-4000-8000-0000000000aa")
        row = _final(client)
        self.assertEqual(row["detail"]["cost_reconciliation"], first)
        self.assertEqual(row["detail"]["status"], "NOT_EXECUTABLE")

    def test_disposition_without_candidate_dict_omits_artifact(self):
        # record_final permits cand=None (symbol/strategy/fingerprint only) —
        # no candidate => no artifact, and the write still succeeds.
        client = FakeSupabase()
        rec = _recorder(client)
        rec.record_final(None, "persisted_blocked",
                         detail={"insert_failed": True},
                         symbol="AAPL", strategy="S",
                         fingerprint="abc123")
        row = _final(client)
        self.assertNotIn("cost_reconciliation", row["detail"])
        self.assertEqual(rec.counters["finals_recorded"], 1)


# ── artifact-failure-does-not-break-write (inject at deepest callee) ──────
class TestArtifactFailureNeverBreaksWrite(unittest.TestCase):
    def test_reconcile_raising_still_persists_disposition(self):
        # Origin injection at the DEEPEST callee: the pure reconcile step
        # throws. The builder's fail-soft returns None; the disposition row
        # still persists with no artifact and clean counters.
        client = FakeSupabase()
        rec = _recorder(client)
        cand = _vertical(contracts=4)
        rec.record_selected([cand])
        with patch("packages.quantum.analytics.cost_basis."
                   "reconcile_cost_bases",
                   side_effect=RuntimeError("boom deep in cost_basis")):
            rec.record_final(cand, "h7_dropped", detail={"reason": "sized_zero"})
        row = _final(client)
        self.assertEqual(row["disposition"], "h7_dropped")
        self.assertEqual(row["detail"]["reason"], "sized_zero")
        self.assertNotIn("cost_reconciliation", row["detail"])
        self.assertEqual(rec.counters["finals_recorded"], 1)
        self.assertEqual(rec.counters["write_failures"], 0)

    def test_builder_raising_still_persists_disposition(self):
        client = FakeSupabase()
        rec = _recorder(client)
        cand = _vertical(contracts=2)
        rec.record_selected([cand])
        with patch("packages.quantum.services.cost_reconciliation_artifact."
                   "build_cost_reconciliation",
                   side_effect=RuntimeError("builder exploded")):
            rec.record_final(cand, "rank_blocked", detail={"reason": "edge"})
        row = _final(client)
        self.assertEqual(row["disposition"], "rank_blocked")
        self.assertNotIn("cost_reconciliation", row["detail"])
        self.assertEqual(rec.counters["finals_recorded"], 1)
        self.assertEqual(rec.counters["write_failures"], 0)


# ── full production route (suggestions_open.run) ──────────────────────────
class TestFullRouteAttachesArtifact(_RouteBase):
    # The ×0.5 calibration blob that drives the SOFI vertical to a real
    # ranker rejection (edge_below_minimum) -> a durable rank_blocked final.
    CAL_BLOB_HALF = {
        "LONG_CALL_DEBIT_SPREAD": {
            "normal": {"ev_multiplier": 0.5, "pop_multiplier": 1.0},
        },
    }

    def test_route_final_carries_observe_only_artifact(self):
        client = FakeSupabase()
        self._seed(client)
        result = self._drive(client, [_scanner_candidate()],
                             cal_blob=self.CAL_BLOB_HALF)
        self.assertTrue(result["ok"], result.get("notes"))

        finals = [r for r in self._ctd_rows(client) if r.get("is_final")]
        self.assertEqual(len(finals), 1)
        final = finals[0]
        self.assertEqual(final["disposition"], "rank_blocked")
        art = final["detail"]["cost_reconciliation"]
        self.assertTrue(art["observe_only"])
        self.assertFalse(art["decisional"])
        self.assertEqual(art["artifact_version"], ARTIFACT_VERSION)
        # Both reconstructable bases present on a real end-to-end disposition.
        self.assertTrue(art["bases_status"]["ranker_model"]["available"])
        self.assertTrue(
            art["bases_status"]["stage_executable_cross"]["available"])
        # The known exhibit decision is unchanged (observe-only).
        src = [r for r in client.tables["trade_suggestions"]
               if r.get("ticker") == "SOFI"
               and r.get("cohort_name") is None][0]
        self.assertEqual(src["status"], "NOT_EXECUTABLE")
        self.assertEqual(src["blocked_reason"], "edge_below_minimum")


if __name__ == "__main__":
    unittest.main()
