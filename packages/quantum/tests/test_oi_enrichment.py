"""Unit coverage for the B3 exact-leg OI enrichment service
(``packages/quantum/services/oi_enrichment.py``) — DRAFT / observe-only.

Pins the H9 contract of the enrichment overlay:
  * OI present  -> threaded with source + observation date + retrieval known-at;
  * OI absent   -> typed unavailable (a miss/error/rate-limit is named, never a
                   fabricated value);
  * OI zero     -> a REAL value, preserved;
  * available OI is NEVER overwritten;
  * the base map is NEVER mutated;
  * a whole-universe fan-out is impossible (hard per-call cap + rate budget);
  * DEFAULT-OFF: the convenience entrypoint is a byte-identical no-op with zero
    provider calls unless OI_ENRICHMENT_ENABLED is explicitly truthy.
Fetchers never hit the network here — they are exercised with fake payloads.
"""

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from packages.quantum.services.oi_enrichment import (
    OIRecord,
    RateLimiter,
    alpaca_contracts_oi_fetcher,
    enrich_leg_oi_by_contract,
    enrich_selected_legs,
    is_oi_enrichment_enabled,
    polygon_oi_fetcher,
)


_FIXED_NOW = lambda: datetime(2026, 7, 20, 21, 0, 0, tzinfo=timezone.utc)


def _legs(*contracts):
    return [{"symbol": c, "side": "buy"} for c in contracts]


def _pass_all_limiter():
    lim = RateLimiter(max_calls_per_window=1000, window_seconds=60,
                      min_interval_ms=0)
    return lim


# --- flag -------------------------------------------------------------------
class TestFlag(unittest.TestCase):
    def test_default_off(self):
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("OI_ENRICHMENT_ENABLED", None)
            self.assertFalse(is_oi_enrichment_enabled())

    def test_truthy_variants_on(self):
        for v in ("1", "true", "TRUE", "yes", "on", "  On  "):
            with patch.dict("os.environ", {"OI_ENRICHMENT_ENABLED": v}):
                self.assertTrue(is_oi_enrichment_enabled(), v)

    def test_falsy_variants_off(self):
        for v in ("0", "false", "no", "off", "", "  ", "nope"):
            with patch.dict("os.environ", {"OI_ENRICHMENT_ENABLED": v}):
                self.assertFalse(is_oi_enrichment_enabled(), v)


# --- rate limiter -----------------------------------------------------------
class TestRateLimiter(unittest.TestCase):
    def test_window_budget_enforced(self):
        lim = RateLimiter(max_calls_per_window=2, window_seconds=60,
                          min_interval_ms=0, clock=lambda: 100.0)
        self.assertTrue(lim.allow())
        self.assertTrue(lim.allow())
        self.assertFalse(lim.allow())   # budget exhausted

    def test_window_evicts_old_calls(self):
        t = {"now": 0.0}
        lim = RateLimiter(max_calls_per_window=1, window_seconds=10,
                          min_interval_ms=0, clock=lambda: t["now"])
        self.assertTrue(lim.allow())
        self.assertFalse(lim.allow())
        t["now"] = 11.0                 # first call now outside the window
        self.assertTrue(lim.allow())

    def test_min_interval_enforced(self):
        t = {"now": 0.0}
        lim = RateLimiter(max_calls_per_window=1000, window_seconds=60,
                          min_interval_ms=500, clock=lambda: t["now"])
        self.assertTrue(lim.allow())
        t["now"] = 0.2                  # < 0.5s
        self.assertFalse(lim.allow())
        t["now"] = 0.6
        self.assertTrue(lim.allow())


# --- core overlay logic -----------------------------------------------------
class TestEnrichOverlay(unittest.TestCase):
    def test_available_oi_threaded_with_provenance(self):
        def fetch(c):
            return OIRecord(contract=c, oi=1500, source="alpaca_contracts",
                            observation_date="2026-07-18",
                            date_field="open_interest_date", status="ok")
        base = {"AAA100C": {"oi": None, "source": "alpaca"}}
        out = enrich_leg_oi_by_contract(
            _legs("AAA100C"), base, fetch_fn=fetch,
            limiter=_pass_all_limiter(), now_fn=_FIXED_NOW)
        e = out["AAA100C"]
        self.assertEqual(e["oi"], 1500)
        self.assertEqual(e["source"], "alpaca_contracts")
        self.assertEqual(e["oi_observation_date"], "2026-07-18")
        self.assertEqual(e["oi_date_field"], "open_interest_date")
        self.assertEqual(e["oi_retrieved_at"], _FIXED_NOW().isoformat())
        self.assertEqual(e["oi_enrichment_status"], "ok")

    def test_zero_oi_is_a_real_value(self):
        def fetch(c):
            return OIRecord(contract=c, oi=0, source="polygon_snapshot",
                            status="ok")
        out = enrich_leg_oi_by_contract(
            _legs("AAA100C"), {}, fetch_fn=fetch,
            limiter=_pass_all_limiter(), now_fn=_FIXED_NOW)
        self.assertEqual(out["AAA100C"]["oi"], 0)          # not None
        self.assertEqual(out["AAA100C"]["source"], "polygon_snapshot")

    def test_miss_stays_typed_unavailable_not_zero(self):
        def fetch(c):
            return OIRecord(contract=c, source="polygon_snapshot", status="miss")
        out = enrich_leg_oi_by_contract(
            _legs("AAA100C"), {}, fetch_fn=fetch,
            limiter=_pass_all_limiter(), now_fn=_FIXED_NOW)
        e = out["AAA100C"]
        self.assertIsNone(e["oi"])                          # never fabricated 0
        self.assertIn("oi_enrich_miss", e["source"])
        self.assertEqual(e["oi_enrichment_status"], "miss")

    def test_error_stays_typed_unavailable(self):
        def fetch(c):
            raise RuntimeError("boom")
        out = enrich_leg_oi_by_contract(
            _legs("AAA100C"), {}, fetch_fn=fetch,
            limiter=_pass_all_limiter(), now_fn=_FIXED_NOW)
        e = out["AAA100C"]
        self.assertIsNone(e["oi"])
        self.assertIn("oi_enrich_error", e["source"])
        self.assertEqual(e["oi_enrichment_status"], "error")

    def test_rate_limited_is_typed_and_no_fetch(self):
        calls = {"n": 0}

        def fetch(c):
            calls["n"] += 1
            return OIRecord(contract=c, oi=5, status="ok")
        deny = RateLimiter(max_calls_per_window=0, window_seconds=60,
                           min_interval_ms=0)
        out = enrich_leg_oi_by_contract(
            _legs("AAA100C"), {}, fetch_fn=fetch, limiter=deny,
            now_fn=_FIXED_NOW)
        self.assertEqual(calls["n"], 0)                     # never called
        self.assertIsNone(out["AAA100C"]["oi"])
        self.assertEqual(out["AAA100C"]["oi_enrichment_status"], "rate_limited")

    def test_available_oi_never_overwritten(self):
        def fetch(c):
            raise AssertionError("must not fetch an already-available leg")
        base = {"AAA100C": {"oi": 900, "source": "alpaca"}}
        out = enrich_leg_oi_by_contract(
            _legs("AAA100C"), base, fetch_fn=fetch,
            limiter=_pass_all_limiter(), now_fn=_FIXED_NOW)
        self.assertEqual(out["AAA100C"]["oi"], 900)
        self.assertEqual(out["AAA100C"]["source"], "alpaca")

    def test_base_map_not_mutated(self):
        def fetch(c):
            return OIRecord(contract=c, oi=42, source="polygon_snapshot",
                            status="ok")
        base = {"AAA100C": {"oi": None, "source": "alpaca"}}
        out = enrich_leg_oi_by_contract(
            _legs("AAA100C"), base, fetch_fn=fetch,
            limiter=_pass_all_limiter(), now_fn=_FIXED_NOW)
        self.assertIsNone(base["AAA100C"]["oi"])            # base untouched
        self.assertEqual(out["AAA100C"]["oi"], 42)

    def test_hard_cap_bounds_fanout(self):
        seen = []

        def fetch(c):
            seen.append(c)
            return OIRecord(contract=c, oi=1, status="ok")
        legs = _legs("A1C", "A2C", "A3C", "A4C", "A5C")
        enrich_leg_oi_by_contract(
            legs, {}, fetch_fn=fetch, limiter=_pass_all_limiter(),
            max_legs_per_call=2, now_fn=_FIXED_NOW)
        self.assertEqual(len(seen), 2)                      # capped

    def test_dedup_and_bad_legs_skipped(self):
        seen = []

        def fetch(c):
            seen.append(c)
            return OIRecord(contract=c, oi=1, status="ok")
        legs = [{"symbol": "O:AAA100C"}, {"symbol": "AAA100C"},  # same bare
                "not-a-dict", {"no_symbol": 1}]
        out = enrich_leg_oi_by_contract(
            legs, {}, fetch_fn=fetch, limiter=_pass_all_limiter(),
            now_fn=_FIXED_NOW)
        self.assertEqual(seen, ["AAA100C"])                 # deduped, bare
        self.assertIn("AAA100C", out)


# --- convenience entrypoint (default-off) -----------------------------------
class TestEnrichSelectedLegs(unittest.TestCase):
    def test_off_is_noop_same_object(self):
        base = {"AAA100C": {"oi": None}}
        with patch.dict("os.environ", {"OI_ENRICHMENT_ENABLED": "0"}):
            out = enrich_selected_legs(_legs("AAA100C"), base)
        self.assertIs(out, base)                            # byte-identical

    def test_on_but_no_fetcher_is_noop(self):
        base = {"AAA100C": {"oi": None}}
        with patch.dict("os.environ", {"OI_ENRICHMENT_ENABLED": "1"}):
            with patch("packages.quantum.services.oi_enrichment."
                       "make_default_fetcher", return_value=None):
                out = enrich_selected_legs(_legs("AAA100C"), base)
        self.assertIs(out, base)

    def test_on_with_injected_fetcher_enriches(self):
        def fetch(c):
            return OIRecord(contract=c, oi=777, source="alpaca_contracts",
                            observation_date="2026-07-18",
                            date_field="open_interest_date", status="ok")
        base = {"AAA100C": {"oi": None, "source": "alpaca"}}
        with patch.dict("os.environ", {"OI_ENRICHMENT_ENABLED": "1"}):
            out = enrich_selected_legs(
                _legs("AAA100C"), base, fetch_fn=fetch,
                limiter=_pass_all_limiter())
        self.assertEqual(out["AAA100C"]["oi"], 777)
        self.assertIsNot(out, base)


# --- concrete fetchers (fake payloads, no network) --------------------------
class TestPolygonFetcher(unittest.TestCase):
    class _Svc:
        def __init__(self, payload):
            self._p = payload

        def get_option_snapshot(self, contract):
            return self._p

    def test_open_interest_parsed_no_date(self):
        rec = polygon_oi_fetcher(self._Svc({"open_interest": 1234}))("AAA100C")
        self.assertEqual(rec.oi, 1234)
        self.assertEqual(rec.status, "ok")
        self.assertEqual(rec.source, "polygon_snapshot")
        self.assertIsNone(rec.observation_date)             # polygon has no OI date

    def test_zero_open_interest_is_ok(self):
        rec = polygon_oi_fetcher(self._Svc({"open_interest": 0}))("AAA100C")
        self.assertEqual(rec.oi, 0)
        self.assertEqual(rec.status, "ok")

    def test_absent_open_interest_is_miss(self):
        rec = polygon_oi_fetcher(self._Svc({"day": {}}))("AAA100C")
        self.assertIsNone(rec.oi)
        self.assertEqual(rec.status, "miss")

    def test_empty_snapshot_is_miss(self):
        rec = polygon_oi_fetcher(self._Svc({}))("AAA100C")
        self.assertEqual(rec.status, "miss")


class TestAlpacaContractsFetcher(unittest.TestCase):
    class _Resp:
        def __init__(self, status, body):
            self.status_code = status
            self._body = body

        def json(self):
            return self._body

    class _Session:
        def __init__(self, resp):
            self._resp = resp
            self.calls = []

        def get(self, url, headers=None, timeout=None):
            self.calls.append(url)
            return self._resp

    def test_oi_and_date_parsed(self):
        sess = self._Session(self._Resp(
            200, {"open_interest": 5000, "open_interest_date": "2026-07-18"}))
        rec = alpaca_contracts_oi_fetcher(sess, "k", "s")("O:AAA100C")
        self.assertEqual(rec.oi, 5000)
        self.assertEqual(rec.observation_date, "2026-07-18")
        self.assertEqual(rec.date_field, "open_interest_date")
        self.assertEqual(rec.status, "ok")
        # O: prefix stripped in the URL path.
        self.assertTrue(sess.calls[0].endswith("/v2/options/contracts/AAA100C"))

    def test_non_200_is_miss(self):
        sess = self._Session(self._Resp(404, {}))
        rec = alpaca_contracts_oi_fetcher(sess, "k", "s")("AAA100C")
        self.assertEqual(rec.status, "miss")

    def test_absent_oi_is_miss(self):
        sess = self._Session(self._Resp(200, {"symbol": "AAA100C"}))
        rec = alpaca_contracts_oi_fetcher(sess, "k", "s")("AAA100C")
        self.assertEqual(rec.status, "miss")


if __name__ == "__main__":
    unittest.main()
