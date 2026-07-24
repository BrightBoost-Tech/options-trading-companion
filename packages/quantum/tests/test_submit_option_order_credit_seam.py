"""Seam test: build_alpaca_order_request → submit_option_order for an
mleg CREDIT close.

THE GAP THIS CLOSES
-------------------
`build_alpaca_order_request` (alpaca_order_handler.py) correctly emits a
NEGATIVE limit_price for a multi-leg credit close (selling a debit spread
to close receives a credit; Alpaca's mleg convention encodes credit as a
negative parent limit — the #101 fix). It guards on MAGNITUDE
(`abs(limit_price) < 0.01`).

`submit_option_order` (alpaca_client.py) one layer down USED to guard on
SIGN (`limit_price <= 0`) — so it rejected exactly the value the upstream
produces, routing every automated debit-spread close to
needs_manual_review. Debit spreads dominate the book, so this blocked the
dominant position type's automated close.

It went unnoticed because nothing ever crossed the build→submit seam:
`test_csx_close_sign_convention.py` asserts `build_alpaca_order_request`
emits -1.86 IN ISOLATION and never calls `submit_option_order`. This file
exercises the ACTUAL path: the -1.86 that build emits flows THROUGH
submit_option_order and is forwarded to the broker request, not bounced.

These tests mock the Alpaca SDK surface — they validate the internal
build→submit contract. The broker-level question (does Alpaca actually
accept/fill a real mleg credit close?) is separate and requires market
hours; see the PR for that pending validation.
"""

import sys
import types
import unittest
from unittest.mock import MagicMock, patch


# ─────────────────────────────────────────────────────────────────────
# Minimal Alpaca SDK stubs so submit_option_order's function-level
# imports resolve to a RECORDING stand-in (so the test can assert on the
# limit_price that reaches the broker request). submit_option_order imports
# these at call time, so overriding them in sys.modules for the duration of
# the test is sufficient. They are installed via patch.dict so they are
# restored — never left shadowing the real alpaca-py for later-collected
# tests (the sys.modules stub-leak class; Lane D).
# ─────────────────────────────────────────────────────────────────────

class _FakeEnumMember:
    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return f"<{self.value}>"


class _OrderSide:
    BUY = _FakeEnumMember("buy")
    SELL = _FakeEnumMember("sell")


class _TimeInForce:
    DAY = _FakeEnumMember("day")
    GTC = _FakeEnumMember("gtc")


class _OrderType:
    LIMIT = _FakeEnumMember("limit")


class _OrderClass:
    MLEG = _FakeEnumMember("mleg")


class _PositionIntent:
    BUY_TO_OPEN = _FakeEnumMember("buy_to_open")
    BUY_TO_CLOSE = _FakeEnumMember("buy_to_close")
    SELL_TO_OPEN = _FakeEnumMember("sell_to_open")
    SELL_TO_CLOSE = _FakeEnumMember("sell_to_close")


class _RecordingRequest:
    """Stand-in for OptionLegRequest / LimitOrderRequest — records the
    kwargs it was constructed with so the test can assert on the
    limit_price that reaches the broker request."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.__dict__.update(kwargs)


def _build_alpaca_stub_modules():
    """Build FRESH stub module objects carrying the recording request +
    fake enums. Returned as a {name: module} dict for ``patch.dict`` so the
    override is scoped and restored — nothing is mutated on a shared/real
    module and nothing leaks past the test."""
    alpaca = types.ModuleType("alpaca")
    trading = types.ModuleType("alpaca.trading")
    requests_mod = types.ModuleType("alpaca.trading.requests")
    enums_mod = types.ModuleType("alpaca.trading.enums")

    alpaca.trading = trading
    trading.requests = requests_mod
    trading.enums = enums_mod

    requests_mod.OptionLegRequest = _RecordingRequest
    requests_mod.LimitOrderRequest = _RecordingRequest

    enums_mod.OrderSide = _OrderSide
    enums_mod.TimeInForce = _TimeInForce
    enums_mod.OrderType = _OrderType
    enums_mod.OrderClass = _OrderClass
    enums_mod.PositionIntent = _PositionIntent

    return {
        "alpaca": alpaca,
        "alpaca.trading": trading,
        "alpaca.trading.requests": requests_mod,
        "alpaca.trading.enums": enums_mod,
    }


def _install_alpaca_stubs(testcase):
    """Install the recording alpaca stubs in sys.modules for the duration of
    ``testcase`` ONLY (restored via addCleanup, so an assertion failure or
    exception cannot leak the stubs to later-collected tests)."""
    patcher = patch.dict(sys.modules, _build_alpaca_stub_modules())
    patcher.start()
    testcase.addCleanup(patcher.stop)


def _make_client(submit_return=None):
    """Construct an AlpacaClient without touching the network.

    Bypasses __init__ (which would build a real TradingClient) and wires
    just the three attributes submit_option_order touches: _client,
    _call_with_retry, _serialize_order.
    """
    from packages.quantum.brokers.alpaca_client import AlpacaClient

    client = AlpacaClient.__new__(AlpacaClient)
    client.paper = True
    client._client = MagicMock()
    client._client.submit_order.return_value = submit_return or object()
    # Pass-through retry wrapper: call the function directly.
    client._call_with_retry = lambda fn, arg: fn(arg)
    # Serializer returns a forwarded-accepted shape (not needs_manual_review).
    client._serialize_order = lambda order: {
        "alpaca_order_id": "seam-test-order-id",
        "status": "accepted",
    }
    return client


def _csx_credit_close_order(requested_price=1.86):
    """The actual CSX close order_json shape captured 2026-05-08: a long
    debit spread (sell the lower-strike long, buy the higher-strike short)
    closed for a net credit → is_credit_close=True."""
    return {
        "id": "seam-csx-close",
        "position_id": "1f77f6af-b536-46a3-9975-88dfef41f855",
        "side": "sell",
        "requested_qty": 1,
        "requested_price": requested_price,
        "order_json": {
            "symbol": "CSX",
            "limit_price": requested_price,
            "is_credit_close": True,
            "legs": [
                {"symbol": "O:CSX260605C00043000", "action": "sell",
                 "type": "call", "strike": 43, "quantity": 1},
                {"symbol": "O:CSX260605C00047000", "action": "buy",
                 "type": "call", "strike": 47, "quantity": 1},
            ],
        },
    }


class TestCreditCloseCrossesBuildSubmitSeam(unittest.TestCase):
    """The headline regression: the negative net-credit limit that
    build_alpaca_order_request produces must survive submit_option_order
    and reach the broker request — not be rejected by the guard."""

    def setUp(self):
        _install_alpaca_stubs(self)
        from packages.quantum.brokers.alpaca_order_handler import (
            build_alpaca_order_request,
        )
        self.build = build_alpaca_order_request

    def test_csx_credit_close_flows_through_to_broker_request(self):
        # 1. UPSTREAM: build emits the negative net-credit limit (#101).
        req = self.build(_csx_credit_close_order(requested_price=1.86))
        self.assertEqual(
            req["limit_price"], -1.86,
            "precondition: build_alpaca_order_request must emit -1.86 for "
            "the credit close",
        )

        # 2. DOWNSTREAM: that exact request must pass through submit, NOT
        #    raise AlpacaOrderError. Pre-fix this raised at the sign guard.
        client = _make_client()
        result = client.submit_option_order(req)

        # 3. The broker request was actually built + forwarded.
        client._client.submit_order.assert_called_once()
        forwarded = client._client.submit_order.call_args[0][0]
        self.assertEqual(
            forwarded.kwargs["limit_price"], -1.86,
            "the negative credit limit must reach the broker request intact "
            "(no abs/clamp/sign-flip downstream of the guard)",
        )
        # 4. Forwarded/accepted — not bounced to needs_manual_review.
        self.assertEqual(result["status"], "accepted")

    def test_f_shape_credit_close_also_passes(self):
        # F-shape ~ -1.30 net credit (0.96 debit × 1.35 target). Same path,
        # different magnitude — guards against a future off-by-threshold.
        req = self.build(_csx_credit_close_order(requested_price=1.30))
        self.assertEqual(req["limit_price"], -1.30)
        client = _make_client()
        client.submit_option_order(req)  # must not raise
        forwarded = client._client.submit_order.call_args[0][0]
        self.assertEqual(forwarded.kwargs["limit_price"], -1.30)


class TestMagnitudeGuardStillRejectsInvalid(unittest.TestCase):
    """The guard must still do its real job: a missing / sub-penny limit
    is rejected. The fix widened it to magnitude, not to 'accept anything
    negative'."""

    def setUp(self):
        _install_alpaca_stubs(self)

    def _minimal_req(self, limit_price):
        return {
            "symbol": "CSX",
            "limit_price": limit_price,
            "qty": 1,
            "order_type": "limit",
            "time_in_force": "day",
            "legs": [
                {"symbol": "CSX260605C00043000", "side": "sell",
                 "position_intent": "sell_to_close"},
                {"symbol": "CSX260605C00047000", "side": "buy",
                 "position_intent": "buy_to_close"},
            ],
        }

    def test_zero_limit_rejected(self):
        from packages.quantum.brokers.alpaca_client import AlpacaOrderError
        client = _make_client()
        with self.assertRaises(AlpacaOrderError):
            client.submit_option_order(self._minimal_req(0))
        client._client.submit_order.assert_not_called()

    def test_missing_limit_rejected(self):
        from packages.quantum.brokers.alpaca_client import AlpacaOrderError
        client = _make_client()
        with self.assertRaises(AlpacaOrderError):
            client.submit_option_order(self._minimal_req(None))
        client._client.submit_order.assert_not_called()

    def test_sub_penny_negative_still_rejected(self):
        # A negative magnitude below 0.01 is NOT a valid credit — the
        # magnitude guard must still reject it (proves the fix is
        # magnitude-based, not 'all negatives pass').
        from packages.quantum.brokers.alpaca_client import AlpacaOrderError
        client = _make_client()
        with self.assertRaises(AlpacaOrderError):
            client.submit_option_order(self._minimal_req(-0.004))
        client._client.submit_order.assert_not_called()

    def test_positive_debit_still_passes(self):
        # Unchanged behavior: a normal positive debit (e.g. opening or a
        # credit-spread close) still submits.
        client = _make_client()
        client.submit_option_order(self._minimal_req(1.25))
        client._client.submit_order.assert_called_once()


if __name__ == "__main__":
    unittest.main()
