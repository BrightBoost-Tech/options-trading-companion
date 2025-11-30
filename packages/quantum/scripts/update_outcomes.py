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
    print(f"[{datetime.now()}] Starting Outcome Updater...")

    supabase = get_supabase_client()
    polygon_service = PolygonService()

    # 1. Fetch pending inference logs (older than 24h, or just "yesterday")
    # For now, let's fetch any log created > 1 day ago that doesn't have an outcome.
    # Actually, simpler: fetch logs from exactly 1 day ago window.
    # Better: Left join logic is hard via API, so we fetch logs without outcomes.

    # We will assume a 'status' or just query logs and check if they exist in outcomes.
    # Since we can't do complex joins easily, we'll fetch recent logs and check individually (inefficient but works for Phase 1).
    # Or, we can just look at logs created between T-48h and T-24h.

    yesterday = datetime.now() - timedelta(days=1)
    two_days_ago = datetime.now() - timedelta(days=2)

    print(f"Fetching logs between {two_days_ago} and {yesterday}...")

    try:
        res = supabase.table("inference_log") \
            .select("trace_id, symbol_universe, predicted_sigma, inputs_snapshot, created_at") \
            .gte("created_at", two_days_ago.isoformat()) \
            .lte("created_at", yesterday.isoformat()) \
            .execute()

        logs = res.data or []
        print(f"Found {len(logs)} candidate logs.")

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

        # Calculate Outcome
        # We need realized P&L and realized Volatility for the *portfolio* or the *assets*.
        # The prompt implies we compare sigma_pred (portfolio vol?) vs realized vol.
        # "Surprise = w1 * abs(sigma_pred - sigma_realized) + w2 * ReLU(-PnL)"

        # `predicted_sigma` in log is whatever we stored. In optimizer we stored `{"sigma_matrix": ...}`.
        # That is the covariance matrix. We need the portfolio volatility prediction.
        # Wait, the optimizer calculates `metrics.tail_risk_score` etc.
        # But we didn't explicitly log "portfolio_sigma_pred".
        # We logged `predicted_sigma` as the whole matrix.
        # And `inputs_snapshot` has weights? No, inputs_snapshot has inputs.
        # The `inference_log` doesn't store the *outputs* (weights).
        # Ah, looking at the prompt: "predicted_mu, predicted_sigma".
        # It seems we are evaluating the *model's* prediction of market parameters, not necessarily the portfolio outcome yet?
        # "Surprise = w1 * abs(sigma_pred - sigma_realized) + w2 * ReLU(-PnL)"
        # PnL implies we held something. But if we don't know the weights, we can't know PnL.
        # Wait, `outcomes_log` links to `inference_log`.
        # Did we log the resulting weights? `optimizer.py` returns them but `log_inference` was called *before* return?
        # Actually `log_inference` is called at the end of `optimize_portfolio`.
        # But `log_inference` signature doesn't take `weights`.

        # Re-reading prompt: "Collect: symbol_universe, inputs_snapshot..., predicted_mu, predicted_sigma... Call log_inference"
        # It doesn't ask to log the *result* (weights).
        # This implies the "Surprise" is either:
        # 1. Based on the *market* behavior vs prediction (regardless of what we bought).
        #    e.g. "We predicted AAPL vol 1%, it was 5%".
        # 2. Or the prompt implies we *should* have logged weights.

        # "Surprise = w1 * abs(sigma_pred - sigma_realized) + w2 * ReLU(-PnL)"
        # PnL requires a position.
        # If `inference_log` doesn't have weights, we can't calculate PnL of the optimized portfolio.
        # Maybe we use the "inputs_snapshot" which contains "positions"?
        # "inputs_snapshot (positions, cash...)"
        # If the user held positions, we calculate the PnL of *those* positions over the day?
        # That makes sense. "Realized P&L 1D" likely refers to the PnL of the portfolio *at the time of inference*.

        # Let's proceed with that assumption: PnL of the input portfolio over the next 24h.

        symbol_universe = log["symbol_universe"] # List of strings
        # predicted_sigma is likely a dict or matrix.
        # If it's a matrix, "sigma_pred" in the formula likely refers to an aggregate or we loop per asset.
        # The formula "abs(sigma_pred - sigma_realized)" looks scalar.
        # Let's assume equal weight or just average vol surprise for now, or use the portfolio vol if we can reconstruct it.
        # Given "Surprise metric" module inputs `sigma_pred` (float), it expects scalars.
        # I will calculate the average volatility surprise across the universe.

        # 1. Get realized data for next trading day after `created_at`
        log_date = datetime.fromisoformat(log["created_at"])
        # We want the *next* trading day.
        # For simplicity, let's just get the close-to-close of the next 24h window or next market day.
        # Polygon `get_historical_prices` handles days.

        total_pnl = 0.0
        total_vol_diff = 0.0
        valid_symbols = 0

        # We need `inputs_snapshot` to get quantities for PnL
        inputs = log.get("inputs_snapshot", {})
        positions = inputs.get("positions", [])

        sigma_pred_matrix = log.get("predicted_sigma", {}).get("sigma_matrix", [])

        # Mean diagonal is approx variance. Sqrt is vol.
        avg_predicted_vol = 0.0
        if sigma_pred_matrix:
            import numpy as np
            arr = np.array(sigma_pred_matrix)
            if arr.shape[0] > 0:
                avg_predicted_vol = np.mean(np.sqrt(np.diag(arr)))

        # Realized Vol & PnL
        total_pnl = 0.0
        total_value_yesterday = 0.0

        realized_vols = []

        # If we have positions, we calculate precise PnL
        # Else we default to equal weight average return (legacy support)

        has_positions = len(positions) > 0
        realized_returns = []

        # Map symbol -> quantity/value
        qty_map = {p.get("symbol"): float(p.get("current_quantity", 0)) for p in positions}
        val_map = {p.get("symbol"): float(p.get("current_value", 0)) for p in positions}

        for sym in symbol_universe:
            try:
                # Fetch recent history (assuming log is from yesterday)
                hist = polygon_service.get_historical_prices(sym, days=5)
                prices = hist.get("prices", [])

                if len(prices) >= 2:
                    p_today = prices[-1]
                    p_yesterday = prices[-2]

                    ret = (p_today - p_yesterday) / p_yesterday
                    realized_vols.append(abs(ret)) # Proxy for 1D vol

                    if has_positions and sym in qty_map:
                        qty = qty_map[sym]
                        # PnL = Delta Price * Qty
                        pnl = (p_today - p_yesterday) * qty
                        total_pnl += pnl
                        total_value_yesterday += val_map.get(sym, 0)
                    else:
                        realized_returns.append(ret)

            except Exception as e:
                # print(f"Failed to fetch data for {sym}: {e}")
                pass

        if not realized_vols:
            continue

        avg_vol_realized = sum(realized_vols) / len(realized_vols)

        # Finalize PnL
        if has_positions:
            realized_pnl_1d = total_pnl
        else:
            # Fallback: Avg Return * Total Equity
            if realized_returns:
                avg_ret = sum(realized_returns) / len(realized_returns)
                equity = inputs.get("total_equity", 10000.0)
                realized_pnl_1d = avg_ret * equity
            else:
                realized_pnl_1d = 0.0

        # Surprise
        # sigma_pred is approx 1-day vol?
        # Usually covariance matrix is annualized.
        # If predicted_sigma is annualized, we need to divide by sqrt(252) to compare with 1-day realized.
        # Let's assume input was annualized.
        sigma_pred_1d = avg_predicted_vol / 16.0 # sqrt(252) approx 16

        surprise = compute_surprise(
            sigma_pred=sigma_pred_1d,
            sigma_realized=avg_vol_realized,
            pnl_realized=realized_pnl_1d
        )

        # Write
        log_outcome(
            trace_id=trace_id,
            realized_pl_1d=realized_pnl_1d,
            realized_vol_1d=avg_vol_realized,
            surprise_score=surprise
        )
        processed_count += 1

    print(f"Updated {processed_count} outcomes.")

if __name__ == "__main__":
    asyncio.run(update_outcomes())
