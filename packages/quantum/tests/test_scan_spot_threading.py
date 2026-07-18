"""⑤ scan-time underlying-spot threading — producer + persisted carrier.

Threads the scanner's OWN underlying quote-mid (``current_price`` — already used
as the option-chain ``spot=`` and written to ``option_liquidity_observations``)
to the stage seam so ``_populate_stage_entry_spot`` can upgrade the
``entry_underlying_spot`` marker from typed-unavailable to POPULATED (future
challenger scorability). OBSERVE-ONLY: no decision path reads it, no extra fetch.

Two hops proven here (the stage-seam consumer hop + guards live in
``test_stage_seam_spot_iv_capture.py``; the study scorability in
``test_challenger_study.py``):

  1. producer  options_scanner.build_scan_spot_capture — value semantics + the
     DETERMINISM contract (as_of is the INPUT provider quote timestamp, NEVER
     wall-clock, so the candidate byte-pin is preserved).
  2. carrier   workflow_orchestrator.build_midday_order_json — the capture rides
     the PERSISTED suggestion order_json as a TOP-LEVEL key, leaving the dedup
     fingerprint AND every decision-relevant order_json field byte-identical
     (§9: driven through the real production function; the full-route
     non-decisional proof drives the real ``suggestions_open.run``).
"""

import copy
import json
import math
import unittest

from packages.quantum.options_scanner import build_scan_spot_capture, _SCAN_SPOT_SOURCE
from packages.quantum.services.workflow_orchestrator import build_midday_order_json
from packages.quantum.services.options_utils import compute_legs_fingerprint


# ── 1. producer: build_scan_spot_capture ────────────────────────────────────
class TestBuildScanSpotCapture(unittest.TestCase):
    def test_finite_positive_value_captured_verbatim(self):
        cap = build_scan_spot_capture(123.45)
        self.assertEqual(cap["value"], 123.45)
        self.assertEqual(cap["source"], _SCAN_SPOT_SOURCE)

    def test_nonpositive_nonfinite_none_value_types_none_never_fabricated(self):
        for bad in (0.0, -1.0, -0.01, float("nan"), float("inf"),
                    float("-inf"), None, "not-a-number"):
            with self.subTest(bad=bad):
                cap = build_scan_spot_capture(bad)
                self.assertIsNone(cap["value"], f"{bad!r} should type value None")
                # source is still recorded — provenance, not a fabricated value.
                self.assertEqual(cap["source"], _SCAN_SPOT_SOURCE)

    def test_provider_ts_ms_renders_iso_utc_as_of(self):
        # 2026-07-18T12:00:00Z == 1784548800000 ms
        ms = 1784548800000
        cap = build_scan_spot_capture(100.0, provider_ts_ms=ms)
        self.assertEqual(cap["as_of_source"], "provider_quote_ts")
        # round-trips back to the same epoch (UTC, ISO-8601)
        from datetime import datetime, timezone
        parsed = datetime.fromisoformat(cap["as_of"])
        self.assertEqual(int(parsed.astimezone(timezone.utc).timestamp() * 1000), ms)

    def test_no_provider_ts_labels_absent_never_wall_clock(self):
        cap = build_scan_spot_capture(100.0, provider_ts_ms=None)
        self.assertIsNone(cap["as_of"])
        self.assertEqual(cap["as_of_source"], "provider_ts_absent")

    def test_bad_provider_ts_falls_back_to_absent(self):
        cap = build_scan_spot_capture(100.0, provider_ts_ms="garbage")
        self.assertIsNone(cap["as_of"])
        self.assertEqual(cap["as_of_source"], "provider_ts_absent")

    def test_no_wall_clock_two_builds_byte_identical(self):
        # The candidate byte-pin (test_lifecycle_fail_closed_route) forbids any
        # wall-clock in the capture. Two identical-input builds must be equal.
        a = build_scan_spot_capture(100.0, provider_ts_ms=1784548800000)
        b = build_scan_spot_capture(100.0, provider_ts_ms=1784548800000)
        self.assertEqual(a, b)
        # and with no provider ts (the determinism-fixture case) still equal.
        self.assertEqual(build_scan_spot_capture(100.0),
                         build_scan_spot_capture(100.0))

    def test_json_serializable(self):
        json.dumps(build_scan_spot_capture(100.0, provider_ts_ms=1784548800000))


# ── 2. carrier: build_midday_order_json rides the capture, non-decisionally ──
def _cand(scan_spot="default"):
    c = {
        "symbol": "SPY",
        "strategy": "LONG_CALL_DEBIT_SPREAD",
        "strategy_key": "long_call_debit_spread",
        "suggested_entry": 1.50,
        "legs": [
            {"symbol": "O:SPY260116C00500000", "side": "buy",
             "bid": 3.00, "ask": 3.10, "mid": 3.05},
            {"symbol": "O:SPY260116C00510000", "side": "sell",
             "bid": 1.00, "ask": 1.10, "mid": 1.05},
        ],
    }
    if scan_spot == "default":
        scan_spot = build_scan_spot_capture(512.34, provider_ts_ms=1784548800000)
    if scan_spot is not None:
        c["scan_underlying_spot"] = scan_spot
    return c


_DECISION_KEYS = ("order_type", "contracts", "limit_price", "legs",
                  "underlying", "strategy")


class TestBuildMiddayOrderJsonCarrier(unittest.TestCase):
    def test_scan_spot_rides_order_json_top_level(self):
        oj = build_midday_order_json(_cand(), 2)
        self.assertIn("scan_underlying_spot", oj)
        self.assertEqual(oj["scan_underlying_spot"]["value"], 512.34)
        self.assertEqual(oj["scan_underlying_spot"]["source"], _SCAN_SPOT_SOURCE)
        # It is a TOP-LEVEL key — never inside legs (so the fingerprint is safe).
        self.assertTrue(all("scan_underlying_spot" not in leg for leg in oj["legs"]))

    def test_candidate_without_capture_rides_as_none(self):
        oj = build_midday_order_json(_cand(scan_spot=None), 2)
        self.assertIn("scan_underlying_spot", oj)
        self.assertIsNone(oj["scan_underlying_spot"])

    def test_fingerprint_byte_identical_with_and_without_capture(self):
        oj_with = build_midday_order_json(_cand(), 2)
        oj_without = build_midday_order_json(_cand(scan_spot=None), 2)
        # compute_legs_fingerprint hashes legs only → dedup/idempotency unchanged.
        self.assertEqual(compute_legs_fingerprint(oj_with),
                         compute_legs_fingerprint(oj_without))

    def test_decision_fields_byte_identical_with_and_without_capture(self):
        oj_with = build_midday_order_json(_cand(), 2)
        oj_without = build_midday_order_json(_cand(scan_spot=None), 2)
        proj_with = {k: oj_with.get(k) for k in _DECISION_KEYS}
        proj_without = {k: oj_without.get(k) for k in _DECISION_KEYS}
        self.assertEqual(json.dumps(proj_with, sort_keys=True, default=str),
                         json.dumps(proj_without, sort_keys=True, default=str))

    def test_a_different_scan_spot_never_changes_a_decision_field(self):
        # Same structure, wildly different spot → the decision projection is
        # untouched (observe-only): the value rides, it never steers.
        oj_a = build_midday_order_json(
            _cand(build_scan_spot_capture(10.0)), 2)
        oj_b = build_midday_order_json(
            _cand(build_scan_spot_capture(9999.0)), 2)
        self.assertEqual({k: oj_a.get(k) for k in _DECISION_KEYS},
                         {k: oj_b.get(k) for k in _DECISION_KEYS})
        self.assertNotEqual(oj_a["scan_underlying_spot"]["value"],
                            oj_b["scan_underlying_spot"]["value"])


# ── 3. full production route: reaches the PERSISTED suggestion, non-decisional
from packages.quantum.tests.test_prerejection_fork_e19 import FakeSupabase  # noqa: E402
from packages.quantum.tests.test_prerejection_full_route_e19 import (  # noqa: E402
    _scanner_candidate,
)
from packages.quantum.tests.test_candidate_disposition_route import (  # noqa: E402
    _RouteBase,
)

# Decision-relevant projection of a persisted trade_suggestions row (everything
# a downstream decision reads) — deliberately EXCLUDES scan_underlying_spot, the
# observe-only rider whose whole job is to be present without steering.
_SUGG_DECISION_KEYS = (
    "ticker", "strategy", "status", "blocked_reason", "ev", "ev_raw",
    "risk_adjusted_ev", "legs_fingerprint",
)


class TestFullRouteScanSpotThreaded(_RouteBase):
    def _cand_with_capture(self):
        c = _scanner_candidate()
        c["scan_underlying_spot"] = build_scan_spot_capture(
            27.11, provider_ts_ms=1784548800000)
        return c

    def _sofi_source_row(self, client):
        # The source suggestion (cohort_name None) — persisted even when the
        # candidate is rank_blocked (edge below minimum), so order_json exists.
        return [r for r in client.tables["trade_suggestions"]
                if r.get("ticker") == "SOFI" and r.get("cohort_name") is None][0]

    def test_capture_reaches_persisted_suggestion_order_json(self):
        client = FakeSupabase()
        self._seed(client)
        result = self._drive(client, [self._cand_with_capture()], cal_blob=None)
        self.assertTrue(result["ok"], result.get("notes"))
        oj = self._sofi_source_row(client)["order_json"]
        # The scanner's scan-time spot rode the WHOLE cycle into the persisted
        # suggestion order_json — the honest carrier the stage seam will read.
        self.assertEqual(oj["scan_underlying_spot"]["value"], 27.11)
        self.assertEqual(oj["scan_underlying_spot"]["source"], _SCAN_SPOT_SOURCE)
        self.assertEqual(oj["scan_underlying_spot"]["as_of_source"],
                         "provider_quote_ts")

    def _decision_projection(self, client):
        rows = client.tables.get("trade_suggestions", [])
        return sorted(
            (tuple(r.get(k) for k in _SUGG_DECISION_KEYS)
             + (str(r.get("order_json", {}).get("legs")),
                r.get("order_json", {}).get("contracts"),
                r.get("order_json", {}).get("limit_price"))
             for r in rows),
            key=lambda t: tuple(str(x) for x in t),
        )

    def test_capture_presence_does_not_change_the_decision(self):
        """#1265-style observe-only proof: the persisted trade_suggestions
        decision projection is byte-identical whether or not the candidate
        carries the scan-time spot capture (only scan_underlying_spot differs)."""
        client_with = FakeSupabase()
        self._seed(client_with)
        res_with = self._drive(client_with, [self._cand_with_capture()],
                               cal_blob=None)
        self.assertTrue(res_with["ok"], res_with.get("notes"))

        client_without = FakeSupabase()
        self._seed(client_without)
        res_without = self._drive(client_without, [_scanner_candidate()],
                                  cal_blob=None)
        self.assertTrue(res_without["ok"], res_without.get("notes"))

        self.assertEqual(self._decision_projection(client_with),
                         self._decision_projection(client_without))
        # And the capture only carries a value on the with-capture run.
        self.assertEqual(
            self._sofi_source_row(client_with)["order_json"]
            ["scan_underlying_spot"]["value"], 27.11)
        self.assertIsNone(
            self._sofi_source_row(client_without)["order_json"]
            ["scan_underlying_spot"])


if __name__ == "__main__":
    unittest.main()
