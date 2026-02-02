import pytest
from unittest.mock import MagicMock
from packages.quantum.options_scanner import _combo_width_share_from_legs, _select_legs_from_chain

class MockTruthLayerRaising:
    def snapshot_many(self, symbols):
        raise RuntimeError("snapshot_many should not be called!")

    def normalize_symbol(self, sym):
        return sym

def test_select_legs_persists_quotes():
    """Test that _select_legs_from_chain copies bid/ask to legs."""
    chain = [
        {
            "contract": "O:SPY250101C00400000",
            "strike": 400.0,
            "expiration": "2025-01-01",
            "type": "call",
            "delta": 0.5,
            "gamma": 0.01,
            "vega": 0.1,
            "theta": -0.05,
            "price": 5.0,
            "close": 5.0,
            "bid": 4.90,
            "ask": 5.10,
            "ticker": "O:SPY250101C00400000"
        }
    ]

    leg_defs = [
        {"delta_target": 0.5, "side": "buy", "type": "call"}
    ]

    # calls=chain, puts=[], leg_defs=leg_defs
    legs, cost = _select_legs_from_chain(chain, [], leg_defs, current_price=400.0)

    assert len(legs) == 1
    leg = legs[0]
    # These should exist after the fix
    assert "bid" in leg, "bid key missing in leg"
    assert "ask" in leg, "ask key missing in leg"
    assert "mid" in leg, "mid key missing in leg"

    assert leg["bid"] == 4.90
    assert leg["ask"] == 5.10
    assert leg["mid"] == 5.0

def test_combo_width_uses_stored_quotes():
    """Test that _combo_width_share_from_legs uses stored quotes and avoids snapshot_many."""
    truth_layer = MockTruthLayerRaising()

    legs = [
        {
            "symbol": "SYM1",
            "bid": 1.0,
            "ask": 1.2
        },
        {
            "symbol": "SYM2",
            "bid": 2.0,
            "ask": 2.2
        }
    ]

    # Expected width: (1.2 - 1.0) + (2.2 - 2.0) = 0.2 + 0.2 = 0.4
    width = _combo_width_share_from_legs(truth_layer, legs, fallback_width_share=0.5)

    assert width == pytest.approx(0.4)

def test_combo_width_fallback_when_missing_quotes():
    """Test that it falls back to snapshot_many if quotes are missing."""

    # We need a truth layer that DOES NOT raise, but returns data
    mock_truth = MagicMock()
    mock_truth.snapshot_many.return_value = {
        "SYM1": {"quote": {"bid": 1.0, "ask": 1.2}},
        "SYM2": {"quote": {"bid": 2.0, "ask": 2.2}}
    }
    mock_truth.normalize_symbol.side_effect = lambda x: x

    legs = [
        {
            "symbol": "SYM1",
            # Missing bid/ask
        },
        {
            "symbol": "SYM2",
            "bid": 2.0,
            "ask": 2.2
        }
    ]

    width = _combo_width_share_from_legs(mock_truth, legs, fallback_width_share=0.5)

    # It should have called snapshot_many
    mock_truth.snapshot_many.assert_called_once()
    assert width == pytest.approx(0.4)
