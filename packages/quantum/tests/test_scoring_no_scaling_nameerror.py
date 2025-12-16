
import pytest
from packages.quantum.analytics.scoring import calculate_unified_score

def test_calculate_unified_score_nameerror():
    trade = {
        "ev": 50.0,
        "suggested_entry": 1.00,         # per-share
        "bid_ask_spread": 0.05,          # per-share spread width
        "net_delta_per_contract": 0.10,
        "net_vega_per_contract": 5.0,
        "strategy_key": "credit_spread",
        "max_loss_per_contract": 400.0,
        "collateral_required_per_contract": 500.0,
    }
    regime_snapshot = {"regime": "NORMAL", "state": "normal"}

    # Removed macro_context as it is not in the signature
    out = calculate_unified_score(trade=trade, regime_snapshot=regime_snapshot)

    assert out is not None
    assert hasattr(out, "score") or "score" in out
    score = out.score if hasattr(out, "score") else out["score"]
    assert isinstance(score, (int, float))
