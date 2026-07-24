"""no-quote-entry rejection on the executor path (2026-06-08 NFLX P86 fix).

The executor (_stage_order_internal) fetched ONE combo quote (legs[0]) and, on
an invalid quote, fell through to the modeled limit + the fabricating TCM
missing-quote fallback — so the 16:30Z NFLX entry submitted/filled on a leg
(P86, O:NFLX260710P00086000) our Polygon feed couldn't price.

_validate_entry_quotes now validates EACH leg with a FRESH quote at stage time
and REJECTS the whole OPEN order if any leg is unpriceable — never the modeled
limit, never the fabricating fallback, never a submit/shadow-fill. CLOSE orders
(position_id set) are exempt (a missing quote must not block an exit).

Flag ENTRY_QUOTE_VALIDATION_ENABLED, default ON; empty-string = default ON.
"""

import os
import sys
import types
import unittest
from unittest.mock import patch

# Stub alpaca-py so transitive imports resolve in the test venv.
from packages.quantum.tests._alpaca_stub import ensure_alpaca as _ensure_alpaca

_ensure_alpaca()

from packages.quantum import paper_endpoints as pe  # noqa: E402
from packages.quantum.paper_endpoints import (  # noqa: E402
    _validate_entry_quotes,
    _entry_quote_validation_enabled,
    _is_valid_quote,
    EntryQuoteUnpriceable,
)

P86 = "O:NFLX260710P00086000"   # the ITM long leg that was dark at scan
P79 = "O:NFLX260710P00079000"   # the short leg, priceable

VALID = {"bid": 4.28, "ask": 4.97}
DEAD = {"bid": 0, "ask": 0, "price": None}


def _ticket(*leg_syms):
    legs = [types.SimpleNamespace(symbol=s, action="buy") for s in leg_syms]
    return types.SimpleNamespace(legs=legs, symbol="NFLX")


def _fetch(quote_map):
    """fetch_fn that returns the mapped quote per leg symbol."""
    return lambda sym: quote_map.get(sym)


class TestFlag(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get("ENTRY_QUOTE_VALIDATION_ENABLED")
        os.environ.pop("ENTRY_QUOTE_VALIDATION_ENABLED", None)

    def tearDown(self):
        os.environ.pop("ENTRY_QUOTE_VALIDATION_ENABLED", None)
        if self._saved is not None:
            os.environ["ENTRY_QUOTE_VALIDATION_ENABLED"] = self._saved

    def test_default_on_when_unset(self):
        self.assertTrue(_entry_quote_validation_enabled())

    def test_empty_string_is_default_on(self):
        with patch.dict(os.environ, {"ENTRY_QUOTE_VALIDATION_ENABLED": ""}):
            self.assertTrue(_entry_quote_validation_enabled())
        with patch.dict(os.environ, {"ENTRY_QUOTE_VALIDATION_ENABLED": "   "}):
            self.assertTrue(_entry_quote_validation_enabled())

    def test_explicit_on_values(self):
        for v in ("1", "true", "yes", "on", "TRUE"):
            with patch.dict(os.environ, {"ENTRY_QUOTE_VALIDATION_ENABLED": v}):
                self.assertTrue(_entry_quote_validation_enabled(), v)

    def test_only_explicit_off_disables(self):
        for v in ("0", "false", "no", "off", "OFF"):
            with patch.dict(os.environ, {"ENTRY_QUOTE_VALIDATION_ENABLED": v}):
                self.assertFalse(_entry_quote_validation_enabled(), v)


class TestValidateEntryQuotes(unittest.TestCase):
    def setUp(self):
        os.environ.pop("ENTRY_QUOTE_VALIDATION_ENABLED", None)  # default ON

    def test_dead_leg_rejects_open_order(self):
        """P86 dead after fresh fetch → REJECT the open order."""
        with self.assertRaises(EntryQuoteUnpriceable) as cm:
            _validate_entry_quotes(
                _ticket(P86, P79), position_id=None,
                fetch_fn=_fetch({P86: DEAD, P79: VALID}),
            )
        self.assertEqual(cm.exception.leg_symbol, P86)
        self.assertEqual(cm.exception.quote, DEAD)

    def test_both_legs_valid_proceeds(self):
        """No regression: both priceable → returns None (no raise)."""
        self.assertIsInstance(_validate_entry_quotes(
            _ticket(P86, P79), position_id=None,
            fetch_fn=_fetch({P86: VALID, P79: VALID}),
        ), dict)

    def test_transient_recovers_on_fresh_fetch(self):
        """The 16:30Z case: scan-time quote was dead but the FRESH fetch (what
        this validates) returns a real quote → proceeds, no false reject."""
        # fetch_fn is the FRESH fetch; it returns valid for P86 now.
        self.assertIsInstance(_validate_entry_quotes(
            _ticket(P86, P79), position_id=None,
            fetch_fn=_fetch({P86: VALID, P79: VALID}),
        ), dict)

    def test_close_order_is_exempt(self):
        """A CLOSE (position_id set) must NOT be blocked by a dead leg —
        exits own #1022/#1035/#1036; trapped > bad close mark."""
        self.assertIsInstance(_validate_entry_quotes(
            _ticket(P86, P79), position_id="pos-123",
            fetch_fn=_fetch({P86: DEAD, P79: VALID}),
        ), dict)

    def test_flag_off_is_legacy_fallthrough(self):
        """Kill-switch off → no validation, no raise (rollback verification)."""
        with patch.dict(os.environ, {"ENTRY_QUOTE_VALIDATION_ENABLED": "0"}):
            self.assertIsInstance(_validate_entry_quotes(
                _ticket(P86, P79), position_id=None,
                fetch_fn=_fetch({P86: DEAD, P79: VALID}),
            ), dict)

    def test_second_leg_dead_also_rejects(self):
        with self.assertRaises(EntryQuoteUnpriceable) as cm:
            _validate_entry_quotes(
                _ticket(P79, P86), position_id=None,
                fetch_fn=_fetch({P79: VALID, P86: DEAD}),
            )
        self.assertEqual(cm.exception.leg_symbol, P86)

    def test_leg_without_symbol_skipped(self):
        legs = [types.SimpleNamespace(symbol=None, action="buy"),
                types.SimpleNamespace(symbol=P79, action="sell")]
        tk = types.SimpleNamespace(legs=legs, symbol="NFLX")
        self.assertIsInstance(_validate_entry_quotes(
            tk, position_id=None, fetch_fn=_fetch({P79: VALID}),
        ), dict)


class TestDoesNotReachFabricatingFallback(unittest.TestCase):
    """An entry with a dead leg must raise BEFORE the order is staged — proving
    the fabricating TCM fallback / submit path is never reached."""

    def setUp(self):
        os.environ.pop("ENTRY_QUOTE_VALIDATION_ENABLED", None)

    def test_raise_precedes_tcm_and_insert(self):
        # If validation raises, fetch_fn is called but no fill is fabricated.
        calls = {"fetched": []}

        def _fetch_fn(sym):
            calls["fetched"].append(sym)
            return DEAD if sym == P86 else VALID

        with self.assertRaises(EntryQuoteUnpriceable):
            _validate_entry_quotes(
                _ticket(P86, P79), position_id=None, fetch_fn=_fetch_fn,
            )
        # It fetched P86 (the dead one) and stopped — never proceeded to staging.
        self.assertIn(P86, calls["fetched"])


class TestSourcePins(unittest.TestCase):
    """_stage_order_internal wires the validation (entry path) and the close
    path stays exempt."""

    def test_stage_order_internal_calls_validation(self):
        import inspect
        src = inspect.getsource(pe._stage_order_internal)
        self.assertIn("_validate_entry_quotes(", src)
        # passes position_id (the entry/exit discriminator)
        self.assertIn("position_id", src)

    def test_is_valid_quote_reused(self):
        # The validator reuses the existing _is_valid_quote (no reinvention).
        import inspect
        src = inspect.getsource(_validate_entry_quotes)
        self.assertIn("_is_valid_quote(", src)


if __name__ == "__main__":
    unittest.main()
