
import pytest
from packages.quantum.analytics.opportunity_scorer import OpportunityScorer
from packages.quantum.services.replay.canonical import compute_content_hash

def test_opportunity_scorer_features_hash_determinism():
    """
    Verifies that OpportunityScorer uses the canonical compute_content_hash (SHA256)
    instead of non-deterministic JSON dumping + MD5.
    """
    trade = {
        "symbol": "SPY",
        "type": "credit_put",
        "short_strike": 490,
        "long_strike": 485,
        "expiry": "2024-02-16",
        "credit": 0.50
    }
    market = {
        "price": 500.0,
        "iv": 0.15,
        "bid": 0.45,
        "ask": 0.55
    }

    # Run scorer
    result = OpportunityScorer.score(trade, market)

    # 1. Assert hash is SHA256 length (64 chars)
    # This will fail if still using MD5 (32 chars)
    assert len(result['features_hash']) == 64, f"features_hash should be SHA256 (64 chars), got {len(result['features_hash'])}"

    # 2. Assert it matches compute_content_hash of the feature inputs
    # Reconstruct features exactly as OpportunityScorer does
    features = {
        "sym": "SPY",
        "str": "credit_put",
        "strikes": "490.0/485.0",
        "exp": "2024-02-16",
        "iv": round(0.15, 4),
        "mu": round(0.05, 4), # Default used in scorer
        "price": round(500.0, 2)
    }

    expected_hash = compute_content_hash(features)
    assert result['features_hash'] == expected_hash, "features_hash should match canonical hash of inputs"
