"""B3 OI-enrichment scanner-wiring proof — end-to-end through the REAL
``scan_for_opportunities`` (real process_symbol, real spread gate).

Root cause (2026-07-20): the Alpaca snapshot carries no OI, so on the natural
Alpaca-primary path every selected leg set's OI-floor counterfactual is
``indeterminate`` (never pass/fail). This proves:

1. DEFAULT-OFF (no enrichment): the gate-PASSED leg-set row's counterfactuals
   are ALL indeterminate (the natural-Monday behavior) — and scan verdicts are
   byte-identical to the plain provenance run.
2. ENRICHMENT ON with an injected (fake) secondary-provider fetcher: the SAME
   passed row now carries AVAILABLE exact-leg OI + real pass/fail
   counterfactuals, with ``oi_source`` naming the enrichment provider — and the
   scan candidates / rejection histograms are STILL byte-identical (OI feeds no
   decision).

The network is never hit: only ``make_default_fetcher`` (the provider boundary)
is monkeypatched; the real enrichment logic (cap, limiter, merge, coerce) runs.
"""

import unittest
from unittest.mock import patch

from packages.quantum.services.oi_enrichment import OIRecord, RateLimiter
from packages.quantum.services.quote_provenance import TABLE_NAME
from packages.quantum.tests.test_funnel_strategy_attribution import (
    SYMBOL,
    FakeSupabase,
    _fake_regime,
    _fake_truth_layer,
    _run_scan,
)
from packages.quantum.tests.test_quote_provenance_scanner_wiring import (
    _LIFECYCLE,
    _selector,
    _tight_spread_chain,
)


def _prov_rows(fake):
    flat = []
    for batch in fake.inserted[TABLE_NAME]:
        flat.extend(batch if isinstance(batch, list) else [batch])
    return flat


def _passed_leg_set(fake):
    passed = [r for r in _prov_rows(fake)
              if r.get("record_type") == "leg_set" and r.get("verdict") == "passed"]
    return passed


# Fake secondary provider: supplies OI keyed on the exact leg contract, with a
# genuine observation date (the alpaca-contracts-shaped source).
def _fake_fetcher():
    def _fetch(contract):
        oi = 1500 if "100" in contract else 300
        return OIRecord(contract=contract, oi=oi, source="alpaca_contracts",
                        observation_date="2026-07-18",
                        date_field="open_interest_date", status="ok")
    return _fetch


class TestEnrichmentOffIsNaturalMonday(unittest.TestCase):
    """Flag OFF → the passed row is all-indeterminate (the observed symptom)."""

    @classmethod
    def setUpClass(cls):
        cls.fake = FakeSupabase(lifecycle_rows=list(_LIFECYCLE))
        cls.candidates, cls.rej_stats = _run_scan(
            cls.fake,
            truth=_fake_truth_layer(closes_profile="rising",
                                    chain=_tight_spread_chain()),
            regime=_fake_regime(iv_rank=45.0),
            selector=_selector(),
            env={"QUOTE_PROVENANCE_SAMPLE_N": "1",
                 "OI_ENRICHMENT_ENABLED": "0"},
        )

    def test_passed_row_all_indeterminate(self):
        passed = _passed_leg_set(self.fake)
        self.assertEqual(len(passed), 1, _prov_rows(self.fake))
        oi = passed[0]["details"]["oi"]
        self.assertTrue(oi["any_oi_unavailable"])
        self.assertEqual(oi["legs_oi_available"], 0)
        cf = {c["verdict"] for c in oi["counterfactuals"]}
        self.assertEqual(cf, {"indeterminate"})


class TestEnrichmentOnThreadsRealOI(unittest.TestCase):
    """Flag ON + injected fetcher → the SAME passed row carries available OI +
    real pass/fail counterfactuals, and scan decisions are unchanged."""

    def _scan(self, enabled):
        fake = FakeSupabase(lifecycle_rows=list(_LIFECYCLE))
        # Fresh limiter each run so the module-global budget never interferes.
        with patch("packages.quantum.services.oi_enrichment.make_default_fetcher",
                   return_value=_fake_fetcher()), \
             patch("packages.quantum.services.oi_enrichment._global_limiter",
                   return_value=RateLimiter(max_calls_per_window=1000,
                                            window_seconds=60, min_interval_ms=0)):
            candidates, rej_stats = _run_scan(
                fake,
                truth=_fake_truth_layer(closes_profile="rising",
                                        chain=_tight_spread_chain()),
                regime=_fake_regime(iv_rank=45.0),
                selector=_selector(),
                env={"QUOTE_PROVENANCE_SAMPLE_N": "1",
                     "OI_ENRICHMENT_ENABLED": "1" if enabled else "0"},
            )
        return fake, candidates, rej_stats.to_dict()

    def test_enriched_oi_and_counterfactuals(self):
        fake, _cands, _stats = self._scan(enabled=True)
        passed = _passed_leg_set(fake)
        self.assertEqual(len(passed), 1, _prov_rows(fake))
        oi = passed[0]["details"]["oi"]
        # OI is now AVAILABLE on both legs — the enrichment filled the gap.
        self.assertFalse(oi["any_oi_unavailable"])
        self.assertEqual(oi["legs_oi_available"], 2)
        self.assertEqual(oi["min_leg_oi"], 300)
        # Real pass/fail (min leg OI 300 passes 100/250, fails 500/1000) — no
        # longer indeterminate.
        cf = {c["floor"]: c["verdict"] for c in oi["counterfactuals"]}
        self.assertEqual(cf[100], "pass")
        self.assertEqual(cf[250], "pass")
        self.assertEqual(cf[500], "fail")
        self.assertEqual(cf[1000], "fail")
        # Provenance names the enrichment provider + genuine observation date.
        leg = oi["legs"][0]
        self.assertEqual(leg["oi_source"], "alpaca_contracts")
        self.assertEqual(leg["oi_observation_date"], "2026-07-18")
        self.assertEqual(leg["oi_freshness"], "fresh")

    def test_scan_decisions_byte_identical_on_vs_off(self):
        fake_on, cands_on, stats_on = self._scan(enabled=True)
        fake_off, cands_off, stats_off = self._scan(enabled=False)
        self.assertEqual(cands_on, cands_off)
        self.assertEqual(stats_on["rejection_counts"], stats_off["rejection_counts"])
        self.assertEqual(stats_on["emission_counts_by_strategy"],
                         stats_off["emission_counts_by_strategy"])
        # OFF captured indeterminate; ON captured available — only the
        # OBSERVATION differs, never the decision.
        off_oi = _passed_leg_set(fake_off)[0]["details"]["oi"]
        on_oi = _passed_leg_set(fake_on)[0]["details"]["oi"]
        self.assertTrue(off_oi["any_oi_unavailable"])
        self.assertFalse(on_oi["any_oi_unavailable"])


if __name__ == "__main__":
    unittest.main()
