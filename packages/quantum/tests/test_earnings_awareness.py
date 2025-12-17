
import pytest
import sys
import os
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta

# Adjust path so we can import from packages.quantum
sys.path.append(os.path.join(os.path.dirname(__file__), '../../..'))

from packages.quantum.options_scanner import scan_for_opportunities

@pytest.fixture
def mock_dependencies():
    with patch("packages.quantum.options_scanner.PolygonService") as MockPolygon, \
         patch("packages.quantum.options_scanner.UniverseService") as MockUniverse, \
         patch("packages.quantum.options_scanner.MarketDataTruthLayer") as MockMDTL, \
         patch("packages.quantum.options_scanner.RegimeEngineV3") as MockRegime, \
         patch("packages.quantum.options_scanner.StrategySelector") as MockSelector, \
         patch("packages.quantum.options_scanner.calculate_ev") as MockCalcEV, \
         patch("packages.quantum.options_scanner.calculate_unified_score") as MockUnifiedScore:

        # Setup mocks
        mock_poly = MockPolygon.return_value
        mock_univ = MockUniverse.return_value
        mock_mdtl = MockMDTL.return_value
        mock_regime = MockRegime.return_value
        mock_selector = MockSelector.return_value

        # Default responses
        mock_poly.get_recent_quote.return_value = {"price": 100.0, "bid": 99.0, "ask": 101.0}
        mock_poly.get_historical_prices.return_value = {"prices": [100.0] * 100}

        # MDTL Quote
        mock_mdtl.snapshot_many.return_value = {
            "AAPL": {"quote": {"bid": 99.0, "ask": 101.0, "mid": 100.0, "last": 100.0}},
            "TSLA": {"quote": {"bid": 99.0, "ask": 101.0, "mid": 100.0, "last": 100.0}},
            "NVDA": {"quote": {"bid": 99.0, "ask": 101.0, "mid": 100.0, "last": 100.0}},
        }
        mock_mdtl.normalize_symbol.side_effect = lambda s: s
        mock_mdtl.daily_bars.return_value = [{"close": 100.0} for _ in range(60)]

        # Mock Option Chain - TIGHT SPREADS REQUIRED (<10%)
        # Bid 1.0, Ask 1.05 -> Spread 0.05. Price 1.025.
        # Ratio ~ 4.8% -> Safe.
        dummy_chain = []
        now = datetime.now()
        expiry = (now + timedelta(days=30)).strftime("%Y-%m-%d")
        for k in [95, 100, 105]:
            dummy_chain.append({
                "contract": f"TEST_{k}_C", "strike": k, "expiry": expiry, "right": "call",
                "greeks": {"delta": 0.5, "gamma": 0.1, "vega": 0.1, "theta": -0.1},
                "quote": {"bid": 1.0, "ask": 1.05, "mid": 1.025, "last": 1.025}
            })
            dummy_chain.append({
                "contract": f"TEST_{k}_P", "strike": k, "expiry": expiry, "right": "put",
                "greeks": {"delta": -0.5, "gamma": 0.1, "vega": 0.1, "theta": -0.1},
                "quote": {"bid": 1.0, "ask": 1.05, "mid": 1.025, "last": 1.025}
            })

        mock_mdtl.option_chain.return_value = dummy_chain
        mock_poly.get_option_chain.return_value = [] # Fallback shouldn't be hit if MDTL works

        # Mock Regime
        mock_snapshot = MagicMock()
        mock_snapshot.state = "NORMAL"
        mock_snapshot.to_dict.return_value = {"state": "NORMAL"}
        mock_snapshot.iv_rank = 50.0
        mock_regime.compute_global_snapshot.return_value = mock_snapshot
        mock_regime._default_global_snapshot.return_value = mock_snapshot
        mock_regime.compute_symbol_snapshot.return_value = mock_snapshot
        mock_regime.get_effective_regime.return_value = MagicMock(value="NORMAL")

        # Mock EV
        mock_ev = MagicMock()
        mock_ev.expected_value = 50.0
        MockCalcEV.return_value = mock_ev

        # Mock Unified Score
        mock_unified = MagicMock()
        mock_unified.score = 80.0
        mock_unified.badges = []
        mock_unified.execution_cost_dollars = 1.0
        mock_unified.components.dict.return_value = {}
        MockUnifiedScore.return_value = mock_unified

        yield {
            "universe": mock_univ,
            "selector": mock_selector,
            "unified_score": mock_unified
        }

def test_earnings_hard_reject(mock_dependencies):
    """
    Ensure Credit Strategies are rejected if earnings are within 2 days.
    """
    deps = mock_dependencies

    # 1. Setup Universe with short-dated earnings (Tomorrow)
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    deps["universe"].get_scan_candidates.return_value = [
        {"symbol": "AAPL", "earnings_date": tomorrow}
    ]

    # 2. Setup Strategy: Credit Spread
    # Note: StrategySelector logic is mocked, so we just check if it passes this step
    deps["selector"].determine_strategy.return_value = {
        "strategy": "Credit Put Spread",
        "legs": [
            {"delta_target": -0.30, "side": "sell", "type": "put"},
            {"delta_target": -0.10, "side": "buy", "type": "put"}
        ]
    }

    # 3. Run Scanner
    candidates = scan_for_opportunities(supabase_client=MagicMock())

    # 4. Assert Rejected (No candidates returned)
    assert len(candidates) == 0

def test_earnings_penalty_applied(mock_dependencies):
    """
    Ensure score is penalized if earnings are within 7 days (but > 2).
    """
    deps = mock_dependencies

    # 1. Setup Universe with earnings in 5 days
    in_5_days = (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d")
    deps["universe"].get_scan_candidates.return_value = [
        {"symbol": "TSLA", "earnings_date": in_5_days}
    ]

    # 2. Setup Strategy: Long Call (Allowed, but penalized)
    deps["selector"].determine_strategy.return_value = {
        "strategy": "Long Call",
        "legs": [
            {"delta_target": 0.50, "side": "buy", "type": "call"}
        ]
    }

    # 3. Run Scanner
    candidates = scan_for_opportunities(supabase_client=MagicMock())

    # 4. Assert Passed but Penalized
    assert len(candidates) == 1
    cand = candidates[0]
    assert cand["symbol"] == "TSLA"
    assert cand["days_to_earnings"] == 5
    assert cand["earnings_risk"] is True
    assert cand["earnings_penalty"] > 0
    # Base score mock is 80.0, penalty is 15.0 -> 65.0
    assert cand["score"] == 65.0
    assert "EARNINGS_RISK" in cand["badges"]

def test_earnings_safe(mock_dependencies):
    """
    Ensure no penalty if earnings are far away (> 7 days).
    """
    deps = mock_dependencies

    # 1. Setup Universe with earnings in 20 days
    in_20_days = (datetime.now() + timedelta(days=20)).strftime("%Y-%m-%d")
    deps["universe"].get_scan_candidates.return_value = [
        {"symbol": "NVDA", "earnings_date": in_20_days}
    ]

    # 2. Setup Strategy
    deps["selector"].determine_strategy.return_value = {
        "strategy": "Long Call",
        "legs": [
            {"delta_target": 0.50, "side": "buy", "type": "call"}
        ]
    }

    # 3. Run Scanner
    candidates = scan_for_opportunities(supabase_client=MagicMock())

    # 4. Assert Passed with NO penalty
    assert len(candidates) == 1
    cand = candidates[0]
    assert cand["days_to_earnings"] == 20
    assert cand["earnings_risk"] is False
    assert cand["earnings_penalty"] == 0.0
    assert cand["score"] == 80.0

def test_manual_symbols_no_earnings(mock_dependencies):
    """
    If running manually with symbols list, earnings map is empty (unless we implement fetching).
    Scanner should proceed without earnings logic.
    """
    deps = mock_dependencies

    deps["selector"].determine_strategy.return_value = {
        "strategy": "Long Call",
        "legs": [{"delta_target": 0.5, "side": "buy", "type": "call"}]
    }

    # Pass manual list
    candidates = scan_for_opportunities(symbols=["AAPL"])

    assert len(candidates) == 1
    cand = candidates[0]
    # Expect None for earnings data
    assert cand.get("earnings_date") is None
    assert cand.get("days_to_earnings") is None
    assert cand.get("score") == 80.0
