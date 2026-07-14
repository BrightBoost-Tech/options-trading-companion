"""B24-B26 RED reproductions against 4758d3a (surgical closure).

Kept as living regression once implemented.
"""
import copy
import math
import os
import unittest
import uuid
from unittest.mock import patch

from packages.quantum.policy_lab import fork as fork_mod
from packages.quantum.policy_lab.config import PolicyConfig
from packages.quantum.tests.test_prerejection_fork_e19 import (
    FakeSupabase, UID, _pending_qqq, _prerejected_sofi, _seed, _run_fork,
    _clones, _verdicts,
)


class TestB24Repro(unittest.TestCase):
    def setUp(self):
        os.environ.pop("SHADOW_RAW_EV_ENABLED", None)

    def _accepted_snapshot(self):
        client = FakeSupabase()
        sofi = _prerejected_sofi()
        _seed(client, _pending_qqq(), sofi)
        _run_fork(client)
        v = _verdicts(client, sofi["id"], "accepted")[0]
        return v

    def test_accepted_snapshot_has_full_scope_contract(self):
        fs = self._accepted_snapshot()["features_snapshot"]
        for f in ("capacity_evaluated", "joint_rank_evaluated",
                  "execution_intent"):
            self.assertIn(f, fs, f)   # RED: omitted on 4758d3a
        self.assertIs(fs["capacity_evaluated"], False)
        self.assertIs(fs["joint_rank_evaluated"], False)

    def test_accepted_rank_is_none(self):
        v = self._accepted_snapshot()
        self.assertIsNone(v["rank_at_decision"])   # RED: 1 on 4758d3a

    def test_accepted_reason_is_raw_candidate_eligible(self):
        v = self._accepted_snapshot()
        self.assertEqual(v["reason_codes"], ["raw_candidate_eligible_observation"])

    def test_rejected_snapshot_full_contract(self):
        client = FakeSupabase()
        nb = _prerejected_sofi(ev_raw=None)
        _seed(client, _pending_qqq(), nb)
        _run_fork(client)
        v = _verdicts(client, nb["id"], "rejected")[0]
        self.assertIsNone(v["rank_at_decision"])
        fs = v["features_snapshot"]
        for f in ("observation_scope", "decision_semantics", "selected_for_entry",
                  "execution_state", "execution_intent", "routing_intent",
                  "source_model_version", "calibration_provenance_status",
                  "experiment_version", "capacity_evaluated",
                  "joint_rank_evaluated"):
            self.assertIn(f, fs, f)   # RED
        self.assertEqual(fs["calibration_provenance_status"],
                         "not_persisted_on_source")

    def test_validator_binds_capacity_and_joint_rank(self):
        client = FakeSupabase()
        sofi = _prerejected_sofi()
        _seed(client, _pending_qqq(), sofi)
        _run_fork(client)
        expected, _ = fork_mod._build_prerejection_clone(
            copy.deepcopy(sofi), "neutral",
            PolicyConfig(min_score_threshold=0.0), 10000.0)
        for field in ("capacity_evaluated", "joint_rank_evaluated"):
            tampered = copy.deepcopy(expected)
            tampered["sizing_metadata"][field] = True
            kind, f = fork_mod._validate_persisted_clone(tampered, expected, sofi)
            self.assertEqual((kind, f),
                             ("clone_identity_mismatch", field))   # RED


class TestB25Repro(unittest.TestCase):
    def setUp(self):
        os.environ.pop("SHADOW_RAW_EV_ENABLED", None)

    def _expected_and_source(self):
        sofi = _prerejected_sofi()
        expected, _ = fork_mod._build_prerejection_clone(
            copy.deepcopy(sofi), "neutral",
            PolicyConfig(min_score_threshold=0.0), 10000.0)
        return expected, sofi

    def test_nan_ev_passes_on_4758d3a(self):
        """RED: NaN slips through abs()>tol (NaN>tol is False)."""
        expected, sofi = self._expected_and_source()
        tampered = copy.deepcopy(expected)
        tampered["ev"] = float("nan")
        tampered["ev_raw"] = float("nan")
        kind, f = fork_mod._validate_persisted_clone(tampered, expected, sofi)
        self.assertIsNotNone(kind)   # RED: None on 4758d3a (NaN passed)

    def test_fractional_contracts_truncate_match_on_4758d3a(self):
        """RED: int(1.9)==1 matches expected qty 1 spuriously."""
        expected, sofi = self._expected_and_source()
        tampered = copy.deepcopy(expected)
        # expected clone is 5ct; make all three 5.9 to isolate truncation
        tampered["sizing_metadata"]["clone_contracts"] = 5.9
        tampered["sizing_metadata"]["contracts"] = 5.9
        tampered["order_json"]["contracts"] = 5.9
        kind, f = fork_mod._validate_persisted_clone(tampered, expected, sofi)
        self.assertIsNotNone(kind)   # RED: int(5.9)==5 matched → None

    # ---- full fail-closed matrix (green after B25) ----
    def _validate(self, mutate):
        expected, sofi = self._expected_and_source()
        tampered = copy.deepcopy(expected)
        mutate(tampered)
        return fork_mod._validate_persisted_clone(tampered, expected, sofi)

    def test_numeric_fields_nan_and_inf_fail_closed(self):
        NUMERIC = [
            ("ev", lambda t, v: t.__setitem__("ev", v)),
            ("ev_raw", lambda t, v: t.__setitem__("ev_raw", v)),
            ("ev_calibrated",
             lambda t, v: t["sizing_metadata"].__setitem__("ev_calibrated", v)),
            ("risk_adjusted_ev",
             lambda t, v: t.__setitem__("risk_adjusted_ev", v)),
            ("max_loss_total",
             lambda t, v: t.__setitem__("max_loss_total", v)),
            ("sizing_max_loss_total",
             lambda t, v: t["sizing_metadata"].__setitem__("max_loss_total", v)),
            ("limit_price",
             lambda t, v: t["order_json"].__setitem__("limit_price", v)),
        ]
        for name, setter in NUMERIC:
            for bad in (float("nan"), float("inf"), float("-inf")):
                # ev/ev_raw must stay equal to avoid masking; set both when ev
                mut = setter
                if name == "ev":
                    def mut(t, s=setter, b=bad):
                        t["ev"] = b; t["ev_raw"] = b
                kind, f = self._validate(lambda t: mut(t, bad))
                self.assertIsNotNone(kind, f"{name}={bad} passed")
                self.assertEqual(kind, "clone_basis_mismatch", name)

    def test_contract_fields_reject_fractional_zero_neg_nonnumeric_bool(self):
        FIELDS = [
            lambda t, v: t["sizing_metadata"].__setitem__("contracts", v),
            lambda t, v: t["sizing_metadata"].__setitem__("clone_contracts", v),
            lambda t, v: t["order_json"].__setitem__("contracts", v),
        ]
        for setter in FIELDS:
            for bad in (5.9, 0, -5, float("nan"), float("inf"), "5.9",
                        "x", True):
                kind, f = self._validate(lambda t: setter(t, bad))
                self.assertEqual((kind, f),
                                 ("clone_basis_mismatch", "clone_contracts"),
                                 f"bad={bad!r}")

    def test_integer_equivalent_forms_pass(self):
        # the SOFI clone is 5 contracts; 5 / 5.0 / "5" / "5.0" all valid
        for good in (5, 5.0, "5", "5.0"):
            def mut(t, g=good):
                t["sizing_metadata"]["contracts"] = g
                t["sizing_metadata"]["clone_contracts"] = g
                t["order_json"]["contracts"] = g
            kind, f = self._validate(mut)
            self.assertIsNone(kind, f"good={good!r} rejected: {f}")


class TestB26Repro(unittest.TestCase):
    def setUp(self):
        os.environ.pop("SHADOW_RAW_EV_ENABLED", None)

    def _assert_invariant_and_partial(self, res):
        self.assertEqual(res.get("expected_source_cohort_attempts"), 1)
        self.assertEqual(res["prerejection_source_cohort_attempts"], 1)
        c = res["prerejection_counts"]
        self.assertEqual(
            c["source_cohort_attempts"],
            c["accepted"] + c["refused"] + c["clone_failed"]
            + c["identity_mismatch"] + c["accepted_verdict_failed"]
            + c["cohort_binding_unavailable"] + c["cohort_identity_missing"]
            + c["cohort_portfolio_missing"] + c["cohort_capital_invalid"])
        self.assertEqual(res["status"], "partial")

    def test_legacy_open_positions_failure_preserves_b19(self):
        """paper_positions is read ONLY in the legacy loop (coverage uses
        paper_portfolios for capital) — the cleanest legacy-only fault: the
        prerejection clone/verdict are already captured and B19 accounting
        survives."""
        client = FakeSupabase()
        sofi = _prerejected_sofi()
        _seed(client, _pending_qqq(), sofi)
        client.raise_when("paper_positions", "select")
        res = _run_fork(client)
        self._assert_invariant_and_partial(res)
        self.assertEqual(len(_clones(client, ticker="SOFI")), 1)   # captured
        stages = {e["stage"] for e in res["error_details"]}
        self.assertIn("legacy_normal_clone_state_failed", stages)

    def test_portfolio_read_failure_fails_closed_and_survives_b19(self):
        """paper_portfolios is read by BOTH coverage (capital) and the legacy
        loop. A failure fails coverage capital CLOSED (cohort_capital_invalid,
        no clone — correct) AND is contained in the legacy loop; B19
        accounting + invariant still hold, job partial."""
        client = FakeSupabase()
        sofi = _prerejected_sofi()
        _seed(client, _pending_qqq(), sofi)
        client.raise_when("paper_portfolios", "select")
        res = _run_fork(client)
        self._assert_invariant_and_partial(res)
        self.assertEqual(res["prerejection_counts"]["cohort_capital_invalid"], 1)
        stages = {e["stage"] for e in res["error_details"]}
        self.assertIn("legacy_normal_clone_state_failed", stages)

    def test_coverage_runs_exactly_once_no_duplicate(self):
        client = FakeSupabase()
        sofi = _prerejected_sofi()
        _seed(client, _pending_qqq(), sofi)
        res = _run_fork(client)
        # one clone, one verdict, attempts counted once
        self.assertEqual(len(_clones(client, ticker="SOFI")), 1)
        self.assertEqual(len(_verdicts(client, sofi["id"], "accepted")), 1)
        self.assertEqual(res["prerejection_source_cohort_attempts"], 1)
        self.assertEqual(res["prerejection_counts"]["accepted"], 1)


if __name__ == "__main__":
    unittest.main()
