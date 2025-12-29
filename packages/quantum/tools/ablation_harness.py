import argparse
import os
import sys
import uuid
import time
import random
import statistics
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta

# Ensure packages.quantum is in path
# Intended usage: python -m packages.quantum.tools.ablation_harness
# However, for standalone execution flexibility, we keep this path adjustment.
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from packages.quantum.market_data import PolygonService
from packages.quantum.services.historical_simulation import HistoricalCycleService

# Configuration Matrix
CONFIGS = {
    "baseline": {
        "QUANT_AGENTS_ENABLED": "false",
        "NESTED_GLOBAL_ENABLED": "false",
        "NESTED_L0_ENABLED": "false",
        "NESTED_L1_ENABLED": "false",
        "NESTED_L2_ENABLED": "false",
        "ENABLE_HISTORICAL_NESTED_LEARNING": "false"
    },
    "full_agents": {
        "QUANT_AGENTS_ENABLED": "true",
        "NESTED_GLOBAL_ENABLED": "true",
        "NESTED_L0_ENABLED": "true",
        "NESTED_L1_ENABLED": "true",
        "NESTED_L2_ENABLED": "true",
        "ENABLE_HISTORICAL_NESTED_LEARNING": "true"
    }
}

class MockPolygonService:
    def __init__(self, mode="random"):
        self.mode = mode

    def get_historical_prices(self, symbol, days, to_date=None):
        # Generate deterministic mock data based on symbol hash or seed
        seed = sum(ord(c) for c in symbol)
        rng = random.Random(seed)

        base_price = 100.0 + (seed % 50)
        dates = []
        prices = []

        start_date = to_date - timedelta(days=days) if to_date else datetime.now() - timedelta(days=days)

        trend = rng.choice(["up", "down", "flat"])

        for i in range(days):
            d = start_date + timedelta(days=i)
            dates.append(d.strftime("%Y-%m-%d"))

            noise = rng.uniform(-2, 2)
            if trend == "up":
                base_price += 0.2
            elif trend == "down":
                base_price -= 0.2

            prices.append(max(1.0, base_price + noise))

        return {
            "dates": dates,
            "prices": prices,
            "volumes": [1000000] * days
        }

def run_simulation(config_name, env_vars, symbols, days, seed, mock_mode=True):
    # Set env vars
    original_env = os.environ.copy()
    os.environ.update(env_vars)

    results = {
        "suggestions_count": 0,
        "veto_count": 0,
        "scores": [],
        "pnl": [],
        "exec_costs": []
    }

    try:
        # Initialize Service with Mock
        poly_service = MockPolygonService() if mock_mode else None

        # We need to suppress the check for Polygon API key if we are mocking
        if mock_mode:
            with patch("packages.quantum.market_data.PolygonService", return_value=poly_service):
                 service = HistoricalCycleService(polygon_service=poly_service)
        else:
             service = HistoricalCycleService(polygon_service=poly_service)

        # Run cycle for each symbol
        for symbol in symbols:
            res = service.run_cycle(
                cursor_date_str=(datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d"),
                symbol=symbol,
                mode="random" if seed else "deterministic",
                seed=seed
            )

            if res.get("status") in ["normal_exit", "forced_exit"]:
                results["suggestions_count"] += 1
                results["pnl"].append(res.get("pnl", 0.0))

                if "convictionAtEntry" in res:
                    results["scores"].append(res["convictionAtEntry"])

                if "attribution" in res:
                    drag = res["attribution"].get("execution_drag", 0.0)
                    results["exec_costs"].append(abs(drag))

            elif res.get("status") == "no_entry":
                # Implicit veto or just no signal
                pass

    finally:
        # Restore env
        os.environ.clear()
        os.environ.update(original_env)

    return results

def print_table(rows, headers):
    # Calculate column widths
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(val)))

    # Format string
    fmt = "  ".join([f"{{:<{w}}}" for w in col_widths])

    # Print Header
    print(fmt.format(*headers))
    print("  ".join(["-" * w for w in col_widths]))

    # Print Rows
    for row in rows:
        print(fmt.format(*[str(r) for r in row]))

def main():
    parser = argparse.ArgumentParser(description="Quant Agents Ablation Harness")
    parser.add_argument("--window", type=str, default="midday_entry", help="Trading window (e.g. midday_entry)")
    parser.add_argument("--symbols", type=int, default=10, help="Number of symbols to simulate")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--matrix", action="store_true", help="Run full matrix of agent toggles")
    parser.add_argument("--mock", action="store_true", default=True, help="Use mock data (no API)")

    args = parser.parse_args()

    # Generate mock universe
    rng = random.Random(args.seed)
    base_universe = ["SPY", "QQQ", "IWM", "AAPL", "MSFT", "TSLA", "AMD", "NVDA", "AMZN", "GOOGL"]
    universe = [rng.choice(base_universe) for _ in range(args.symbols)]

    # Configs to run
    run_configs = ["baseline", "full_agents"]

    # Copy generic configs locally to avoid global mutation
    local_configs = {k: v.copy() for k, v in CONFIGS.items()}

    # If matrix, add more configs (e.g. toggle L2 off only)
    if args.matrix:
        local_configs["no_l2"] = {**local_configs["full_agents"], "NESTED_L2_ENABLED": "false"}
        local_configs["no_l1"] = {**local_configs["full_agents"], "NESTED_L1_ENABLED": "false"}
        run_configs.extend(["no_l2", "no_l1"])

    final_table = []

    print(f"Running Ablation Harness | Window: {args.window} | Symbols: {args.symbols} | Seed: {args.seed}")

    for cfg_name in run_configs:
        print(f"Running config: {cfg_name}...")
        env_vars = local_configs[cfg_name].copy()

        # Patch keys that might cause startup errors if missing
        env_vars["ENCRYPTION_KEY"] = "dummy_key_for_test_dummy_key_for_test_dummy="
        env_vars["SUPABASE_URL"] = "https://dummy.supabase.co"
        env_vars["SUPABASE_SERVICE_ROLE_KEY"] = "dummy_key"

        metrics = run_simulation(cfg_name, env_vars, universe, args.symbols, args.seed, mock_mode=args.mock)

        avg_score = statistics.mean(metrics["scores"]) if metrics["scores"] else 0.0
        avg_pnl = statistics.mean(metrics["pnl"]) if metrics["pnl"] else 0.0
        avg_drag = statistics.mean(metrics["exec_costs"]) if metrics["exec_costs"] else 0.0

        # Veto rate: (total_runs - suggestions) / total_runs
        veto_rate = (args.symbols - metrics["suggestions_count"]) / args.symbols if args.symbols > 0 else 0.0

        final_table.append([
            cfg_name,
            metrics["suggestions_count"],
            f"{veto_rate:.1%}",
            f"{avg_score:.2f}",
            f"${avg_pnl:.2f}",
            f"${avg_drag:.2f}"
        ])

    # Print Table
    headers = ["Config", "Suggestions", "Veto Rate", "Avg Score", "Avg PnL", "Avg Drag"]
    print("\n=== Ablation Results ===")
    print_table(final_table, headers)

if __name__ == "__main__":
    main()
