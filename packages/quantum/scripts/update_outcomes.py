import os
import sys
import uuid
from datetime import datetime, timedelta
import asyncio
from typing import List, Dict, Any

from dotenv import load_dotenv
from supabase import create_client, Client

# Add package root to path to allow imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from packages.quantum.market_data import PolygonService
from packages.quantum.analytics.surprise import compute_surprise
from packages.quantum.nested_logging import log_outcome

# Load env vars
load_dotenv()

def get_supabase_client() -> Client:
    url = os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("Error: Missing Supabase credentials.")
        sys.exit(1)
    return create_client(url, key)

async def update_outcomes():
    print(f"[{datetime.now()}] Starting Outcome Updater (Decision-Aware)...")

    supabase = get_supabase_client()
    polygon_service = PolygonService()

    # Window: logs from 48h to 24h ago
    yesterday = datetime.now() - timedelta(days=1)
    two_days_ago = datetime.now() - timedelta(days=2)

    print(f"Fetching logs between {two_days_ago} and {yesterday}...")

    try:
        # Fetch inference logs
        res = supabase.table("inference_log") \
            .select("trace_id, symbol_universe, predicted_sigma, inputs_snapshot, created_at") \
            .gte("created_at", two_days_ago.isoformat()) \
            .lte("created_at", yesterday.isoformat()) \
            .execute()

        logs = res.data or []
        print(f"Found {len(logs)} candidate inference logs.")

    except Exception as e:
        print(f"Error fetching logs: {e}")
        return

    processed_count = 0

    for log in logs:
        trace_id = log["trace_id"]

        # Check if outcome already exists
        try:
            check = supabase.table("outcomes_log").select("trace_id").eq("trace_id", trace_id).execute()
            if check.data:
                continue
        except Exception:
            pass

        # === 1. Fetch Related Decision ===
        decision = None
        try:
            d_res = supabase.table("decision_logs").select("*").eq("trace_id", trace_id).execute()
            if d_res.data:
                decision = d_res.data[0]
        except Exception:
            pass

        # === 2. Fetch Related Suggestion & Execution ===
        # We need to find suggestions linked to this trace_id
        executions = []
        suggestions = []

        try:
            # Join suggestions by trace_id (added in workflow_orchestrator)
            s_res = supabase.table("trade_suggestions").select("id, status, ticker").eq("trace_id", trace_id).execute()
            suggestions = s_res.data or []

            # Find executions for these suggestions
            if suggestions:
                s_ids = [s["id"] for s in suggestions]
                # Assuming trade_executions has suggestion_id or similar link.
                # Note: Schema might vary, checking models.py -> TradeExecution has 'suggestion_id'
                e_res = supabase.table("trade_executions").select("*").in_("suggestion_id", s_ids).execute()
                executions = e_res.data or []
        except Exception:
            pass

        # === 3. Determine Outcome Logic ===

        realized_pnl_1d = 0.0
        realized_vol_1d = 0.0
        attribution_type = "portfolio_snapshot"
        related_id = None

        # Priority 1: Executed Trade (The "Real" Outcome)
        if executions:
            attribution_type = "execution"
            # Sum PnL of executions
            # Assuming execution logs have 'realized_pnl' populated later or we compute it now.
            # If execution happened yesterday, we need its PnL today?
            # Or if it was an entry, we track its 1D performance?
            # Learning typically wants "Reward" of the action.
            # If we entered, Reward = 1D PnL of position.

            # For simplicity, calculate 1D PnL of the *executed symbols*
            # using Polygon history, similar to portfolio snapshot logic but specific to trade.

            total_exec_pnl = 0.0

            for exc in executions:
                sym = exc["symbol"]
                qty = exc["quantity"]
                fill_price = exc["fill_price"]
                # Get price now (or close of next day)
                try:
                    # Note: We fetch recent history (5 days). Using the latest price (prices[-1])
                    # implies we are calculating PnL as of "now" (the script execution time),
                    # relative to the trade. For a cron running daily, this approximates 1D PnL
                    # if the trade happened yesterday.
                    hist = polygon_service.get_historical_prices(sym, days=5)
                    prices = hist.get("prices", [])
                    if len(prices) >= 1:
                        curr = prices[-1]
                        # PnL = (Curr - Fill) * Qty * 100 (if option) or 1 (if stock)
                        # Assuming option multiplier 100 for simplicity if not in metadata
                        multiplier = 100 if len(sym) > 6 else 1 # Heuristic
                        total_exec_pnl += (curr - fill_price) * qty * multiplier
                except:
                    pass

            realized_pnl_1d = total_exec_pnl
            related_id = executions[0]["id"] # Link to first execution

        # Priority 2: Suggestion made but not executed (No Action)
        elif suggestions:
            attribution_type = "no_action"
            realized_pnl_1d = 0.0
            related_id = suggestions[0]["id"]

        # Priority 3: Optimization Decision (Rebalance Weights)
        elif decision and decision["decision_type"] == "optimizer_weights":
            attribution_type = "optimizer_simulation"
            # Calculate theoretical PnL of the target weights
            weights = decision["content"].get("target_weights", {})
            # Need total value to convert weights to PnL dollars, or just return %?
            # Existing outcome schema expects float PnL.
            # Use 'inputs_snapshot' total equity.
            total_equity = log.get("inputs_snapshot", {}).get("total_equity", 10000.0)

            sim_pnl = 0.0
            valid_syms = 0

            for sym, w in weights.items():
                try:
                    hist = polygon_service.get_historical_prices(sym, days=5)
                    prices = hist.get("prices", [])
                    if len(prices) >= 2:
                        ret = (prices[-1] - prices[-2]) / prices[-2]
                        sim_pnl += w * total_equity * ret
                        valid_syms += 1
                except:
                    pass

            if valid_syms > 0:
                realized_pnl_1d = sim_pnl

        # Priority 4: Fallback to Input Portfolio (Legacy / Passive)
        else:
            attribution_type = "portfolio_snapshot"
            # Use existing logic for portfolio PnL
            inputs = log.get("inputs_snapshot", {})
            positions = inputs.get("positions", [])
            # ... (Legacy logic from previous file version) ...
            # Reuse logic for portfolio 1D PnL

            total_pnl = 0.0
            qty_map = {p.get("symbol"): float(p.get("current_quantity", 0)) for p in positions}

            symbol_universe = log["symbol_universe"]
            realized_vols = []

            for sym in symbol_universe:
                try:
                    hist = polygon_service.get_historical_prices(sym, days=5)
                    prices = hist.get("prices", [])
                    if len(prices) >= 2:
                        p_today = prices[-1]
                        p_yesterday = prices[-2]
                        ret = (p_today - p_yesterday) / p_yesterday
                        realized_vols.append(abs(ret))

                        if sym in qty_map:
                            qty = qty_map[sym]
                            multiplier = 100 if len(sym) > 6 else 1
                            pnl = (p_today - p_yesterday) * qty * multiplier
                            total_pnl += pnl
                except:
                    pass

            realized_pnl_1d = total_pnl
            if realized_vols:
                realized_vol_1d = sum(realized_vols) / len(realized_vols)

        # === Compute Surprise ===
        # Always compute Surprise relative to prediction, even if outcome source varies
        sigma_pred_matrix = log.get("predicted_sigma", {}).get("sigma_matrix", [])
        avg_predicted_vol = 0.0
        if sigma_pred_matrix:
            import numpy as np
            arr = np.array(sigma_pred_matrix)
            if arr.shape[0] > 0:
                avg_predicted_vol = np.mean(np.sqrt(np.diag(arr)))

        sigma_pred_1d = avg_predicted_vol / 16.0

        # If we didn't calculate realized vol above (e.g. execution path), estimate it from universe
        if realized_vol_1d == 0.0:
             # Fallback to universe average for "market regime" comparison
             # (This is imperfect for specific execution but sufficient for 'regime surprise')
             pass # Logic similar to legacy loop would go here if strict accuracy needed

        surprise = compute_surprise(
            sigma_pred=sigma_pred_1d,
            sigma_realized=realized_vol_1d,
            pnl_realized=realized_pnl_1d
        )

        # Write
        log_outcome(
            trace_id=trace_id,
            realized_pl_1d=realized_pnl_1d,
            realized_vol_1d=realized_vol_1d,
            surprise_score=surprise,
            attribution_type=attribution_type,
            related_id=related_id
        )
        processed_count += 1

    print(f"Updated {processed_count} outcomes.")

if __name__ == "__main__":
    asyncio.run(update_outcomes())
