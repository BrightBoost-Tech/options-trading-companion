
import time
import numpy as np
from packages.quantum.analytics.factors import calculate_trend, calculate_rsi, calculate_volatility

def benchmark():
    # Simulate a long history (e.g., 10 years of daily data)
    N = 2500
    prices = list(np.random.random(N) * 100 + 100)

    iterations = 5000

    start_time = time.time()
    for _ in range(iterations):
        calculate_trend(prices)
    trend_time = time.time() - start_time
    print(f"calculate_trend: {trend_time:.4f}s per {iterations} calls")

    start_time = time.time()
    for _ in range(iterations):
        calculate_rsi(prices, period=14)
    rsi_time = time.time() - start_time
    print(f"calculate_rsi: {rsi_time:.4f}s per {iterations} calls")

    start_time = time.time()
    for _ in range(iterations):
        calculate_volatility(prices, window=30)
    vol_time = time.time() - start_time
    print(f"calculate_volatility: {vol_time:.4f}s per {iterations} calls")

if __name__ == "__main__":
    print("Benchmarking original factors.py...")
    benchmark()
