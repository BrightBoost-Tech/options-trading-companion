import os
import sys
import argparse
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
from scipy.optimize import minimize
from supabase import create_client, Client

# Ensure we can import packages.quantum
# This assumes the script is run from repo root or packages/quantum/scripts/
current_dir = os.path.dirname(os.path.abspath(__file__))
# Add repo root to sys.path
repo_root = os.path.abspath(os.path.join(current_dir, "../../.."))
if repo_root not in sys.path:
    sys.path.append(repo_root)

from packages.quantum.security.secrets_provider import SecretsProvider
from packages.quantum.services.analytics_service import AnalyticsService

def get_supabase_client() -> Optional[Client]:
    try:
        secrets = SecretsProvider().get_supabase_secrets()
        if secrets.url and secrets.service_role_key:
            return create_client(secrets.url, secrets.service_role_key)
        return None
    except Exception as e:
        print(f"Failed to initialize Supabase client: {e}")
        return None

class WalkForwardValidator:
    def __init__(self, user_id: str, lookback_days: int = 180, client: Optional[Client] = None):
        self.user_id = user_id
        self.lookback_days = lookback_days
        self.client = client or get_supabase_client()
        if not self.client:
            raise ValueError("Supabase client not available")
        self.analytics = AnalyticsService(self.client)
        self.data: Optional[pd.DataFrame] = None

    def fetch_data(self):
        print(f"Fetching data for user {self.user_id} (last {self.lookback_days} days)...")
        cutoff = (datetime.utcnow() - timedelta(days=self.lookback_days)).isoformat()

        # Assume learning_trade_outcomes_v3 has standard fields based on context
        # We need: closed_at, score/probability, pnl_realized, ev_estimated
        # If columns differ, we might need to adjust.
        # Common pattern:
        #   score (0-100) or probability (0-1)
        #   realized_pnl (float)
        #   ev (float)
        #   closed_at (timestamp)
        #   is_win (boolean) or derive from pnl > 0

        try:
            res = self.client.table("learning_trade_outcomes_v3") \
                .select("*") \
                .eq("user_id", self.user_id) \
                .gte("closed_at", cutoff) \
                .order("closed_at") \
                .execute()

            if not res.data:
                print("No data found.")
                self.data = pd.DataFrame()
                return

            df = pd.DataFrame(res.data)
            df['closed_at'] = pd.to_datetime(df['closed_at'])

            # Normalize column names if needed
            # Assuming 'score' is the uncalibrated probability-like metric (0-100 or 0-1)
            # Assuming 'realized_pnl' is the outcome
            # Assuming 'ev' or 'expected_value' is the initial expectation

            # Map columns if necessary (defensive)
            if 'score' in df.columns:
                # normalize to 0-1 if it looks like 0-100
                if df['score'].max() > 1.0:
                    df['prob_raw'] = df['score'] / 100.0
                else:
                    df['prob_raw'] = df['score']
            elif 'confidence_score' in df.columns:
                 if df['confidence_score'].max() > 1.0:
                    df['prob_raw'] = df['confidence_score'] / 100.0
                 else:
                    df['prob_raw'] = df['confidence_score']
            else:
                 # Fallback mock for testing if column missing, but likely should fail
                 print("Warning: 'score' or 'confidence_score' column missing. Using 0.5.")
                 df['prob_raw'] = 0.5

            if 'realized_pnl' not in df.columns and 'pnl' in df.columns:
                df['realized_pnl'] = df['pnl']

            if 'ev' not in df.columns and 'expected_value' in df.columns:
                df['ev'] = df['expected_value']

            # Fill NaNs
            df['ev'] = df['ev'].fillna(0.0)
            df['realized_pnl'] = df['realized_pnl'].fillna(0.0)
            df['is_win'] = (df['realized_pnl'] > 0).astype(int)

            self.data = df
            print(f"Loaded {len(df)} records.")

        except Exception as e:
            print(f"Error fetching data: {e}")
            raise e

    def calibrate_platt(self, probs: np.array, labels: np.array) -> Tuple[float, float]:
        """
        Fit Platt Scaling: P(y=1|x) = 1 / (1 + exp(-(A*logit(x) + B)))
        Returns A, B
        """
        # Avoid log(0) or log(1)
        epsilon = 1e-6
        p = np.clip(probs, epsilon, 1 - epsilon)
        logits = np.log(p / (1 - p))

        def objective(params):
            A, B = params
            f = A * logits + B
            pred_p = 1.0 / (1.0 + np.exp(-f))
            pred_p = np.clip(pred_p, 1e-15, 1 - 1e-15)
            # Log loss
            loss = -np.mean(labels * np.log(pred_p) + (1 - labels) * np.log(1 - pred_p))
            return loss

        # Initial guess A=1 (identity), B=0
        res = minimize(objective, [1.0, 0.0], method='BFGS')
        return res.x[0], res.x[1]

    def apply_platt(self, probs: np.array, A: float, B: float) -> np.array:
        epsilon = 1e-6
        p = np.clip(probs, epsilon, 1 - epsilon)
        logits = np.log(p / (1 - p))
        f = A * logits + B
        return 1.0 / (1.0 + np.exp(-f))

    def calibrate_ev(self, ev_raw: np.array, pnl_realized: np.array) -> Tuple[float, float]:
        """
        Fit Linear: PnL = alpha * EV + beta
        Returns alpha, beta
        """
        if len(ev_raw) < 2:
            return 1.0, 0.0
        # Simple least squares
        # np.polyfit returns [slope, intercept] for deg=1
        slope, intercept = np.polyfit(ev_raw, pnl_realized, 1)
        return slope, intercept

    def run_walkforward(self, train_days=60, test_days=14, step_days=14) -> List[Dict]:
        if self.data is None or self.data.empty:
            return []

        df = self.data.sort_values("closed_at")
        start_date = df['closed_at'].min()
        end_date = df['closed_at'].max()

        # Need at least train_days of data
        if (end_date - start_date).days < train_days:
            print(f"Not enough data for walk-forward. Have {(end_date - start_date).days} days, need {train_days}+.")
            return []

        current_date = start_date + timedelta(days=train_days)
        folds = []

        fold_idx = 1
        while current_date < end_date:
            train_start = current_date - timedelta(days=train_days)
            test_start = current_date
            test_end = current_date + timedelta(days=test_days)

            # Enforce hard cutoff for last fold to not exceed actual data end?
            # Or just take available data?
            # Standard WF usually implies full test windows, but we can allow partial.

            train_mask = (df['closed_at'] >= train_start) & (df['closed_at'] < test_start)
            test_mask = (df['closed_at'] >= test_start) & (df['closed_at'] < test_end)

            train_set = df[train_mask]
            test_set = df[test_mask]

            # Move window for next iteration
            current_date += timedelta(days=step_days)

            if test_set.empty:
                continue

            if len(train_set) < 10:
                print(f"Fold {fold_idx}: Skipped (Insufficient training data: {len(train_set)})")
                fold_idx += 1
                continue

            # --- Calibrate ---
            # PoP
            A, B = self.calibrate_platt(train_set['prob_raw'].values, train_set['is_win'].values)

            # EV
            alpha, beta = self.calibrate_ev(train_set['ev'].values, train_set['realized_pnl'].values)

            # --- Evaluate on Test ---
            # Apply
            test_probs_cal = self.apply_platt(test_set['prob_raw'].values, A, B)
            test_ev_cal = alpha * test_set['ev'].values + beta

            # Metrics
            # Brier Score = mean((prob - outcome)^2)
            brier_raw = np.mean((test_set['prob_raw'].values - test_set['is_win'].values)**2)
            brier_cal = np.mean((test_probs_cal - test_set['is_win'].values)**2)

            # EV Leakage = mean(PnL - EV)
            leakage_raw = np.mean(test_set['realized_pnl'].values - test_set['ev'].values)
            leakage_cal = np.mean(test_set['realized_pnl'].values - test_ev_cal)

            # Abs EV Leakage
            leakage_abs_raw = np.mean(np.abs(test_set['realized_pnl'].values - test_set['ev'].values))
            leakage_abs_cal = np.mean(np.abs(test_set['realized_pnl'].values - test_ev_cal))

            # Store result
            fold_res = {
                "fold_idx": fold_idx,
                "train_start": train_start.strftime("%Y-%m-%d"),
                "test_start": test_start.strftime("%Y-%m-%d"),
                "test_end": test_end.strftime("%Y-%m-%d"),
                "n_train": len(train_set),
                "n_test": len(test_set),
                "brier_raw": brier_raw,
                "brier_cal": brier_cal,
                "leakage_raw": leakage_raw,
                "leakage_cal": leakage_cal,
                "leakage_abs_raw": leakage_abs_raw,
                "leakage_abs_cal": leakage_abs_cal,
                "params_pop": {"A": A, "B": B},
                "params_ev": {"alpha": alpha, "beta": beta}
            }
            folds.append(fold_res)
            fold_idx += 1

        return folds

    def print_report(self, folds: List[Dict]):
        if not folds:
            print("No folds generated.")
            return

        print("\n=== Walk-Forward Validation Report (v3) ===")
        print(f"{'Fold':<5} {'Test Start':<12} {'N':<5} | {'Leak Raw':<10} {'Leak Cal':<10} | {'Brier Raw':<10} {'Brier Cal':<10}")
        print("-" * 80)

        for f in folds:
            print(f"{f['fold_idx']:<5} {f['test_start']:<12} {f['n_test']:<5} | "
                  f"{f['leakage_raw']:<10.2f} {f['leakage_cal']:<10.2f} | "
                  f"{f['brier_raw']:<10.4f} {f['brier_cal']:<10.4f}")

        print("-" * 80)

        # Global Summary
        avg_leak_raw = np.mean([f['leakage_raw'] for f in folds])
        avg_leak_cal = np.mean([f['leakage_cal'] for f in folds])
        avg_brier_raw = np.mean([f['brier_raw'] for f in folds])
        avg_brier_cal = np.mean([f['brier_cal'] for f in folds])

        print(f"AVERAGE (All Folds):")
        print(f"Leakage (Mean Error): Raw={avg_leak_raw:.2f} -> Cal={avg_leak_cal:.2f}")
        print(f"Brier Score (Acc):    Raw={avg_brier_raw:.4f} -> Cal={avg_brier_cal:.4f}")

        # Answer key questions
        improved_ev = abs(avg_leak_cal) < abs(avg_leak_raw)
        improved_brier = avg_brier_cal < avg_brier_raw

        print("\nCONCLUSIONS:")
        print(f"1) Is calibration reducing EV leakage? {'YES' if improved_ev else 'NO'} "
              f"(Abs delta: {abs(avg_leak_raw) - abs(avg_leak_cal):.2f})")
        print(f"2) Is PoP calibration improving Brier score? {'YES' if improved_brier else 'NO'} "
              f"(Delta: {avg_brier_raw - avg_brier_cal:.4f})")

    def save_analytics(self, folds: List[Dict]):
        if os.getenv("WRITE_WALKFORWARD_REPORT", "false").lower() != "true":
            return

        summary = {
            "avg_leakage_raw": np.mean([f['leakage_raw'] for f in folds]),
            "avg_leakage_cal": np.mean([f['leakage_cal'] for f in folds]),
            "avg_brier_raw": np.mean([f['brier_raw'] for f in folds]),
            "avg_brier_cal": np.mean([f['brier_cal'] for f in folds]),
            "total_folds": len(folds)
        }

        print("Writing report to analytics_events...")
        self.analytics.log_event(
            user_id=self.user_id,
            event_name="walkforward_report",
            category="system",
            properties={
                "folds": folds,
                "summary": summary
            }
        )

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run v3 Walk-Forward Validation")
    parser.add_argument("--user-id", required=True, help="User UUID")
    parser.add_argument("--days", type=int, default=180, help="Lookback days")

    args = parser.parse_args()

    validator = WalkForwardValidator(user_id=args.user_id, lookback_days=args.days)
    validator.fetch_data()
    results = validator.run_walkforward(train_days=60, test_days=14, step_days=14)
    validator.print_report(results)
    validator.save_analytics(results)
