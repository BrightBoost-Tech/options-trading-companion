"""⑤ Scan-time capture (services/td_scan_capture) — envelope builder + recorder.

Proves: per-leg IV is threaded from the already-fetched source chain (ZERO
provider calls), the builder never mutates the input legs, no-legs → None
(not_scorable), the flag parser is default-OFF lenient-truthy, and the recorder
is absolute fail-soft (disabled no-op / table-missing typed no-op / write-failure
counted) and never mutates candidates.
"""

import copy
import os
import unittest
from unittest.mock import patch

from packages.quantum.services import td_scan_capture as C
from packages.quantum.services.td_scan_capture import (
    ENVELOPE_TABLE,
    ScanEnvelopeRecorder,
    build_research_candidate_envelope,
    td_scan_observe_enabled,
)
from packages.quantum.services.options_utils import compute_legs_fingerprint


def _legs():
    return [
        {"symbol": "O:SPY260824C00500000", "side": "buy", "type": "call",
         "strike": 500.0, "expiry": "2026-08-24", "delta": 0.55, "gamma": 0.02,
         "vega": 0.1, "theta": -0.05, "bid": 3.0, "ask": 3.06, "mid": 3.03,
         "premium": 3.03},
        {"symbol": "O:SPY260824C00510000", "side": "sell", "type": "call",
         "strike": 510.0, "expiry": "2026-08-24", "delta": 0.30, "gamma": 0.02,
         "vega": 0.1, "theta": -0.05, "bid": 1.0, "ask": 1.06, "mid": 1.03,
         "premium": 1.03},
    ]


def _chain_nested():
    # TruthLayer nested schema: OCC at 'contract', IV at top-level 'iv'.
    return [
        {"contract": "O:SPY260824C00500000", "strike": 500.0, "expiry": "2026-08-24",
         "type": "call", "iv": 0.22, "greeks": {"delta": 0.55}, "quote": {"bid": 3.0, "ask": 3.06}},
        {"contract": "O:SPY260824C00510000", "strike": 510.0, "expiry": "2026-08-24",
         "type": "call", "iv": 0.20, "greeks": {"delta": 0.30}, "quote": {"bid": 1.0, "ask": 1.06}},
    ]


class TestFlagParser(unittest.TestCase):
    def test_default_off(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TERMINAL_DISTRIBUTION_SCAN_OBSERVE_ENABLED", None)
            self.assertFalse(td_scan_observe_enabled())

    def test_lenient_truthy_on(self):
        for v in ("1", "true", "yes", "on", "TRUE", "On"):
            with patch.dict(os.environ, {"TERMINAL_DISTRIBUTION_SCAN_OBSERVE_ENABLED": v}):
                self.assertTrue(td_scan_observe_enabled(), v)

    def test_explicit_falsy_off(self):
        for v in ("0", "false", "no", "off", ""):
            with patch.dict(os.environ, {"TERMINAL_DISTRIBUTION_SCAN_OBSERVE_ENABLED": v}):
                self.assertFalse(td_scan_observe_enabled(), v)


class TestEnvelopeBuilder(unittest.TestCase):
    def test_iv_threaded_from_chain_zero_fetch(self):
        legs = _legs()
        env = build_research_candidate_envelope(
            symbol="SPY", strategy="LONG_CALL_DEBIT_SPREAD", strategy_key="long_call_debit_spread",
            legs=legs, chain=_chain_nested(), current_price=500.0, total_ev=17.5,
            net_premium=2.0, premium_direction="debit", dte_days=35.0,
        )
        ivs = {l["symbol"]: l["iv"] for l in env["legs"]}
        self.assertEqual(ivs["O:SPY260824C00500000"], 0.22)
        self.assertEqual(ivs["O:SPY260824C00510000"], 0.20)
        # delta copied, strike/side/type present.
        self.assertEqual(env["legs"][0]["delta"], 0.55)
        self.assertEqual(env["legs"][0]["option_type"], "call")
        self.assertEqual(env["contracts"], 1)
        self.assertEqual(env["production_ev"], 17.5)
        self.assertIsNone(env["production_pop"])  # absent pre-emit (§7a)

    def test_missing_iv_in_chain_stays_none_never_defaulted(self):
        legs = _legs()
        # chain without iv → threaded iv is None (challenger will abstain).
        chain = [{"contract": l["symbol"], "strike": l["strike"], "greeks": {"delta": l["delta"]}}
                 for l in legs]
        env = build_research_candidate_envelope(
            symbol="SPY", strategy="LONG_CALL_DEBIT_SPREAD", strategy_key="k",
            legs=legs, chain=chain, current_price=500.0, total_ev=1.0,
            net_premium=2.0, premium_direction="debit", dte_days=35.0,
        )
        self.assertTrue(all(l["iv"] is None for l in env["legs"]))

    def test_builder_never_mutates_input_legs(self):
        legs = _legs()
        before = copy.deepcopy(legs)
        build_research_candidate_envelope(
            symbol="SPY", strategy="S", strategy_key="k", legs=legs,
            chain=_chain_nested(), current_price=500.0, total_ev=1.0,
            net_premium=2.0, premium_direction="debit", dte_days=35.0,
        )
        self.assertEqual(legs, before, "capture must never mutate the live legs")

    def test_no_legs_returns_none_not_scorable(self):
        env = build_research_candidate_envelope(
            symbol="SPY", strategy="S", strategy_key="k", legs=[],
            chain=_chain_nested(), current_price=500.0, total_ev=1.0,
            net_premium=None, premium_direction=None, dte_days=None,
        )
        self.assertIsNone(env)

    def test_fingerprint_equals_legs_fingerprint(self):
        legs = _legs()
        env = build_research_candidate_envelope(
            symbol="SPY", strategy="S", strategy_key="k", legs=legs,
            chain=_chain_nested(), current_price=500.0, total_ev=1.0,
            net_premium=2.0, premium_direction="debit", dte_days=35.0,
        )
        self.assertEqual(env["candidate_fingerprint"], compute_legs_fingerprint({"legs": legs}))


class _FakeQ:
    def __init__(self, parent, table):
        self._p = parent
        self._t = table
        self._op = None
        self._payload = None

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def execute(self):
        return self._p._exec(self._t, self._op, self._payload)


class _FakeSB:
    def __init__(self, raise_on_insert=None):
        self.inserted = []
        self.raise_on_insert = raise_on_insert

    def table(self, name):
        self._last = name
        return _FakeQ(self, name)

    def _exec(self, table, op, payload):
        if op == "insert":
            if self.raise_on_insert is not None:
                raise self.raise_on_insert
            self.inserted.append((table, payload))
        class _R:
            data = []
        return _R()


class TestRecorder(unittest.TestCase):
    def _rec(self, sb, enabled=True):
        return ScanEnvelopeRecorder(sb, cycle_date="2026-07-23", enabled=enabled)

    def _record_one(self, rec):
        rec.record(symbol="SPY", strategy="LONG_CALL_DEBIT_SPREAD", strategy_key="k",
                   legs=_legs(), chain=_chain_nested(), current_price=500.0,
                   total_ev=17.5, net_premium=2.0, premium_direction="debit")

    def test_disabled_is_total_noop(self):
        sb = _FakeSB()
        rec = self._rec(sb, enabled=False)
        self._record_one(rec)
        out = rec.flush([])
        self.assertEqual(out["status"], "disabled")
        self.assertEqual(sb.inserted, [])
        self.assertEqual(rec.counters["captured"], 0)

    def test_enabled_captures_and_flushes(self):
        sb = _FakeSB()
        rec = self._rec(sb)
        self._record_one(rec)
        self.assertEqual(rec.counters["captured"], 1)
        # emitted resolved from the candidates set (fingerprint match → emitted).
        emitted_cand = [{"legs": _legs()}]
        out = rec.flush(emitted_cand)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(len(sb.inserted), 1)
        table, rows = sb.inserted[0]
        self.assertEqual(table, ENVELOPE_TABLE)
        self.assertEqual(rows[0]["emitted"], True)
        self.assertIsNone(rows[0]["reject_reason"])

    def test_non_emitted_gets_reject_reason(self):
        sb = _FakeSB()
        rec = self._rec(sb)
        self._record_one(rec)
        out = rec.flush([])  # empty emitted set → this candidate was rejected
        self.assertEqual(out["status"], "ok")
        _, rows = sb.inserted[0]
        self.assertEqual(rows[0]["emitted"], False)
        self.assertEqual(rows[0]["reject_reason"], "unattributed_post_ev")

    def test_table_missing_typed_noop(self):
        sb = _FakeSB(raise_on_insert=Exception("relation td_scan_envelopes does not exist"))
        rec = self._rec(sb)
        self._record_one(rec)
        out = rec.flush([])
        self.assertEqual(out["status"], "table_missing")
        self.assertEqual(out["table_missing_noops"], 1)

    def test_write_failure_counted_never_raises(self):
        sb = _FakeSB(raise_on_insert=Exception("some transient boom"))
        rec = self._rec(sb)
        self._record_one(rec)
        out = rec.flush([])  # must NOT raise
        self.assertEqual(out["status"], "write_failed")
        self.assertEqual(out["write_failures"], 1)

    def test_record_never_raises_on_bad_input(self):
        sb = _FakeSB()
        rec = self._rec(sb)
        # A malformed legs arg must be swallowed (fail-soft), not raised.
        rec.record(symbol="SPY", strategy="S", strategy_key="k", legs=None,
                   chain=None, current_price=None, total_ev=None,
                   net_premium=None, premium_direction=None)
        self.assertEqual(rec.counters["captured"], 0)

    def test_no_client_disabled(self):
        rec = ScanEnvelopeRecorder(None, cycle_date="2026-07-23", enabled=True)
        self.assertFalse(rec.enabled)


if __name__ == "__main__":
    unittest.main()
