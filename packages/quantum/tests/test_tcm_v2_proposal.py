"""Unit tests for the TCM v2 routing-aware PROPOSAL (observe-only).

Pins the pure model: routing classification, routing-aware commission
(broker-$0 vs internal/shadow synthetic), the missing-quote H9 abstention on
carried slippage/spread, the commission delta math, and the realized close-join
predicate (mirrors the realized_cost_study broker-routed rule).
"""

import math
import unittest

from packages.quantum.services import tcm_v2_proposal as v2


# frozen-TCM shape at stage: valid quote (spread/slippage present, no fallback)
_CUR_VALID = {
    "expected_spread_cost_usd": 1.50,
    "expected_slippage_usd": 0.08,
    "fill_probability": 0.5,
    "expected_fill_price": 1.50,
    "fees_usd": 0.65,
    "tcm_version": "1.1.0",
    "missing_quote": False,
    "used_fallback": False,
}

# frozen-TCM shape at stage: missing quote → fallback band, flags set
_CUR_MISSING = {
    "expected_spread_cost_usd": 1.50,   # fabricated from the 0.99/1.01 band
    "expected_slippage_usd": 0.08,
    "fill_probability": 0.5,
    "expected_fill_price": 1.50,
    "fees_usd": 0.65,
    "tcm_version": "1.1.0",
    "missing_quote": True,
    "used_fallback": True,
}


class TestClassifyRouting(unittest.TestCase):
    def test_alpaca_live_eligible_is_broker(self):
        self.assertEqual(
            v2.classify_routing("alpaca_live", "live_eligible"), v2.ROUTING_BROKER)
        self.assertEqual(
            v2.classify_routing("alpaca_paper", "live_eligible"), v2.ROUTING_BROKER)

    def test_shadow_only_is_shadow_regardless_of_exec_mode(self):
        self.assertEqual(
            v2.classify_routing("alpaca_paper", "shadow_only"), v2.ROUTING_SHADOW)
        self.assertEqual(
            v2.classify_routing("internal_paper", "shadow_only"), v2.ROUTING_SHADOW)

    def test_internal_paper_is_internal(self):
        self.assertEqual(
            v2.classify_routing("internal_paper", "live_eligible"), v2.ROUTING_INTERNAL)

    def test_unknown_routing_falls_to_internal_never_broker(self):
        # Fail-safe direction for a COST proposal: never understate a cost by
        # calling an unrecognized route broker-$0.
        self.assertEqual(
            v2.classify_routing("alpaca_live", "some_future_mode"), v2.ROUTING_INTERNAL)
        self.assertEqual(
            v2.classify_routing(None, None), v2.ROUTING_INTERNAL)

    def test_case_insensitive(self):
        self.assertEqual(
            v2.classify_routing("ALPACA_LIVE", "Live_Eligible"), v2.ROUTING_BROKER)


class TestBrokerRoutedCommission(unittest.TestCase):
    def test_broker_commission_is_zero_and_labeled(self):
        rec = v2.build_proposal(
            current_tcm=_CUR_VALID, routing=v2.ROUTING_BROKER,
            leg_count=2, quantity=1, entry_or_close="entry")
        pm = rec["proposed_model"]["commission_usd"]
        self.assertEqual(pm["usd"], 0.0)
        self.assertTrue(pm["available"])
        self.assertEqual(pm["source"], v2.COMMISSION_SOURCE_BROKER)
        self.assertEqual(rec["source"], v2.COMMISSION_SOURCE_BROKER)

    def test_broker_commission_delta_is_negative_over_charge(self):
        # proposed 0.0 − current 0.65 = −0.65 (the frozen model over-charged)
        rec = v2.build_proposal(
            current_tcm=_CUR_VALID, routing=v2.ROUTING_BROKER,
            leg_count=2, quantity=1, entry_or_close="entry")
        d = rec["delta"]
        self.assertTrue(d["available"])
        self.assertAlmostEqual(d["commission_usd"], -0.65, places=6)

    def test_current_model_carried_verbatim(self):
        rec = v2.build_proposal(
            current_tcm=_CUR_VALID, routing=v2.ROUTING_BROKER,
            leg_count=2, quantity=1, entry_or_close="entry")
        cm = rec["current_model"]
        self.assertEqual(cm["commission_usd"]["usd"], 0.65)
        self.assertEqual(cm["spread_cost_usd"]["usd"], 1.50)
        self.assertEqual(cm["slippage_usd"]["usd"], 0.08)
        self.assertEqual(cm["tcm_version"], "1.1.0")


class TestInternalShadowCommission(unittest.TestCase):
    def test_internal_uses_synthetic_estimate_labeled(self):
        rec = v2.build_proposal(
            current_tcm=_CUR_VALID, routing=v2.ROUTING_INTERNAL,
            leg_count=1, quantity=1, entry_or_close="entry")
        pm = rec["proposed_model"]["commission_usd"]
        self.assertEqual(pm["usd"], 0.65)            # = current synthetic fee
        self.assertEqual(pm["source"], v2.COMMISSION_SOURCE_SYNTHETIC)
        # internal proposed == current → delta 0.0 (no over-charge on internal)
        self.assertEqual(rec["delta"]["commission_usd"], 0.0)

    def test_shadow_uses_synthetic_estimate(self):
        rec = v2.build_proposal(
            current_tcm=_CUR_VALID, routing=v2.ROUTING_SHADOW,
            leg_count=4, quantity=7, entry_or_close="entry")
        self.assertEqual(rec["source"], v2.COMMISSION_SOURCE_SYNTHETIC)
        self.assertEqual(rec["proposed_model"]["commission_usd"]["usd"], 0.65)


class TestMissingQuoteH9(unittest.TestCase):
    def test_missing_quote_types_spread_slippage_unavailable(self):
        # H9: fallback-derived spread/slippage are NOT carried as evidenced.
        rec = v2.build_proposal(
            current_tcm=_CUR_MISSING, routing=v2.ROUTING_BROKER,
            leg_count=2, quantity=1, entry_or_close="entry")
        pm = rec["proposed_model"]
        self.assertFalse(pm["spread_cost_usd"]["available"])
        self.assertIsNone(pm["spread_cost_usd"]["usd"])
        self.assertEqual(pm["spread_cost_usd"]["reason"], "quote_missing_carried_from_current")
        self.assertFalse(pm["slippage_usd"]["available"])
        self.assertIsNone(pm["slippage_usd"]["usd"])

    def test_commission_still_available_on_missing_quote(self):
        # Commission is qty-based → independent of the quote.
        rec = v2.build_proposal(
            current_tcm=_CUR_MISSING, routing=v2.ROUTING_BROKER,
            leg_count=2, quantity=1, entry_or_close="entry")
        pm = rec["proposed_model"]["commission_usd"]
        self.assertTrue(pm["available"])
        self.assertEqual(pm["usd"], 0.0)
        self.assertTrue(rec["context"]["missing_quote"])

    def test_present_quote_carries_spread_slippage(self):
        rec = v2.build_proposal(
            current_tcm=_CUR_VALID, routing=v2.ROUTING_BROKER,
            leg_count=2, quantity=1, entry_or_close="entry")
        pm = rec["proposed_model"]
        self.assertTrue(pm["spread_cost_usd"]["available"])
        self.assertEqual(pm["spread_cost_usd"]["usd"], 1.50)
        self.assertEqual(pm["carried_unchanged_from_current"],
                         ["spread_cost_usd", "slippage_usd"])


class TestPartialAndDeltaMath(unittest.TestCase):
    def test_no_fabricated_zero_when_current_fee_missing(self):
        cur = {k: v for k, v in _CUR_VALID.items() if k != "fees_usd"}
        rec = v2.build_proposal(
            current_tcm=cur, routing=v2.ROUTING_INTERNAL,
            leg_count=1, quantity=1, entry_or_close="entry")
        pm = rec["proposed_model"]["commission_usd"]
        self.assertFalse(pm["available"])
        self.assertIsNone(pm["usd"])                 # never 0.0
        self.assertFalse(rec["delta"]["available"])
        self.assertIsNone(rec["delta"]["commission_usd"])

    def test_none_current_tcm_does_not_raise(self):
        rec = v2.build_proposal(
            current_tcm=None, routing=v2.ROUTING_BROKER,
            leg_count=2, quantity=1, entry_or_close="close")
        # broker commission still computes ($0 is not fabricated — it's evidenced)
        self.assertEqual(rec["proposed_model"]["commission_usd"]["usd"], 0.0)
        # but the delta is unavailable (no current fee to compare against)
        self.assertFalse(rec["delta"]["available"])

    def test_realized_typed_unavailable_at_stage(self):
        rec = v2.build_proposal(
            current_tcm=_CUR_VALID, routing=v2.ROUTING_BROKER,
            leg_count=2, quantity=1, entry_or_close="entry")
        rw = rec["realized_when_available"]
        self.assertFalse(rw["available"])
        self.assertEqual(rw["reason"], "no_broker_fill_pre_execution")

    def test_record_carries_context_and_version(self):
        rec = v2.build_proposal(
            current_tcm=_CUR_VALID, routing=v2.ROUTING_BROKER,
            leg_count=2, quantity=3, entry_or_close="close",
            submit_to_broker=False, dry_run=True)
        self.assertEqual(rec["model_version"], v2.VERSION)
        self.assertEqual(rec["entry_or_close"], "close")
        self.assertEqual(rec["leg_count"], 2)
        self.assertEqual(rec["quantity"], 3)
        self.assertTrue(rec["observe_only"])
        self.assertTrue(rec["context"]["dry_run"])
        self.assertFalse(rec["context"]["submit_to_broker"])


class TestRealizedCloseJoin(unittest.TestCase):
    def test_broker_filled_known_zero(self):
        c = v2.realized_commission_when_available(
            execution_mode="alpaca_live", has_alpaca_order_id="abc",
            broker_status="filled", fees_usd=0.0)
        self.assertTrue(c["available"])
        self.assertEqual(c["usd"], 0.0)
        self.assertEqual(c["source"], "broker_reconciler")

    def test_internal_fill_unavailable(self):
        c = v2.realized_commission_when_available(
            execution_mode="internal_paper", has_alpaca_order_id=None,
            broker_status=None, fees_usd=1.30)
        self.assertFalse(c["available"])
        self.assertEqual(c["reason"], "internal_fill_commission_not_broker_stamped")

    def test_alpaca_mode_but_no_oid_unavailable(self):
        # execution_mode alpaca but never got a broker order id → not broker-stamped.
        c = v2.realized_commission_when_available(
            execution_mode="alpaca_paper", has_alpaca_order_id=None,
            broker_status="filled", fees_usd=0.0)
        self.assertFalse(c["available"])

    def test_broker_routed_but_fees_missing(self):
        c = v2.realized_commission_when_available(
            execution_mode="alpaca_live", has_alpaca_order_id="abc",
            broker_status="filled", fees_usd=None)
        self.assertFalse(c["available"])
        self.assertEqual(c["reason"], "broker_routed_but_fees_missing")


class TestCoerceFloatGuards(unittest.TestCase):
    def test_nan_and_inf_rejected(self):
        cur = dict(_CUR_VALID, fees_usd=float("nan"))
        rec = v2.build_proposal(
            current_tcm=cur, routing=v2.ROUTING_INTERNAL,
            leg_count=1, quantity=1, entry_or_close="entry")
        # NaN fee → treated as absent, never a fabricated number
        self.assertFalse(rec["current_model"]["commission_usd"]["available"])
        self.assertFalse(math.isnan(rec["proposed_model"]["commission_usd"]["usd"] or 0.0))


if __name__ == "__main__":
    unittest.main()
