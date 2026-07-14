"""B19-B23 RED reproductions against ec5042d (Phase 1).

These fail on ec5042d for the intended reasons; they are superseded by the
full B19-B23 suites once implemented (kept as living regression). Uses the
hardened contract fake from the main E19 test module.
"""
import copy
import os
import unittest
import uuid
from unittest.mock import patch

from packages.quantum.policy_lab import fork as fork_mod
from packages.quantum.policy_lab.config import PolicyConfig
from packages.quantum.tests.test_prerejection_fork_e19 import (
    FakeSupabase, UID, _pending_qqq, _prerejected_sofi, _seed, _run_fork,
    _clones, _verdicts, _has_filter,
)


class TestB19Repro(unittest.TestCase):
    def setUp(self):
        os.environ.pop("SHADOW_RAW_EV_ENABLED", None)

    def test_portfolio_missing_pair_is_counted_and_partial(self):
        """B19: a challenger whose portfolio row/binding is missing must still
        count the source×challenger attempt and go partial — ec5042d skips it
        silently (continue before _process_prerejection_source)."""
        client = FakeSupabase()
        sofi = _prerejected_sofi()
        _seed(client, _pending_qqq(), sofi)
        # neutral has a cohort id row but NO portfolio_id
        client.tables["policy_lab_cohorts"] = [
            r for r in client.tables["policy_lab_cohorts"]
            if r["cohort_name"] != "neutral"]
        client.tables["policy_lab_cohorts"].append(
            {"id": "c-neu", "user_id": UID, "cohort_name": "neutral",
             "portfolio_id": None, "is_active": True})
        res = _run_fork(client)
        c = res["prerejection_counts"]
        self.assertEqual(res["status"], "partial")
        self.assertEqual(c["source_cohort_attempts"], 1)   # RED: 0 on ec5042d
        self.assertEqual(c.get("cohort_portfolio_missing", 0), 1)
        self.assertEqual(_clones(client, ticker="SOFI"), [])

    def test_capital_100k_fabrication_removed(self):
        """B19-I: a portfolio with net_liq=0 and cash_balance=0 must fail
        closed (cohort_capital_invalid), NOT fabricate $100,000. RED on
        ec5042d: `net_liq or cash_balance or 100000` → 100000 → clone made."""
        client = FakeSupabase()
        sofi = _prerejected_sofi()
        _seed(client, _pending_qqq(), sofi)
        for p in client.tables["paper_portfolios"]:
            if p["id"] == "pf-neu":
                p["net_liq"] = 0
                p["cash_balance"] = 0
        res = _run_fork(client)
        c = res["prerejection_counts"]
        self.assertEqual(res["status"], "partial")
        self.assertEqual(c.get("cohort_capital_invalid", 0), 1)
        self.assertEqual(_clones(client, ticker="SOFI"), [])

    def test_expected_coverage_fields_present(self):
        client = FakeSupabase()
        sofi = _prerejected_sofi()
        _seed(client, _pending_qqq(), sofi)
        res = _run_fork(client)
        self.assertIn("expected_source_cohort_attempts", res)   # RED: absent
        self.assertIn("coverage_complete", res)
        self.assertTrue(res["coverage_complete"])
        self.assertEqual(res["expected_source_cohort_attempts"],
                         res["prerejection_source_cohort_attempts"])


class TestB20Repro(unittest.TestCase):
    def setUp(self):
        os.environ.pop("SHADOW_RAW_EV_ENABLED", None)

    def test_no_false_calibration_identity(self):
        """B20: the clone/verdict must NOT stamp calibration_identity from
        model_version; it must carry source_model_version +
        calibration_provenance_status='not_persisted_on_source'."""
        client = FakeSupabase()
        sofi = _prerejected_sofi()
        _seed(client, _pending_qqq(), sofi)
        _run_fork(client)
        clone = _clones(client, ticker="SOFI")[0]
        sz = clone["sizing_metadata"]
        self.assertNotIn("calibration_identity", sz)   # RED: present on ec5042d
        self.assertEqual(sz.get("source_model_version"), sofi["model_version"])
        self.assertEqual(sz.get("calibration_provenance_status"),
                         "not_persisted_on_source")


class TestB22Repro(unittest.TestCase):
    def setUp(self):
        os.environ.pop("SHADOW_RAW_EV_ENABLED", None)

    def test_rejected_verdicts_counted(self):
        """B22: a successful REJECTED verdict must increment rejected_verdicts;
        total = accepted + rejected. RED: ec5042d only counts accepted."""
        client = FakeSupabase()
        good = _prerejected_sofi()
        no_basis = _prerejected_sofi(ev_raw=None)
        no_basis.update({"id": str(uuid.uuid4()), "ticker": "XPEV",
                         "legs_fingerprint": "fp-xpev",
                         "trace_id": str(uuid.uuid4())})
        _seed(client, _pending_qqq(), good, no_basis)
        res = _run_fork(client)
        self.assertEqual(res.get("prerejection_eligible_verdict_count"), 1)
        self.assertEqual(res.get("prerejection_ineligible_verdict_count"), 1)  # RED
        self.assertEqual(res.get("prerejection_total_verdict_count"), 2)


class TestB23Repro(unittest.TestCase):
    def setUp(self):
        os.environ.pop("SHADOW_RAW_EV_ENABLED", None)

    def test_observation_scope_narrowed(self):
        """B23: observation_scope must be raw_candidate_eligibility_only +
        decision_semantics + selected_for_entry=false. RED: ec5042d says
        entry_selection_only."""
        client = FakeSupabase()
        sofi = _prerejected_sofi()
        _seed(client, _pending_qqq(), sofi)
        _run_fork(client)
        sz = _clones(client, ticker="SOFI")[0]["sizing_metadata"]
        self.assertEqual(sz.get("observation_scope"),
                         "raw_candidate_eligibility_only")   # RED
        self.assertEqual(sz.get("decision_semantics"),
                         "raw_candidate_eligibility")
        self.assertIs(sz.get("selected_for_entry"), False)
        self.assertIs(sz.get("capacity_evaluated"), False)
        self.assertIs(sz.get("joint_rank_evaluated"), False)


if __name__ == "__main__":
    unittest.main()
