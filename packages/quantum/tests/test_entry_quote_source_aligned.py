"""Tests for Phase C — stage-quote source alignment (06-10 runbook).

The 06-10 16:30Z XLE rejections were FEED DIVERGENCE: Polygon's option NBBO
returned zeros for O:XLE260717C00058000 while OPRA (via the truth layer's
Alpaca-primary path) quoted 2.15×428 / 2.39×565 with 83 trades on the day.
The entry stage validator read Polygon only.

Pins:
- XLE fixture, divergence: Polygon zeros + truth-layer live → leg priced
  from the truth-layer quote, one FEED DIVERGENCE WARNING logged
- XLE fixture, all dark: every source zeros → EntryQuoteUnpriceable raised
  exactly as before (the gate is never weakened)
- flag off (explicit falsy) → legacy Polygon-only behavior (truth layer
  never consulted; zeros raise even when Alpaca is live)
- empty/unset flag → aligned (ON)
- truth-layer exception → falls to Polygon (fail-soft, no crash)
- both sources valid → truth-layer preferred, NO divergence warning
- close-path untouched: position_id set → fetch_fn never invoked
"""

import logging
import sys
import types
import unittest
from unittest import mock

# Stub alpaca-py so paper_endpoints imports resolve in the test venv.
from packages.quantum.tests._alpaca_stub import ensure_alpaca as _ensure_alpaca

_ensure_alpaca()

from packages.quantum import paper_endpoints as pe  # noqa: E402


XLE_LEG = "O:XLE260717C00058000"
TRUTH_LIVE = {"quote": {"bid": 2.15, "ask": 2.39, "last": 2.33, "mid": 2.27}}
POLY_ZEROS = {"bid": 0.0, "ask": 0.0, "bid_price": 0.0, "ask_price": 0.0, "price": None}


class _TruthStub:
    instances = []

    def __init__(self, snap=None, raises=False):
        self._snap = snap
        self._raises = raises
        _TruthStub.instances.append(self)
        self.calls = []

    def snapshot_many(self, symbols):
        self.calls.append(list(symbols))
        if self._raises:
            raise RuntimeError("truth layer down")
        return {symbols[0]: self._snap} if self._snap else {}


def _patch(monkeystack, truth_snap=None, truth_raises=False, poly_quote=None, env=None):
    truth = _TruthStub(snap=truth_snap, raises=truth_raises)
    fake_module = types.SimpleNamespace(MarketDataTruthLayer=lambda *a, **k: truth)
    monkeystack.enter_context(mock.patch.dict(
        sys.modules, {"packages.quantum.services.market_data_truth_layer": fake_module},
    ))
    monkeystack.enter_context(mock.patch.object(
        pe, "_fetch_quote_with_retry", lambda poly, s: poly_quote,
    ))
    monkeystack.enter_context(mock.patch.dict("os.environ", env or {}, clear=False))
    return truth


class TestAlignedFetch(unittest.TestCase):
    def setUp(self):
        self.stack = mock.patch.stopall  # noqa - use ExitStack instead
        import contextlib
        self.ctx = contextlib.ExitStack()
        import os
        os.environ.pop("ENTRY_QUOTE_SOURCE_ALIGNED", None)

    def tearDown(self):
        self.ctx.close()

    def test_xle_divergence_polygon_dark_truth_live(self):
        truth = _patch(self.ctx, truth_snap=TRUTH_LIVE, poly_quote=POLY_ZEROS)
        with self.assertLogs(pe.logger, level=logging.WARNING) as logs:
            q = pe._aligned_leg_quote_fetch(object(), XLE_LEG)
        self.assertTrue(pe._is_valid_quote(q))
        self.assertEqual(q["bid"], 2.15)
        self.assertEqual(q["ask"], 2.39)
        self.assertTrue(any("FEED DIVERGENCE" in m for m in logs.output))

    def test_all_sources_dark_stays_unpriceable(self):
        _patch(self.ctx, truth_snap=None, poly_quote=POLY_ZEROS)
        q = pe._aligned_leg_quote_fetch(object(), XLE_LEG)
        self.assertFalse(pe._is_valid_quote(q))

    def test_all_dark_raises_through_validator_unchanged(self):
        _patch(self.ctx, truth_snap=None, poly_quote=POLY_ZEROS)
        ticket = types.SimpleNamespace(legs=[{"symbol": XLE_LEG}])
        with self.assertRaises(pe.EntryQuoteUnpriceable):
            pe._validate_entry_quotes(
                ticket, None,
                fetch_fn=pe._make_entry_quote_fetch_fn(object()),
            )

    def test_truth_layer_exception_falls_to_polygon(self):
        _patch(self.ctx, truth_raises=True,
               poly_quote={"bid": 1.0, "ask": 1.2, "price": 1.1})
        q = pe._aligned_leg_quote_fetch(object(), XLE_LEG)
        self.assertTrue(pe._is_valid_quote(q))
        self.assertEqual(q["bid"], 1.0)

    def test_both_valid_prefers_truth_no_divergence_warning(self):
        truth = _patch(self.ctx, truth_snap=TRUTH_LIVE,
                       poly_quote={"bid": 2.10, "ask": 2.45, "price": 2.30})
        q = pe._aligned_leg_quote_fetch(object(), XLE_LEG)
        self.assertEqual(q["bid"], 2.15)  # truth preferred
        # No assertLogs context: verify divergence text absent via capture
        with self.assertLogs(pe.logger, level=logging.WARNING) as logs:
            pe.logger.warning("sentinel")
            pe._aligned_leg_quote_fetch(object(), XLE_LEG)
        self.assertFalse(any("FEED DIVERGENCE" in m for m in logs.output))


class TestFlag(unittest.TestCase):
    def test_unset_is_aligned(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("ENTRY_QUOTE_SOURCE_ALIGNED", None)
            self.assertTrue(pe._entry_quote_source_aligned())

    def test_empty_is_aligned(self):
        with mock.patch.dict("os.environ", {"ENTRY_QUOTE_SOURCE_ALIGNED": ""}):
            self.assertTrue(pe._entry_quote_source_aligned())

    def test_explicit_off_reverts_to_polygon_only(self):
        import contextlib
        with contextlib.ExitStack() as ctx:
            truth = _patch(
                ctx, truth_snap=TRUTH_LIVE, poly_quote=POLY_ZEROS,
                env={"ENTRY_QUOTE_SOURCE_ALIGNED": "0"},
            )
            fetch = pe._make_entry_quote_fetch_fn(object())
            q = fetch(XLE_LEG)
            # Legacy behavior: zeros pass through; Alpaca-live is IGNORED.
            self.assertFalse(pe._is_valid_quote(q))
            self.assertEqual(truth.calls, [])  # truth layer never consulted


class TestClosePathUntouched(unittest.TestCase):
    def test_close_orders_never_fetch(self):
        def _boom(_s):
            raise AssertionError("close-path must never fetch entry quotes")

        ticket = types.SimpleNamespace(legs=[{"symbol": XLE_LEG}])
        # position_id set → CLOSE → exempt before any fetch, flag irrelevant.
        pe._validate_entry_quotes(ticket, "pos-123", fetch_fn=_boom)


if __name__ == "__main__":
    unittest.main()
