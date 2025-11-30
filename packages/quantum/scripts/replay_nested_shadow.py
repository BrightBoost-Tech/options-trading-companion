import argparse
import asyncio
import os
import sys
import json
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Any

# Add package root to path
# We need to add the repo root (../../..) so "packages.quantum..." imports work
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))
# We ALSO need packages/quantum (../..) so internal imports like "core" work
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from dotenv import load_dotenv
from supabase import create_client

from packages.quantum.optimizer import optimize_portfolio, OptimizationRequest, PositionInput

# Load env vars
load_dotenv()

def get_supabase_client():
    url = os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("Error: Missing Supabase credentials.")
        sys.exit(1)
    return create_client(url, key)

async def main():
    parser = argparse.ArgumentParser(description="Replay portfolio optimization in shadow mode.")
    parser.add_argument("--user-id", required=True, help="User ID to replay for")
    parser.add_argument("--start-date", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--profile", default="aggressive", help="Risk profile")
    args = parser.parse_args()

    user_id = args.user_id
    start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
    end_date = datetime.strptime(args.end_date, "%Y-%m-%d")

    print(f"Replaying for User {user_id} from {start_date.date()} to {end_date.date()} in Shadow Mode...")

    supabase = get_supabase_client()

    current_date = start_date
    results_log = []

    while current_date <= end_date:
        date_str = current_date.strftime("%Y-%m-%d")
        print(f"Processing {date_str}...", end=" ", flush=True)

        try:
            # 1. Fetch Snapshot
            res = supabase.table("portfolio_snapshots") \
                .select("*") \
                .eq("user_id", user_id) \
                .gte("created_at", date_str + "T00:00:00") \
                .lte("created_at", date_str + "T23:59:59") \
                .order("created_at", desc=True) \
                .limit(1) \
                .execute()

            snapshots = res.data
            if not snapshots:
                print("No snapshot.")
                current_date += timedelta(days=1)
                continue

            snapshot_data = snapshots[0]
            holdings = snapshot_data.get("holdings", [])

            positions = []
            cash_balance = 0.0

            for h in holdings:
                sym = h.get("symbol")
                qty = float(h.get("quantity", 0))
                price = float(h.get("current_price", 0))
                val = qty * price

                if sym in ["USD", "CUR:USD", "CASH"]:
                    cash_balance += val
                    positions.append(PositionInput(
                        symbol=sym,
                        current_value=val,
                        current_quantity=qty,
                        current_price=price
                    ))
                else:
                    positions.append(PositionInput(
                        symbol=sym,
                        current_value=val,
                        current_quantity=qty,
                        current_price=price
                    ))

            if not positions:
                print("Empty portfolio.")
                current_date += timedelta(days=1)
                continue

            req = OptimizationRequest(
                positions=positions,
                risk_aversion=1.0 if args.profile == "aggressive" else 2.0,
                skew_preference=0.0,
                cash_balance=cash_balance,
                profile=args.profile,
                nested_shadow=True
            )

            # 2. Run Optimizer
            result = await optimize_portfolio(req, user_id=user_id)

            # 3. Collect Metrics
            diag = result.get("diagnostics", {})
            shadow = diag.get("nested_shadow", {})

            m_base = shadow.get("baseline_metrics", {})
            m_nest = shadow.get("nested_metrics", {})

            diff_er = m_nest.get("expected_return", 0) - m_base.get("expected_return", 0)
            diff_sr = m_nest.get("sharpe_ratio", 0) - m_base.get("sharpe_ratio", 0)

            t_base = len(shadow.get("baseline_trades", []))
            t_nest = len(shadow.get("nested_trades", []))

            crisis_triggered = diag.get("nested", {}).get("crisis_mode_triggered_by") is not None

            print(f"Diff ER: {diff_er:.4f}, Diff SR: {diff_sr:.2f}, Trades: {t_base}->{t_nest}, Crisis: {crisis_triggered}")

            results_log.append({
                "date": date_str,
                "diff_er": diff_er,
                "diff_sr": diff_sr,
                "trades_base": t_base,
                "trades_nest": t_nest,
                "crisis": 1 if crisis_triggered else 0
            })

        except Exception as e:
            print(f"Error: {e}")
            # import traceback
            # traceback.print_exc()

        current_date += timedelta(days=1)

    # Summary Table
    if results_log:
        avg_diff_er = np.mean([r["diff_er"] for r in results_log])
        avg_diff_sr = np.mean([r["diff_sr"] for r in results_log])
        total_crisis = sum([r["crisis"] for r in results_log])

        print("\n--- Summary ---")
        print(f"Avg Diff Expected Return: {avg_diff_er:.6f}")
        print(f"Avg Diff Sharpe Ratio:    {avg_diff_sr:.4f}")
        print(f"Total Crisis Days:        {total_crisis}")
        print("----------------")
    else:
        print("\nNo days processed.")

if __name__ == "__main__":
    asyncio.run(main())
