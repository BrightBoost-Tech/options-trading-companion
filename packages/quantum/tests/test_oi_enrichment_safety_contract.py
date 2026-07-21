"""OI enrichment SAFETY CONTRACT — the secondary-provider-call guardrails.

Verifies the safety properties that the sibling suite covers only indirectly:
  P1  default-OFF makes ZERO provider calls (mock provider call count == 0,
      and make_default_fetcher is never even reached);
  P4  a timeout-class exception is typed error (never exception->empty);
  P3  the rolling window budget + min-interval bound the ACTUAL fetches across
      repeated enrich_selected_legs calls (the scanner calls it once per
      selected candidate — the module-global budget must cap the fan-out);
  P5  a REAL existing 0 in the base is preserved AND never re-fetched.
"""
import unittest
from unittest.mock import MagicMock, patch

from packages.quantum.services.oi_enrichment import (
    OIRecord,
    RateLimiter,
    enrich_leg_oi_by_contract,
    enrich_selected_legs,
)


def _legs(*cs):
    return [{"symbol": c, "side": "buy"} for c in cs]


class TestZeroProviderCallsWhenOff(unittest.TestCase):
    def test_off_never_builds_or_calls_provider(self):
        provider = MagicMock(name="make_default_fetcher")
        injected_calls = {"n": 0}

        def counting_fetch(c):
            injected_calls["n"] += 1
            return OIRecord(contract=c, oi=9, status="ok")

        base = {"AAA100C": {"oi": None}}
        with patch.dict("os.environ", {"OI_ENRICHMENT_ENABLED": "0"}):
            with patch("packages.quantum.services.oi_enrichment."
                       "make_default_fetcher", provider):
                out = enrich_selected_legs(
                    _legs("AAA100C"), base, fetch_fn=counting_fetch)
        self.assertIs(out, base)                 # byte-identical no-op
        provider.assert_not_called()             # provider builder never reached
        self.assertEqual(injected_calls["n"], 0)  # zero provider calls


class TestTimeoutTyped(unittest.TestCase):
    def test_timeout_is_typed_error_not_empty(self):
        class FakeTimeout(Exception):
            pass

        def fetch(c):
            raise FakeTimeout("read timed out")

        out = enrich_leg_oi_by_contract(
            _legs("AAA100C"), {}, fetch_fn=fetch,
            limiter=RateLimiter(max_calls_per_window=10, window_seconds=60,
                                min_interval_ms=0))
        e = out["AAA100C"]
        self.assertIsNone(e["oi"])                        # no fabricated value
        self.assertEqual(e["oi_enrichment_status"], "error")
        self.assertIn("oi_enrich_error", e["source"])


class TestBudgetBoundsRepeatedScannerCalls(unittest.TestCase):
    def test_global_window_budget_caps_total_fetches(self):
        seen = []

        def fetch(c):
            seen.append(c)
            return OIRecord(contract=c, oi=1, status="ok")

        # Simulate the scanner selecting 10 distinct candidates (1 leg each) in
        # one scan; the process-global limiter budget is 3.
        shared = RateLimiter(max_calls_per_window=3, window_seconds=60,
                             min_interval_ms=0, clock=lambda: 100.0)
        with patch.dict("os.environ", {"OI_ENRICHMENT_ENABLED": "1"}):
            with patch("packages.quantum.services.oi_enrichment."
                       "make_default_fetcher", return_value=fetch), \
                 patch("packages.quantum.services.oi_enrichment."
                       "_global_limiter", return_value=shared):
                for i in range(10):
                    out = enrich_selected_legs(
                        _legs(f"C{i}00C"), {f"C{i}00C": {"oi": None}})
                    # a rate-limited candidate stays typed-unavailable
                    self.assertIn(out[f"C{i}00C"]["oi_enrichment_status"],
                                  {"ok", "rate_limited"})
        self.assertEqual(len(seen), 3)                    # budget bound the fan-out

    def test_min_interval_bounds_fetches(self):
        t = {"now": 0.0}
        seen = []

        def fetch(c):
            seen.append(c)
            return OIRecord(contract=c, oi=1, status="ok")

        lim = RateLimiter(max_calls_per_window=1000, window_seconds=60,
                          min_interval_ms=1000, clock=lambda: t["now"])
        # First fetch grants; second within the interval is rate-limited.
        enrich_leg_oi_by_contract(_legs("A1C"), {}, fetch_fn=fetch, limiter=lim)
        enrich_leg_oi_by_contract(_legs("A2C"), {}, fetch_fn=fetch, limiter=lim)
        self.assertEqual(seen, ["A1C"])                   # 2nd denied by interval


class TestExistingZeroPreserved(unittest.TestCase):
    def test_existing_real_zero_not_refetched_or_overwritten(self):
        def fetch(c):
            raise AssertionError("must not fetch a leg whose OI is a real 0")

        base = {"AAA100C": {"oi": 0, "source": "polygon"}}
        out = enrich_leg_oi_by_contract(
            _legs("AAA100C"), base, fetch_fn=fetch,
            limiter=RateLimiter(max_calls_per_window=10, window_seconds=60,
                                min_interval_ms=0))
        self.assertEqual(out["AAA100C"]["oi"], 0)         # real 0 preserved
        self.assertEqual(out["AAA100C"]["source"], "polygon")


if __name__ == "__main__":
    unittest.main()
