import unittest
import time
import random
from typing import List, Dict, Any
from packages.quantum.options_scanner import _select_legs_from_chain

class TestOptionsScannerOptimization(unittest.TestCase):

    def generate_synthetic_chain(self, n_contracts=100) -> tuple[List[Dict], List[Dict]]:
        # Generate monotonic deltas
        # Calls: Strike increases, Delta decreases (0.95 -> 0.05)
        # Puts: Strike increases, Abs(Delta) increases (0.05 -> 0.95) -> Delta (-0.05 -> -0.95)

        calls = []
        puts = []
        start_strike = 100.0
        strike_step = 2.5

        for i in range(n_contracts):
            strike = start_strike + (i * strike_step)

            # Linear approximation for delta
            # Calls: 0.95 at i=0, 0.05 at i=n
            call_delta = 0.95 - (0.90 * (i / n_contracts))

            # Puts: -0.05 at i=0, -0.95 at i=n
            put_delta = -0.05 - (0.90 * (i / n_contracts))

            # Randomize slightly but keep sorted for bisect validation
            # Actually, to test bisect, we need strictly sorted key values?
            # Market data is roughly sorted. Let's keep it strictly monotonic for the baseline test.

            contract_base = {
                "strike": strike,
                "expiry": "2023-12-15",
                "contract": f"SYM{int(strike)}",
                "quote": {"bid": 1.0, "ask": 1.1, "mid": 1.05},
                # Greeks moved out to avoid shared reference issues
            }

            c = contract_base.copy()
            c["type"] = "call"
            c["greeks"] = {
                "delta": call_delta,
                "gamma": 0.05, "vega": 0.1, "theta": -0.05
            }
            calls.append(c)

            p = contract_base.copy()
            p["type"] = "put"
            p["greeks"] = {
                "delta": put_delta,
                "gamma": 0.05, "vega": 0.1, "theta": -0.05
            }
            puts.append(p)

        return calls, puts

    def test_correctness(self):
        calls, puts = self.generate_synthetic_chain(100)

        # Test Case 1: Target Delta 0.30 for Call
        # Expected: find contract with delta closest to 0.30
        leg_defs = [{"delta_target": 0.30, "side": "buy", "type": "call"}]
        current_price = 150.0

        legs, cost = _select_legs_from_chain(calls, puts, leg_defs, current_price)
        selected_delta = legs[0]["delta"]

        # Validate using slow method (min scan)
        best_diff = float('inf')
        best_d = None
        for c in calls:
            d = c["greeks"]["delta"]
            diff = abs(d - 0.30)
            if diff < best_diff:
                best_diff = diff
                best_d = d

        self.assertAlmostEqual(selected_delta, best_d, places=5, msg="Call selection mismatch")

        # Test Case 2: Target Delta 0.30 for Put (Abs delta)
        # Puts have negative delta. Target 0.30 means finding delta closest to -0.30 or +0.30?
        # Logic uses abs(abs(delta) - target). So -0.30 is closest to target 0.30.
        leg_defs = [{"delta_target": 0.30, "side": "buy", "type": "put"}]
        legs, cost = _select_legs_from_chain(calls, puts, leg_defs, current_price)
        selected_delta = legs[0]["delta"]

        best_diff = float('inf')
        best_d = None
        for c in puts:
            d = c["greeks"]["delta"]
            diff = abs(abs(d) - 0.30)
            if diff < best_diff:
                best_diff = diff
                best_d = d

        self.assertAlmostEqual(selected_delta, best_d, places=5, msg="Put selection mismatch")

    def test_benchmark(self):
        calls, puts = self.generate_synthetic_chain(200)
        leg_defs = [
            {"delta_target": 0.30, "side": "buy", "type": "call"},
            {"delta_target": 0.30, "side": "buy", "type": "put"}
        ]
        current_price = 150.0

        start_time = time.time()
        iterations = 5000
        for _ in range(iterations):
            _select_legs_from_chain(calls, puts, leg_defs, current_price)
        end_time = time.time()

        duration = end_time - start_time
        print(f"\nBenchmark (Original): {iterations} iters in {duration:.4f}s")
        print(f"Avg per call: {(duration/iterations)*1000:.4f}ms")

if __name__ == '__main__':
    unittest.main()
