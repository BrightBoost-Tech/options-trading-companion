"""Lane 4B — durable terminal dispositions for NON-SELECTED candidates.

Closes the non-selected-alternate gap (Monday cycle 608c7682: the scanner
emitted 8 concrete candidates, 2 selected primaries got ``h7_dropped``
finals, and the 6 NON-SELECTED alternates got NO durable final). The writer
previously covered only the rank_and_select-SELECTED set; ``rank_and_select``
returns just its survivors, so the candidates it passed over vanished with no
terminal fate.

Doctrine (v1.4 07-12): inject at the ORIGIN, assert at the TOP. Every test
drives the REAL ``suggestions_open.run`` -> ``run_midday_cycle`` (the shared
harness in test_candidate_disposition_route.py) with stubs only at genuine
external boundaries, and asserts on durable DB rows + the top-level cycle
counts / job status — never on recorder internals.

Contract proven end-to-end:
  - 8 EMITTED -> 8 honest finals (2 h7_dropped selected + 6 rank_blocked
    not-selected); the 163-style scanner rejections are NOT turned into
    dispositions (only the emitted candidates are);
  - one final per identity; a job RETRY (same cycle_id) does not duplicate;
  - a dead ``rank_blocked`` terminal can NEVER advance to a live milestone;
  - a genuine alternate write FAILURE surfaces -> job PARTIAL (H9);
  - the selection/decision output (persisted trade_suggestions + the selected
    finals) is BYTE-IDENTICAL with vs without the new alternate writes.
"""

import copy
import os
import unittest
from unittest.mock import patch

from packages.quantum.services.candidate_disposition import (
    TABLE,
    CandidateDispositionRecorder,
    advance_candidate_milestone,
    candidate_fingerprint,
)
from packages.quantum.tests.test_prerejection_fork_e19 import FakeSupabase, UID
from packages.quantum.tests.test_candidate_disposition_route import (
    _RouteBase,
    _scanner_candidate,
)


# ── Monday-shaped fixture ─────────────────────────────────────────────────
# 8 structurally-distinct SOFI verticals (distinct strike pairs -> distinct
# legs fingerprints). ``score`` controls rank_and_select: >=40 clears the
# quality floor (SELECTED), <40 is passed over (the NON-selected alternate).
def _variant(buy_strike, score, *, max_loss=None, entry=0.30, ev=30.73):
    c = copy.deepcopy(_scanner_candidate())
    sell_strike = buy_strike + 2
    c["score"] = float(score)
    c["suggested_entry"] = entry
    c["ev"] = ev
    if max_loss is not None:
        c["max_loss_per_contract"] = float(max_loss)
    c["legs"][0]["strike"] = float(buy_strike)
    c["legs"][0]["symbol"] = f"SOFI260821C{int(buy_strike * 1000):08d}"
    c["legs"][1]["strike"] = float(sell_strike)
    c["legs"][1]["symbol"] = f"SOFI260821C{int(sell_strike * 1000):08d}"
    return c


def _monday_eight():
    """2 SELECTED primaries (score 60, max_loss 50000 -> H7-unfit) + 6
    NON-selected alternates (score 10, below the 40 floor). 8 distinct
    fingerprints."""
    selected = [_variant(26, 60, max_loss=50000.0),
                _variant(30, 60, max_loss=50000.0)]
    alternates = [_variant(bs, 10) for bs in (34, 38, 42, 46, 50, 54)]
    return selected + alternates


def _executable_eight():
    """Same 2/6 split but the 2 selected are executable (persist as
    persisted_executable) so there IS a meaty persisted output to compare in
    the byte-identity proof."""
    selected = [_variant(26, 60, max_loss=300.0, entry=3.00, ev=100.0),
                _variant(30, 60, max_loss=300.0, entry=3.00, ev=100.0)]
    alternates = [_variant(bs, 10) for bs in (34, 38, 42, 46, 50, 54)]
    return selected + alternates


class _AltBase(_RouteBase):
    def _by_disposition(self, client, disp):
        return [r for r in self._finals(client) if r.get("disposition") == disp]

    @staticmethod
    def _ts_projection(client):
        """The DECISION output: the persisted trade_suggestions, projected to
        the fields a downstream consumer reads. Alternates never persist here,
        so this is the selected path's output only."""
        rows = client.tables.get("trade_suggestions", [])
        return sorted(
            (
                (
                    r.get("ticker"), r.get("strategy"), r.get("window"),
                    r.get("cohort_name"), r.get("status"),
                    r.get("blocked_reason"), r.get("ev"),
                    r.get("legs_fingerprint"),
                    str(r.get("order_json", {}).get("legs")),
                )
                for r in rows
            ),
            key=lambda t: tuple(str(x) for x in t),
        )


class TestEightEmittedEightFinals(_AltBase):
    def test_two_h7_plus_six_not_selected(self):
        os.environ["H7_PREFILTER_ENABLED"] = "true"
        client = FakeSupabase()
        self._seed(client)
        cands = _monday_eight()
        emitted_fps = {candidate_fingerprint(c) for c in cands}
        selected_fps = {candidate_fingerprint(c) for c in cands[:2]}
        alt_fps = {candidate_fingerprint(c) for c in cands[2:]}
        self.assertEqual(len(emitted_fps), 8)  # 8 distinct identities

        result = self._drive(client, cands, cal_blob=None)
        self.assertTrue(result["ok"], result.get("notes"))

        # 8 EMITTED -> exactly 8 honest finals, one per identity.
        finals = self._assert_one_final_per_identity(client)
        self.assertEqual({fp for (_c, fp) in finals.keys()}, emitted_fps)
        self.assertEqual(len(finals), 8)

        # 2 selected primaries -> h7_dropped (selected=true), the active
        # prefilter's round-trip BP kill.
        h7 = self._by_disposition(client, "h7_dropped")
        self.assertEqual({r["candidate_fingerprint"] for r in h7}, selected_fps)
        self.assertTrue(all(r["selected"] for r in h7))
        self.assertTrue(all(r["detail"]["h7_subreason"] == "roundtrip_bp"
                            for r in h7))

        # 6 non-selected alternates -> rank_blocked (selected=false), known
        # facts only, no fabricated break reason / economics.
        rb = self._by_disposition(client, "rank_blocked")
        self.assertEqual({r["candidate_fingerprint"] for r in rb}, alt_fps)
        self.assertEqual(len(rb), 6)
        for r in rb:
            self.assertFalse(r["selected"])
            self.assertTrue(r["is_final"])
            d = r["detail"]
            self.assertEqual(d["reason"], "not_selected_by_ranker")
            self.assertEqual(d["selection_stage"], "rank_and_select")
            self.assertEqual(d["score"], 10.0)          # actually computed
            self.assertEqual(d["emitted_count"], 8)
            self.assertEqual(d["selected_count"], 2)
            self.assertNotIn("available_bp", d)          # never reached H7
            self.assertNotIn("rt_required", d)           # not computed
            self.assertIsNotNone(r.get("code_sha"))
            self.assertIsNone(r.get("suggestion_id"))    # never persisted

        # PRESERVE scanner evidence: the alternates are the EMITTED-not-selected
        # set, NOT the scanner rejections — nothing extra was fabricated.
        self.assertEqual(
            [r for r in client.tables.get("trade_suggestions", [])
             if r.get("cohort_name") is None], [])

        ctd = self._cycle_counts(result)["candidate_disposition"]
        self.assertFalse(ctd["table_missing"])
        self.assertEqual(ctd["finals_recorded"], 8)
        self.assertEqual(ctd["write_failures"], 0)
        self.assertEqual(ctd["writer_taxonomy_violation"], 0)

    def tearDown(self):
        os.environ.pop("H7_PREFILTER_ENABLED", None)
        super().tearDown()


class TestWriterFailureIsPartial(_AltBase):
    def test_alternate_write_failure_makes_job_partial(self):
        os.environ["H7_PREFILTER_ENABLED"] = "true"
        client = FakeSupabase()
        self._seed(client)
        # Origin injection: the DB upsert of the NON-selected (rank_blocked)
        # rows throws a generic (non-table-missing) failure. The writer's
        # fail-soft catches it and counts write_failures; the cycle must NOT
        # ride green (H9 — no silent swallow).
        client.raise_when(
            TABLE, "upsert",
            predicate=lambda q: isinstance(q._payload, dict)
            and q._payload.get("disposition") == "rank_blocked",
        )

        result = self._drive(client, _monday_eight(), cal_blob=None)

        # TOP-LEVEL job truth: partial (ok=false) via counts.errors, and the
        # failure is visible in the disposition telemetry — never swallowed.
        self.assertFalse(result["ok"])
        self.assertGreater(result["counts"]["errors"], 0)
        ctd = self._cycle_counts(result)["candidate_disposition"]
        self.assertGreater(ctd["write_failures"], 0)
        self.assertFalse(ctd["table_missing"])  # a real failure, not a no-op

    def tearDown(self):
        os.environ.pop("H7_PREFILTER_ENABLED", None)
        super().tearDown()


class TestByteIdenticalDecisionOutput(_AltBase):
    """Observe-only proof: the SELECTED-path decision output is byte-identical
    with the new alternate-disposition writes ACTIVE vs a no-op — the only
    delta is the 6 durable rank_blocked rows."""

    def _run(self, alternate_writes_active):
        client = FakeSupabase()
        self._seed(client)
        extra = ()
        if not alternate_writes_active:
            extra = (
                patch.object(CandidateDispositionRecorder,
                             "record_not_selected",
                             lambda self, *a, **k: None),
            )
        result = self._drive(client, _executable_eight(), cal_blob=None,
                             extra_patches=extra)
        self.assertTrue(result["ok"], result.get("notes"))
        return client, result

    def test_selected_output_identical_with_and_without_alternates(self):
        client_on, _ = self._run(alternate_writes_active=True)
        client_off, _ = self._run(alternate_writes_active=False)

        # (1) The persisted DECISION output is byte-identical.
        self.assertEqual(self._ts_projection(client_on),
                         self._ts_projection(client_off))

        # (2) The SELECTED candidates' finals are byte-identical (same
        #     dispositions, same identities) — the selected path is untouched.
        def _selected_finals(c):
            return sorted(
                (r["candidate_fingerprint"], r["disposition"])
                for r in self._finals(c) if r.get("selected"))
        self.assertEqual(_selected_finals(client_on),
                         _selected_finals(client_off))
        self.assertTrue(_selected_finals(client_on))  # non-empty (persisted)

        # (3) The ONLY delta: the 6 rank_blocked alternates exist iff active.
        rb_on = [r for r in self._finals(client_on)
                 if r["disposition"] == "rank_blocked"]
        rb_off = [r for r in self._finals(client_off)
                  if r["disposition"] == "rank_blocked"]
        self.assertEqual(len(rb_on), 6)
        self.assertEqual(rb_off, [])


class TestRetryAndDeadTerminalSeam(unittest.TestCase):
    """The record_not_selected -> record_final -> upsert seam driven directly
    for the two invariants a route drive cannot cheaply reproduce: a job
    RETRY (same cycle_id, fresh process) and a dead-terminal advance attempt.
    """

    CYCLE_DATE = "2026-07-20"

    def _cands(self):
        sel = [_variant(26, 60), _variant(30, 60)]
        alt = [_variant(bs, 10) for bs in (34, 38, 42, 46, 50, 54)]
        return sel, alt

    def test_retry_same_cycle_id_does_not_duplicate_finals(self):
        client = FakeSupabase()
        client.tables[TABLE] = []
        sel, alt = self._cands()
        emitted = sel + alt

        # First run.
        rec1 = CandidateDispositionRecorder(
            client, user_id=UID, cycle_date=self.CYCLE_DATE, cycle_id="cyc-1")
        rec1.record_not_selected(emitted, sel)
        first = [r for r in client.tables[TABLE]
                 if r.get("disposition") == "rank_blocked"]
        self.assertEqual(len(first), 6)

        # Job RETRY: a fresh recorder (attempt tracking reset) with the SAME
        # cycle_id re-runs the same emitted/selected split on FRESH candidate
        # objects (a new process rebuilds them). The partial-unique upsert
        # (cycle_id, fingerprint, attempt) must dedup -> still 6, no duplicate
        # finals.
        rerun = [copy.deepcopy(c) for c in emitted]
        rec2 = CandidateDispositionRecorder(
            client, user_id=UID, cycle_date=self.CYCLE_DATE, cycle_id="cyc-1")
        rec2.record_not_selected(rerun, rerun[:2])

        finals = [r for r in client.tables[TABLE] if r.get("is_final")]
        by_identity = {}
        for r in finals:
            key = (r["cycle_id"], r["candidate_fingerprint"])
            self.assertNotIn(key, by_identity,
                             f"duplicate final for identity {key}")
            by_identity[key] = r
        rb = [r for r in finals if r["disposition"] == "rank_blocked"]
        self.assertEqual(len(rb), 6)

    def test_rank_blocked_dead_terminal_never_advances(self):
        client = FakeSupabase()
        client.tables[TABLE] = []
        sel, alt = self._cands()
        rec = CandidateDispositionRecorder(
            client, user_id=UID, cycle_date=self.CYCLE_DATE, cycle_id="cyc-2")
        # An alternate final, stamped with a suggestion_id (simulating an
        # ERRONEOUS executor that later tries to advance a dead terminal).
        sid = "11111111-1111-4111-8111-111111111111"
        rec.record_final(alt[0], "rank_blocked",
                         detail={"reason": "not_selected_by_ranker"},
                         suggestion_id=sid, selected=False)
        before = [r for r in client.tables[TABLE] if r.get("suggestion_id") == sid]
        self.assertEqual(len(before), 1)
        self.assertEqual(before[0]["disposition"], "rank_blocked")

        for milestone in ("staged", "broker_submitted", "filled"):
            res = advance_candidate_milestone(client, sid, milestone)
            self.assertEqual(res["status"], "not_advanceable",
                             f"{milestone} must not advance a dead terminal")

        after = [r for r in client.tables[TABLE] if r.get("suggestion_id") == sid]
        self.assertEqual(len(after), 1)
        self.assertEqual(after[0]["disposition"], "rank_blocked")  # unchanged


if __name__ == "__main__":
    unittest.main()
