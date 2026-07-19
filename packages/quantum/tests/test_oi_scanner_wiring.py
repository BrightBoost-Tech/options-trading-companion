"""Lane H scanner-wiring proof — exact-leg OI reaches the durable row, and
adding OI to the chain changes NO scan decision (byte-pin).

Drives the REAL ``scan_for_opportunities`` (real process_symbol, real spread
gate) with the shared funnel harness. Assertions run on the DURABLE
``option_quote_provenance`` insert payloads the route flushed
(``details->oi``), never recorder internals.

Proves:
1. A chain carrying per-contract OI flows exact-leg into the persisted
   leg-set row: each leg carries its own OI + the hypothetical-floor
   counterfactuals are computed with the correct pass/fail.
2. OBSERVE-ONLY: scan candidates and rejection histograms are byte-identical
   whether the chain carries OI or not — OI never gates, ranks, or sizes.
Plus unit coverage of the ``_build_oi_by_contract`` map (0-vs-absent, O:
prefix, legacy flat chain, garbage entries).
"""

import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from packages.quantum.options_scanner import _build_oi_by_contract
from packages.quantum.services.quote_provenance import TABLE_NAME
from packages.quantum.tests.test_funnel_strategy_attribution import (
    SYMBOL,
    FakeSupabase,
    _fake_regime,
    _fake_truth_layer,
    _run_scan,
)

_LIFECYCLE = [
    {"strategy_name": "LONG_CALL_DEBIT_SPREAD", "current_state": "live_full"},
    {"strategy_name": "SHORT_PUT_CREDIT_SPREAD", "current_state": "live_full"},
]


def _selector():
    sel = MagicMock()
    sel.get_candidates.return_value = [{
        "strategy": "LONG_CALL_DEBIT_SPREAD",
        "legs": [
            {"side": "buy", "type": "call", "delta_target": 0.55},
            {"side": "sell", "type": "call", "delta_target": 0.30},
        ],
    }]
    return sel


def _wide_chain(oi_by_strike=None):
    """Wide-spread chain (→ real gate rejects spread_too_wide_real). When
    ``oi_by_strike`` is given, each contract carries its exact OI/volume/source
    (nested TruthLayer schema — top-level ``oi``)."""
    expiry = (datetime.now().date() + timedelta(days=35)).isoformat()

    def contract(strike, delta, bid, ask):
        mid = round((bid + ask) / 2.0, 4)
        c = {
            "contract": f"{SYMBOL}{int(strike)}C",
            "strike": strike,
            "expiry": expiry,
            "type": "call",
            "greeks": {"delta": delta, "gamma": 0.02, "vega": 0.10, "theta": -0.05},
            "quote": {"bid": bid, "ask": ask, "mid": mid, "last": mid},
        }
        if oi_by_strike is not None and strike in oi_by_strike:
            oi, vol = oi_by_strike[strike]
            c["oi"] = oi
            c["volume"] = vol
            c["source"] = "alpaca"
        return c

    return [contract(100.0, 0.55, 3.00, 3.50), contract(105.0, 0.30, 1.00, 1.50)]


def _prov_rows(fake):
    flat = []
    for batch in fake.inserted[TABLE_NAME]:
        if isinstance(batch, list):
            flat.extend(batch)
        else:
            flat.append(batch)
    return flat


class TestOIReachesDurableRow(unittest.TestCase):
    """Chain with per-contract OI → the rejected leg-set row carries exact-leg
    OI + write-time counterfactuals."""

    @classmethod
    def setUpClass(cls):
        cls.fake = FakeSupabase(lifecycle_rows=list(_LIFECYCLE))
        chain = _wide_chain(oi_by_strike={100.0: (1500, 40), 105.0: (300, 10)})
        cls.candidates, cls.rej_stats = _run_scan(
            cls.fake,
            truth=_fake_truth_layer(closes_profile="rising", chain=chain),
            regime=_fake_regime(iv_rank=45.0),
            selector=_selector(),
            env={"QUOTE_PROVENANCE_SAMPLE_N": "1000"},   # only always-persist survive
        )

    def test_route_reached_the_gate_and_rejected(self):
        d = self.rej_stats.to_dict()
        self.assertNotIn("processing_error", d["rejection_counts"],
                         d["rejection_counts"])
        self.assertIn("spread_too_wide_real", d["rejection_counts"])

    def test_leg_set_row_carries_exact_leg_oi(self):
        leg_sets = [r for r in _prov_rows(self.fake)
                    if r.get("record_type") == "leg_set"]
        self.assertEqual(len(leg_sets), 1, _prov_rows(self.fake))
        row = leg_sets[0]
        self.assertEqual(row["verdict"], "rejected")
        # details->oi present with the per-leg exact OI.
        oi = row["details"]["oi"]
        self.assertEqual(oi["legs_total"], 2)
        self.assertEqual(oi["legs_oi_available"], 2)
        self.assertFalse(oi["any_oi_unavailable"])
        self.assertEqual(oi["min_leg_oi"], 300)
        by_contract = {l["contract"]: l["oi"] for l in oi["legs"]}
        self.assertEqual(by_contract[f"{SYMBOL}100C"], 1500)
        self.assertEqual(by_contract[f"{SYMBOL}105C"], 300)
        # Per-leg OI also rode on the leg quote rows (exact-leg linkage).
        leg_rows = {l["contract"]: l for l in row["legs"]}
        self.assertEqual(leg_rows[f"{SYMBOL}100C"]["oi"], 1500)
        self.assertTrue(leg_rows[f"{SYMBOL}100C"]["oi_available"])
        self.assertEqual(leg_rows[f"{SYMBOL}105C"]["oi_source"], "alpaca")

    def test_counterfactuals_pass_fail_correct(self):
        row = [r for r in _prov_rows(self.fake)
               if r.get("record_type") == "leg_set"][0]
        cf = {c["floor"]: c["verdict"]
              for c in row["details"]["oi"]["counterfactuals"]}
        # min leg OI = 300: passes 100/250, fails 500/1000.
        self.assertEqual(cf[100], "pass")
        self.assertEqual(cf[250], "pass")
        self.assertEqual(cf[500], "fail")
        self.assertEqual(cf[1000], "fail")


class TestOIIsObserveOnly(unittest.TestCase):
    """Scan decisions must be byte-identical whether the chain carries OI or
    not — OI feeds only the recorder, never a gate/rank/size."""

    def _scan(self, with_oi):
        fake = FakeSupabase(lifecycle_rows=list(_LIFECYCLE))
        chain = _wide_chain(
            oi_by_strike={100.0: (1500, 40), 105.0: (300, 10)} if with_oi else None)
        candidates, rej_stats = _run_scan(
            fake,
            truth=_fake_truth_layer(closes_profile="rising", chain=chain),
            regime=_fake_regime(iv_rank=45.0),
            selector=_selector(),
            env={"QUOTE_PROVENANCE_ENABLED": "1"},
        )
        return fake, candidates, rej_stats.to_dict()

    def test_scan_decisions_identical_with_and_without_oi(self):
        fake_oi, cands_oi, stats_oi = self._scan(with_oi=True)
        fake_no, cands_no, stats_no = self._scan(with_oi=False)

        self.assertEqual(cands_oi, cands_no)
        self.assertEqual(stats_oi["rejection_counts"], stats_no["rejection_counts"])
        self.assertEqual(
            stats_oi["rejection_counts_by_strategy_and_reason"],
            stats_no["rejection_counts_by_strategy_and_reason"])
        self.assertEqual(stats_oi["emission_counts_by_strategy"],
                         stats_no["emission_counts_by_strategy"])
        # Rejection rows of record unchanged either way.
        self.assertEqual(
            [(r["symbol"], r["reason"]) for r in fake_oi.rejection_rows],
            [(r["symbol"], r["reason"]) for r in fake_no.rejection_rows])

        # Both wrote provenance; the OI run captured available OI, the no-OI
        # run captured typed-unavailable — the DECISION is the same, only the
        # OBSERVATION differs.
        row_oi = [r for r in _prov_rows(fake_oi)
                  if r.get("record_type") == "leg_set"][0]
        row_no = [r for r in _prov_rows(fake_no)
                  if r.get("record_type") == "leg_set"][0]
        self.assertFalse(row_oi["details"]["oi"]["any_oi_unavailable"])
        self.assertTrue(row_no["details"]["oi"]["any_oi_unavailable"])
        # And the no-OI counterfactuals are all indeterminate (never fabricated).
        cf_no = {c["verdict"] for c in row_no["details"]["oi"]["counterfactuals"]}
        self.assertEqual(cf_no, {"indeterminate"})


class TestBuildOIByContract(unittest.TestCase):
    def test_nested_chain_preserves_zero_and_value(self):
        chain = [
            {"contract": "O:TEST100C", "oi": 0, "volume": 5, "source": "alpaca"},
            {"contract": "TEST105C", "oi": 742, "volume": 33, "source": "polygon"},
        ]
        m = _build_oi_by_contract(chain)
        # O: prefix stripped for the map key.
        self.assertEqual(m["TEST100C"]["oi"], 0)      # a real value, preserved
        self.assertEqual(m["TEST100C"]["source"], "alpaca")
        self.assertEqual(m["TEST105C"]["oi"], 742)
        self.assertEqual(m["TEST105C"]["volume"], 33)

    def test_absent_oi_key_maps_to_none(self):
        chain = [{"contract": "TEST100C", "volume": 5, "source": "alpaca"}]
        m = _build_oi_by_contract(chain)
        self.assertIsNone(m["TEST100C"]["oi"])

    def test_legacy_flat_chain_has_no_oi(self):
        # Legacy flat Polygon fallback: ticker key, no oi field → None.
        chain = [{"ticker": "TEST100C", "bid": 1.0, "ask": 1.1}]
        m = _build_oi_by_contract(chain)
        self.assertIn("TEST100C", m)
        self.assertIsNone(m["TEST100C"]["oi"])
        self.assertEqual(m["TEST100C"]["source"], "unknown")

    def test_open_interest_and_date_fallbacks(self):
        chain = [{"contract": "TEST100C", "open_interest": 900,
                  "open_interest_date": "2026-07-18"}]
        m = _build_oi_by_contract(chain)
        self.assertEqual(m["TEST100C"]["oi"], 900)
        self.assertEqual(m["TEST100C"]["oi_known_at"], "2026-07-18")

    def test_garbage_entries_skipped_and_fail_soft(self):
        chain = ["not-a-dict", {"no_ticker": 1},
                 {"contract": "TEST100C", "oi": 10}]
        m = _build_oi_by_contract(chain)
        self.assertEqual(set(m), {"TEST100C"})
        self.assertEqual(_build_oi_by_contract(None), {})
        self.assertEqual(_build_oi_by_contract("garbage"), {})


if __name__ == "__main__":
    unittest.main()
