import argparse
import asyncio
import os
import sys
from datetime import date, timedelta, datetime
from typing import List, Optional

# Add repo root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))
# Add package root to path (for internal imports like 'core', 'market_data')
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dotenv import load_dotenv
from supabase import create_client, Client

# Load environment variables
load_dotenv()

# Backend imports
from packages.quantum.optimizer import OptimizationRequest, PositionInput, optimize_portfolio
# Ensure dependencies (e.g. cryptography for security.py) are available
try:
    from packages.quantum.models import Holding
except ImportError:
    pass

def get_supabase_client() -> Client:
    url = os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("Error: Missing Supabase credentials (NEXT_PUBLIC_SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY).")
        # Do not exit, try to continue if mocking or just fail later
        # sys.exit(1)
    return create_client(url, key)

async def run_replay(args):
    try:
        supabase = get_supabase_client()
    except Exception as e:
        print(f"Failed to init Supabase: {e}")
        return

    user_id = args.user_id
    start_date = datetime.strptime(args.start_date, "%Y-%m-%d").date()
    end_date = datetime.strptime(args.end_date, "%Y-%m-%d").date()
    profile = args.profile

    print(f"Starting Replay for User {user_id} from {start_date} to {end_date} (Profile: {profile})")

    current_date = start_date
    delta = timedelta(days=1)

    total_days = 0
    different_recs = 0
    sum_sharpe_diff = 0.0
    sum_return_diff = 0.0

    while current_date <= end_date:
        # 1. Fetch Snapshot for this day (latest one on or before day end)
        day_start = current_date.isoformat() + "T00:00:00"
        day_end = current_date.isoformat() + "T23:59:59"

        try:
            res = supabase.table("portfolio_snapshots") \
                .select("*") \
                .eq("user_id", user_id) \
                .gte("created_at", day_start) \
                .lte("created_at", day_end) \
                .order("created_at", desc=True) \
                .limit(1) \
                .execute()

            snapshot = res.data[0] if res.data else None
        except Exception as e:
            print(f"Error fetching snapshot for {current_date}: {e}")
            current_date += delta
            continue

        if not snapshot:
            # print(f"[{current_date}] No snapshot found.")
            current_date += delta
            continue

        print(f"[{current_date}] Processing snapshot {snapshot['id']}...")

        # 2. Reconstruct OptimizationRequest
        # Assuming 'positions' column stores list of holdings
        positions_data = snapshot.get("positions", [])
        if not positions_data:
             positions_data = snapshot.get("holdings", [])

        pos_inputs = []

        # Use buying_power as cash proxy if available
        stored_bp = float(snapshot.get("buying_power", 0.0))

        for p in positions_data:
            sym = p.get("symbol")
            if not sym: continue

            qty = float(p.get("quantity", 0) or p.get("current_quantity", 0))
            price = float(p.get("current_price", 0) or p.get("price", 0))
            val = float(p.get("current_value", 0) or p.get("value", 0))
            if val == 0 and qty > 0 and price > 0:
                val = qty * price

            pos_inputs.append(PositionInput(
                symbol=sym,
                current_quantity=qty,
                current_price=price,
                current_value=val
            ))

        req = OptimizationRequest(
            positions=pos_inputs,
            cash_balance=stored_bp,
            profile=profile,
            nested_enabled=False,
            nested_shadow=True # Enable Shadow Mode!
        )

        # 3. Run Optimization (Internal)
        try:
            # We call the endpoint function as a coroutine
            # Note: optimize_portfolio uses 'user_id' for session state lookup.
            result = await optimize_portfolio(req, user_id=user_id)

            # 4. Analyze Diagnostics
            diag = result.get("diagnostics", {})
            shadow = diag.get("nested_shadow", {})

            if not shadow:
                print("  Warning: No shadow diagnostics returned.")
                current_date += delta
                continue

            base_m = shadow.get("baseline_metrics", {})
            nest_m = shadow.get("nested_metrics", {})

            sharpe_diff = nest_m.get("sharpe_ratio", 0) - base_m.get("sharpe_ratio", 0)
            ret_diff = nest_m.get("expected_return", 0) - base_m.get("expected_return", 0)

            base_trades = shadow.get("baseline_trades", [])
            nest_trades = shadow.get("nested_trades", [])

            # Simple diff check
            def fmt_trades(ts):
                return sorted([f"{t['action']}:{t['symbol']}" for t in ts])

            is_diff = (fmt_trades(base_trades) != fmt_trades(nest_trades))

            sum_sharpe_diff += sharpe_diff
            sum_return_diff += ret_diff
            total_days += 1
            if is_diff:
                different_recs += 1

            print(f"  Diff: Sharpe {sharpe_diff:.4f}, Ret {ret_diff:.4f}, Trades Changed: {is_diff}")
            if is_diff:
                print(f"    Baseline: {fmt_trades(base_trades)}")
                print(f"    Nested:   {fmt_trades(nest_trades)}")

        except Exception as e:
            print(f"  Error running optimizer: {e}")

        current_date += delta

    print("\n--- REPLAY SUMMARY ---")
    print(f"Days Processed: {total_days}")
    if total_days > 0:
        print(f"Avg Sharpe Diff: {sum_sharpe_diff/total_days:.4f}")
        print(f"Avg Return Diff: {sum_return_diff/total_days:.6f}")
        print(f"Days with Different Trades: {different_recs} ({different_recs/total_days*100:.1f}%)")
    else:
        print("No days processed.")

def main():
    parser = argparse.ArgumentParser(description="Replay Nested Shadow Optimization")
    parser.add_argument("--user-id", required=True, help="User UUID")
    parser.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--profile", default="balanced", help="Risk profile")

    args = parser.parse_args()

    asyncio.run(run_replay(args))

if __name__ == "__main__":
    main()
