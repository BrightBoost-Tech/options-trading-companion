import sys
import os
from unittest.mock import MagicMock

# Mock dependencies BEFORE importing the service
sys.modules["supabase"] = MagicMock()
sys.modules["numpy"] = MagicMock()
sys.modules["packages.quantum.market_data"] = MagicMock()
sys.modules["packages.quantum.market_data.PolygonService"] = MagicMock()

# Add the package root to sys.path to allow imports
current_dir = os.path.dirname(os.path.abspath(__file__))
# current is packages/quantum/scripts
# we want root of repo to access 'packages'
# packages/quantum/scripts -> packages/quantum -> packages -> root
repo_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
sys.path.append(repo_root)

# Also add packages/quantum to path if needed for relative imports within the package
quantum_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.append(quantum_root)

try:
    from packages.quantum.services.universe_service import UniverseService
except ImportError as e:
    print(f"Failed to import UniverseService: {e}")
    # Try adding parent directory of packages/quantum
    sys.path.append(os.path.dirname(quantum_root))
    try:
        from packages.quantum.services.universe_service import UniverseService
    except ImportError as e2:
        print(f"Failed again: {e2}")
        sys.exit(1)

def test_sanitize():
    test_cases = [
        (
            {"market_cap": 12345.67, "symbol": "AAPL"},
            {"market_cap": 12345, "symbol": "AAPL"},
            "Float truncation"
        ),
        (
            {"avg_volume_30d": "1000.5", "sector": "Tech"},
            {"avg_volume_30d": 1000, "sector": "Tech"},
            "String float truncation"
        ),
        (
            {"liquidity_score": 99.9, "symbol": "GOOD"},
            {"liquidity_score": 99, "symbol": "GOOD"},
            "Liquidity score int cast"
        ),
        (
            # Key "open_interest" is in INT_LIKE_KEYS
            {"open_interest": None, "symbol": "TSLA"},
            {"symbol": "TSLA"},
            "None value omission"
        ),
        (
            {"volume": 500, "other": "data"},
            {"volume": 500, "other": "data"},
            "Integer preservation"
        ),
        (
            {"market_cap": "invalid", "symbol": "MSFT"},
            {"symbol": "MSFT"}, # Should be omitted
            "Invalid string omission"
        )
    ]

    print("Running integration smoke tests for UniverseService.sanitize_metrics...")
    passed = 0
    for input_dict, expected, desc in test_cases:
        # Use the actual static method
        result = UniverseService.sanitize_metrics(input_dict)
        if result == expected:
            print(f"[PASS] {desc}")
            passed += 1
        else:
            print(f"[FAIL] {desc}")
            print(f"  Input:    {input_dict}")
            print(f"  Expected: {expected}")
            print(f"  Got:      {result}")

    if passed == len(test_cases):
        print("\nAll tests passed!")
    else:
        print("\nSome tests failed.")
        sys.exit(1)

if __name__ == "__main__":
    test_sanitize()
