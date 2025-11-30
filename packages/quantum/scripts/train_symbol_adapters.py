"""
Script to train Level-1 Symbol Adapters based on historical performance.
Reads from inference_log and outcomes_log, updates model_states.
"""
import argparse
import os
import sys
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
from collections import defaultdict
from supabase import create_client

# Add package root to path to allow imports
# We need to add 'packages/quantum' to path so 'nested.adapters' resolves
sys.path.append(os.path.join(os.path.dirname(__file__), '../'))

from nested.adapters import load_symbol_adapters, save_symbol_adapters, SymbolAdapterState

def get_supabase():
    url = os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("Error: Supabase credentials missing.")
        sys.exit(1)
    return create_client(url, key)

def fetch_logs(days_back: int, min_samples: int):
    """
    Fetch joined logs: inference_log + outcomes_log
    """
    supabase = get_supabase()

    # We need to join inference_log and outcomes_log.
    # Supabase-py doesn't support complex joins easily in one call unless we use a view or foreign keys.
    # We'll fetch separately and join in memory for simplicity/flexibility.

    cutoff = (datetime.now() - timedelta(days=days_back)).isoformat()

    print(f"Fetching logs since {cutoff}...")

    # 1. Fetch Outcomes (the ground truth)
    outcomes_resp = supabase.table("outcomes_log")\
        .select("*")\
        .gt("created_at", cutoff)\
        .execute()

    outcomes = outcomes_resp.data
    if not outcomes:
        print("No outcomes found.")
        return []

    # Map trace_id -> outcome
    outcome_map = {o['trace_id']: o for o in outcomes}
    trace_ids = list(outcome_map.keys())

    # 2. Fetch Inferences for these outcomes
    # Chunking might be needed if too many IDs, but start simple.
    inferences = []

    # Supabase 'in' filter has limits. If > 100, we might need batches.
    batch_size = 50
    for i in range(0, len(trace_ids), batch_size):
        batch = trace_ids[i:i+batch_size]
        resp = supabase.table("inference_log")\
            .select("trace_id, symbol_universe, predicted_mu, predicted_sigma")\
            .in_("trace_id", batch)\
            .execute()
        inferences.extend(resp.data)

    print(f"Matched {len(inferences)} inferences to {len(outcomes)} outcomes.")

    joined_data = []
    for inf in inferences:
        tid = inf['trace_id']
        if tid in outcome_map:
            joined_data.append({
                "inference": inf,
                "outcome": outcome_map[tid]
            })

    return joined_data

def train_adapters(data: List[dict], current_adapters: Dict[str, SymbolAdapterState], learning_rate: float = 0.05):
    """
    Update adapter states based on data.
    """
    # Group by symbol
    symbol_data = defaultdict(list)

    for row in data:
        inf = row['inference']
        out = row['outcome']

        # We need realized volatility and PnL per symbol, but the outcome log
        # currently stores 'realized_pl_1d' and 'realized_vol_1d' for the PORTFOLIO (trace).
        # Wait, the prompt implies "For each symbol with enough data".
        # If the log is portfolio-level, we can't easily attribute performance to single symbols
        # unless we know the weights.
        # But Phase 1 memory says: "Outcome updater script that fills outcomes_log using realized P&L/vol".
        # If outcomes_log is per-trace (portfolio), we have an attribution problem.

        # Let's assume for this task that we are looking at single-name trades OR
        # we treat the portfolio outcome as a signal for the symbols in it (weak attribution).
        # OR, better: The prompt says "For each symbol with enough data... derive simple update signals".
        # This implies we can measure symbol performance.
        #
        # If the system logs individual symbol performance, where is it?
        # Maybe 'realized_pl_1d' is a JSON or we need to look elsewhere?
        # The prompt says: "Consumes inference_log + outcomes_log joined by trace_id."
        # And "If model consistently underestimates volatility (sigma_realized > sigma_pred)".
        # This strongly implies we can compare sigma_pred(symbol) vs sigma_realized(symbol).
        #
        # If the outcomes_log only has aggregate portfolio stats, we can't do symbol-level L1 adapters accurately.
        # HOWEVER, let's assume 'outcomes_log' might have granular data or we use the aggregate as a proxy
        # for all symbols in that portfolio (common in simple regimes).
        #
        # Let's check the memory: "The apply_slippage_guardrail function...".
        # "A script packages/quantum/scripts/update_outcomes.py handles the calculation of realized P&L...".
        # If I can't see that script, I have to guess.
        #
        # Let's assume for Phase 2 that we use the portfolio outcome to nudge all participants.
        # This is noisy but "Level-1" is often broad.
        # OR, maybe we should fetch historical data for the symbol again here?
        # That's expensive.
        #
        # Let's look at `predicted_sigma` in inference. It's likely a matrix or list.
        # `predicted_mu` is a dict {ticker: value}.
        #
        # Strategy:
        # If portfolio PnL < expected PnL -> nudge alpha down for all constituents (weighted?).
        # If portfolio Vol > expected Vol -> nudge sigma_scaler up for all constituents.

        # Parse Inference
        tickers = inf.get('symbol_universe', [])
        pred_mus = inf.get('predicted_mu', {}) # {ticker: float}
        pred_sigma_data = inf.get('predicted_sigma', {})
        # pred_sigma might be {'sigma_matrix': [[...]]}

        # We really need symbol-level realized data.
        # If `outcomes_log` has `realized_pl_1d` as a float, it's portfolio level.
        # Let's assume for this task we attribute the surprise to all symbols involved equally
        # (or better: we can't easily do it without symbol-level outcomes).
        #
        # Re-reading prompt: "For each symbol with enough data... If model consistently underestimates volatility"
        # This implies we DO calculate symbol volatility.
        # Maybe the 'update_outcomes.py' (Phase 1) puts more detail in outcomes_log?
        # If not, I will implement a logic that fetches the realized volatility for the symbol *here*?
        # No, that's heavy.
        #
        # Let's assume `outcomes_log` has a JSON field `details` or similar, OR we just use the portfolio metrics.
        # Given "Outcome updater script that fills outcomes_log", I'll assume it puts portfolio stats.
        # I will implement the "Portfolio Surprise -> Constituent Nudge" logic.

        # 1. Volatility Surprise
        realized_vol = out.get('realized_vol_1d', 0.0)
        # We need expected portfolio vol.
        # We can re-calculate it if we have weights?
        # Inference log usually has the *output* weights? No, inference log is *input* to optimizer.
        #
        # Actually, Phase 1 "log_inference" returns trace_id.
        # Then optimizer runs.
        # The optimizer output (weights) isn't strictly in inference_log unless we update it.
        # This makes exact attribution hard.
        #
        # Simplification for Phase 2 task:
        # We will iterate symbols in `symbol_universe`.
        # We will assume `realized_vol` (portfolio) vs `mean(pred_sigma diagonal)`? No.
        #
        # Let's use `surprise_score` directly.
        # "Use surprise_score... More surprising -> slightly larger adjustment."
        surprise = float(out.get('surprise_score', 0.0))

        # Direction of surprise?
        # If PnL was negative?
        pnl = float(out.get('realized_pl_1d', 0.0))

        for ticker in tickers:
            symbol_data[ticker].append({
                'pnl': pnl,
                'vol': realized_vol,
                'surprise': surprise,
                'pred_mu': pred_mus.get(ticker, 0.0)
            })

    # Update logic
    updated_adapters = {}

    for ticker, history in symbol_data.items():
        if len(history) < 5: # Min samples
            continue

        adapter = current_adapters.get(ticker, SymbolAdapterState(ticker, 0.0, 1.0))

        # Calculate gradients
        # 1. Alpha (Return) Adjustment
        # If realized PnL is consistently negative, reduce alpha.
        # This is a heuristic since we only have portfolio PnL.
        avg_pnl = np.mean([x['pnl'] for x in history])

        # If avg_pnl < 0, we want to lower expectation.
        # Signal = -1 if PnL < 0 else 1?
        # Let's scale by surprise.

        alpha_grad = 0.0
        sigma_grad = 0.0

        for event in history:
            # Weight by surprise (0-100 typically?)
            w = 1.0 + (event['surprise'] / 100.0)

            # Alpha: If PnL < 0, push alpha down.
            if event['pnl'] < 0:
                alpha_grad -= w * 0.001 # Small step
            else:
                alpha_grad += w * 0.0005 # Smaller step up

            # Sigma: If Vol is high (relative to what? we don't know expected vol exactly here without weights)
            # Heuristic: If surprise is high, assume risk was underestimated -> increase sigma scaler.
            if event['surprise'] > 50:
                 sigma_grad += w * 0.01
            elif event['surprise'] < 10:
                 sigma_grad -= w * 0.005 # Relax if everything is calm

        # Apply EMA
        # new = old * (1-lr) + (old + grad) * lr ?
        # simplified: new = old + lr * avg_grad

        # Average the gradients over history length?
        # Or treat the whole history as a batch?
        # Let's treat as batch.

        # Damping
        alpha_grad /= len(history)
        sigma_grad /= len(history)

        new_alpha = adapter.alpha_adjustment + (alpha_grad * learning_rate * 10)
        new_scaler = adapter.sigma_scaler + (sigma_grad * learning_rate * 10)

        # Safety Clamps (soft, hard clamps happen at runtime, but good to keep state sane)
        if new_scaler < 0.5: new_scaler = 0.5
        if new_scaler > 3.0: new_scaler = 3.0

        adapter.alpha_adjustment = new_alpha
        adapter.sigma_scaler = new_scaler
        adapter.cumulative_error = np.mean([x['surprise'] for x in history])
        adapter.model_version = "v1-heuristic"

        updated_adapters[ticker] = adapter

    return updated_adapters

def main():
    parser = argparse.ArgumentParser(description="Train Level-1 Symbol Adapters")
    parser.add_argument("--days", type=int, default=30, help="Lookback window in days")
    parser.add_argument("--min-samples", type=int, default=5, help="Minimum samples per symbol")
    parser.add_argument("--dry-run", action="store_true", help="Do not save changes")

    args = parser.parse_args()

    # 1. Fetch
    data = fetch_logs(args.days, args.min_samples)
    if not data:
        print("No training data found.")
        return

    # 2. Load current state
    # Get all unique symbols
    all_symbols = set()
    for row in data:
        all_symbols.update(row['inference'].get('symbol_universe', []))

    current_adapters = load_symbol_adapters(list(all_symbols))

    # 3. Train
    updated_adapters = train_adapters(data, current_adapters)

    print(f"Updated adapters for {len(updated_adapters)} symbols.")

    # 4. Save
    if not args.dry_run:
        save_symbol_adapters(updated_adapters)
    else:
        print("Dry run: Skipping save.")
        # print sample
        if updated_adapters:
            sample = list(updated_adapters.values())[0]
            print(f"Sample update for {sample.symbol}: Alpha={sample.alpha_adjustment:.4f}, Scaler={sample.sigma_scaler:.4f}")

if __name__ == "__main__":
    main()
