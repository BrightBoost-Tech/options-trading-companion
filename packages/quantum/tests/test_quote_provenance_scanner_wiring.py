"""Scanner spread-gate wiring proof for the Lane 4C provenance recorder.

Drives the REAL ``scan_for_opportunities`` (real process_symbol, real
spread gate, real RejectionStats) with stubs only at genuine data
boundaries — the same harness ``test_funnel_strategy_attribution`` uses.
Assertions run on the DURABLE ``option_quote_provenance`` insert payloads
the route flushed, never on recorder internals.

Proves:
1. A spread-REJECTED leg set persists provenance with verdict + threshold
   + basis + per-leg quotes + linkage — ALWAYS (immune to sampling).
2. A gate-PASSED leg set records the same evidence (sampled).
3. OBSERVE-ONLY: scan candidates and rejection histograms are identical
   with the recorder enabled and disabled, and no provenance rows are
   written when disabled.
"""

import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from packages.quantum.services.quote_provenance import TABLE_NAME
from packages.quantum.tests.test_funnel_strategy_attribution import (
    SYMBOL,
    FakeSupabase,
    _fake_regime,
    _fake_truth_layer,
    _run_scan,
    _wide_spread_chain,
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


def _tight_spread_chain():
    """Same shape as _wide_spread_chain but liquid: combo spread 0.08 on
    a 1.00 debit → 8% < the 10% NORMAL threshold → gate PASSES."""
    expiry = (datetime.now().date() + timedelta(days=35)).isoformat()

    def contract(strike, delta, bid, ask):
        mid = round((bid + ask) / 2.0, 4)
        return {
            "contract": f"{SYMBOL}{int(strike)}C",
            "strike": strike,
            "expiry": expiry,
            "type": "call",
            "greeks": {
                "delta": delta, "gamma": 0.02, "vega": 0.10, "theta": -0.05,
            },
            "quote": {"bid": bid, "ask": ask, "mid": mid, "last": mid},
        }

    return [
        contract(100.0, 0.55, 3.00, 3.04),
        contract(105.0, 0.30, 2.00, 2.04),
    ]


def _prov_rows(fake):
    flat = []
    for batch in fake.inserted[TABLE_NAME]:
        if isinstance(batch, list):
            flat.extend(batch)
        else:
            flat.append(batch)
    return flat


class TestSpreadGateRejectionProvenance(unittest.TestCase):
    """Wide chain → real gate rejects → durable leg-set row, immune to
    sampling (QUOTE_PROVENANCE_SAMPLE_N=1000 would sample out anything
    that is not in an always-persist class)."""

    @classmethod
    def setUpClass(cls):
        cls.fake = FakeSupabase(lifecycle_rows=list(_LIFECYCLE))
        cls.candidates, cls.rej_stats = _run_scan(
            cls.fake,
            truth=_fake_truth_layer(
                closes_profile="rising", chain=_wide_spread_chain()),
            regime=_fake_regime(iv_rank=45.0),
            selector=_selector(),
            env={"QUOTE_PROVENANCE_SAMPLE_N": "1000"},
        )

    def test_route_reached_the_gate(self):
        d = self.rej_stats.to_dict()
        self.assertNotIn("processing_error", d["rejection_counts"],
                         d["rejection_counts"])
        self.assertIn("spread_too_wide_real", d["rejection_counts"])
        self.assertEqual(self.candidates, [])

    def test_rejected_leg_set_persisted_with_verdict_and_basis(self):
        rows = _prov_rows(self.fake)
        leg_sets = [r for r in rows if r.get("record_type") == "leg_set"]
        self.assertEqual(len(leg_sets), 1, rows)
        row = leg_sets[0]
        self.assertEqual(row["verdict"], "rejected")
        self.assertEqual(row["reject_reason"], "spread_too_wide_real")
        self.assertEqual(row["boundary"], "spread_gate")
        # Threshold the gate ACTUALLY applied (NORMAL regime → 0.10), and
        # the spread value must be the GATE'S own number — cross-checked
        # against the spread_debug the route persisted to
        # suggestion_rejections in the same cycle (never a hand-derived
        # figure).
        self.assertAlmostEqual(row["threshold"], 0.10, places=6)
        rej = [r for r in self.fake.rejection_rows
               if r["reason"] == "spread_too_wide_real"][0]
        debug = rej["spread_debug"]["spread_debug"]
        self.assertAlmostEqual(row["option_spread_pct"],
                               debug["option_spread_pct"], places=4)
        self.assertGreater(row["option_spread_pct"], row["threshold"])
        basis = row["spread_basis"]
        self.assertEqual(basis["denominator_basis"], "entry_cost")
        self.assertEqual(basis["combo_source"], "cost_range")
        self.assertAlmostEqual(basis["combo_width_share"],
                               debug["combo_width_share"], places=4)
        self.assertAlmostEqual(basis["entry_cost_share"],
                               debug["entry_cost_share"], places=4)
        # Basis math self-consistent with the gate formula (debit spread:
        # combo / entry_cost).
        self.assertAlmostEqual(
            row["option_spread_pct"],
            basis["combo_width_share"] / basis["entry_cost_share"],
            places=4)
        # Per-leg quote evidence rode along.
        self.assertEqual(len(row["legs"]), 2)
        for leg in row["legs"]:
            self.assertIsNotNone(leg["bid"])
            self.assertIsNotNone(leg["ask"])
        self.assertFalse(row["selected"])
        self.assertFalse(row["sampled"])   # always-persist class
        self.assertTrue(row["leg_fingerprint"])

    def test_linkage_matches_suggestion_rejections(self):
        """(symbol, strategy_key, cycle_date) joins the same cycle's
        suggestion_rejections row — the identity linkage contract."""
        rows = _prov_rows(self.fake)
        row = [r for r in rows if r.get("record_type") == "leg_set"][0]
        self.assertEqual(row["symbol"], SYMBOL)
        self.assertEqual(row["strategy_key"], "long_call_debit_spread")
        rej = [r for r in self.fake.rejection_rows
               if r["reason"] == "spread_too_wide_real"][0]
        self.assertEqual(row["symbol"], rej["symbol"])
        self.assertEqual(row["cycle_date"], rej["cycle_date"])


class TestSpreadGatePassProvenance(unittest.TestCase):
    """Tight chain → gate PASSES → a passed leg-set row is recorded
    (persisted here because SAMPLE_N=1)."""

    @classmethod
    def setUpClass(cls):
        cls.fake = FakeSupabase(lifecycle_rows=list(_LIFECYCLE))
        cls.candidates, cls.rej_stats = _run_scan(
            cls.fake,
            truth=_fake_truth_layer(
                closes_profile="rising", chain=_tight_spread_chain()),
            regime=_fake_regime(iv_rank=45.0),
            selector=_selector(),
            env={"QUOTE_PROVENANCE_SAMPLE_N": "1"},
        )

    def test_gate_did_not_reject_on_spread(self):
        d = self.rej_stats.to_dict()
        self.assertNotIn("processing_error", d["rejection_counts"],
                         d["rejection_counts"])
        for reason in ("spread_too_wide", "spread_too_wide_real",
                       "entry_cost_too_low"):
            self.assertNotIn(reason, d["rejection_counts"])

    def test_passed_leg_set_recorded_with_threshold_and_basis(self):
        rows = _prov_rows(self.fake)
        passed = [r for r in rows
                  if r.get("record_type") == "leg_set"
                  and r.get("verdict") == "passed"]
        self.assertEqual(len(passed), 1, rows)
        row = passed[0]
        self.assertIsNone(row["reject_reason"])
        self.assertAlmostEqual(row["threshold"], 0.10, places=6)
        self.assertAlmostEqual(row["option_spread_pct"], 0.08, places=2)
        self.assertEqual(row["spread_basis"]["denominator_basis"],
                         "entry_cost")
        self.assertEqual(len(row["legs"]), 2)
        # If the candidate emitted, the selected stamp must agree with the
        # scan output; either way the flag is present and boolean.
        emitted = any(c.get("symbol") == SYMBOL for c in self.candidates)
        self.assertEqual(bool(row["selected"]), emitted)


class TestBehaviorImmutability(unittest.TestCase):
    """The recorder must change NOTHING: candidates and rejection
    histograms byte-identical with provenance on vs off; zero provenance
    rows when off."""

    def _scan(self, enabled):
        fake = FakeSupabase(lifecycle_rows=list(_LIFECYCLE))
        candidates, rej_stats = _run_scan(
            fake,
            truth=_fake_truth_layer(
                closes_profile="rising", chain=_wide_spread_chain()),
            regime=_fake_regime(iv_rank=45.0),
            selector=_selector(),
            env={"QUOTE_PROVENANCE_ENABLED": "1" if enabled else "0"},
        )
        return fake, candidates, rej_stats.to_dict()

    def test_scan_verdicts_identical_on_and_off(self):
        fake_on, cands_on, stats_on = self._scan(enabled=True)
        fake_off, cands_off, stats_off = self._scan(enabled=False)

        self.assertEqual(cands_on, cands_off)
        self.assertEqual(stats_on["rejection_counts"],
                         stats_off["rejection_counts"])
        self.assertEqual(
            stats_on["rejection_counts_by_strategy_and_reason"],
            stats_off["rejection_counts_by_strategy_and_reason"])
        self.assertEqual(stats_on["emission_counts_by_strategy"],
                         stats_off["emission_counts_by_strategy"])
        # The rejection rows of record are unchanged either way.
        self.assertEqual(
            [(r["symbol"], r["reason"]) for r in fake_on.rejection_rows],
            [(r["symbol"], r["reason"]) for r in fake_off.rejection_rows])

        # ON wrote provenance; OFF wrote none.
        self.assertGreater(len(_prov_rows(fake_on)), 0)
        self.assertEqual(_prov_rows(fake_off), [])


if __name__ == "__main__":
    unittest.main()
