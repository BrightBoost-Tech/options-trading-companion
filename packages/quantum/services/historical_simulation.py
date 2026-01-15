import os
import sys
import random
import uuid
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

# Add parent directory to path to allow importing strategy_profiles
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from packages.quantum.strategy_profiles import StrategyConfig
except ImportError:
    StrategyConfig = None # Fallback or type alias

from packages.quantum.analytics.regime_scoring import ScoringEngine, ConvictionTransform
from packages.quantum.analytics.regime_integration import (
    DEFAULT_WEIGHT_MATRIX,
    DEFAULT_CATALYST_PROFILES,
    DEFAULT_LIQUIDITY_SCALAR,
    DEFAULT_REGIME_PROFILES,
    map_market_regime,
    run_historical_scoring
)
from packages.quantum.market_data import PolygonService
from packages.quantum.analytics.factors import calculate_indicators_vectorized
from packages.quantum.nested.backbone import infer_global_context, GlobalContext
from packages.quantum.services.transaction_cost_model import TransactionCostModel
from packages.quantum.common_enums import UnifiedScore

# --- Configuration ---
HISTORICAL_SIM_UNIVERSE = os.getenv("HISTORICAL_SIM_UNIVERSE", "SPY,QQQ,IWM,DIA").split(",")
HISTORICAL_RANDOM_LOOKBACK_YEARS = int(os.getenv("HISTORICAL_RANDOM_LOOKBACK_YEARS", "5"))
HISTORICAL_RANDOM_MIN_AGE_DAYS = int(os.getenv("HISTORICAL_RANDOM_MIN_AGE_DAYS", "365"))
HISTORICAL_RANDOM_PARAMS = os.getenv("HISTORICAL_RANDOM_PARAMS", "false").lower() == "true"
HISTORICAL_SIM_USER_ID = os.getenv("HISTORICAL_SIM_USER_ID")


# --- Learning Hook ---

def learn_from_cycle(
    trajectory: List[Dict[str, Any]],
    entry: Dict[str, Any],
    exit: Dict[str, Any],
    reward: float,
    user_id: Optional[str] = None,
    mode: str = "historical",
    attribution: Dict[str, float] = None
) -> None:
    """
    Hook for nested learning.
    Feeds (state, action, reward) into learning_feedback_loops for offline analysis.
    Uses aggregation pattern to support ConvictionService feedback loop.
    """
    try:
        # Check if enabled globally (redundant check if caller checked, but safe)
        enable_learning = os.getenv("ENABLE_HISTORICAL_NESTED_LEARNING", "true").lower() == "true"
        if not enable_learning:
            return

        # Lazy import to avoid circular dep at top level if it becomes an issue,
        # though usually okay.
        from packages.quantum.nested_logging import _get_supabase_client
        from packages.quantum.services.journal_service import JournalService

        supabase = _get_supabase_client()
        if not supabase:
            return

        # 1. Determine Target User
        # Use configured historical user, passed user, or fallback
        target_user = HISTORICAL_SIM_USER_ID or user_id
        if not target_user:
            # Fallback only for dev convenience
            target_user = "75ee12ad-b119-4f32-aeea-19b4ef55d587"

        # Breakdown attribution in notes
        attr_str = ""
        if attribution:
            attr_str = f" | Attribution: Alpha={attribution.get('alpha',0):.2f}, Drag={attribution.get('execution_drag',0):.2f}, Regime={attribution.get('regime_shift',0):.2f}"

        # 2. Create Synthetic Journal Entry
        try:
            journal_service = JournalService(supabase)

            journal_service.add_trade(
                user_id=target_user,
                trade_data={
                    "entry_type": "historical_cycle",
                    "symbol": entry.get("symbol", "SPY"),
                    "pnl": reward,
                    "entry_date": entry["entryTime"],
                    "exit_date": exit["exitTime"],
                    "entry_price": entry["entryPrice"],
                    "exit_price": exit["exitPrice"],
                    "direction": "Long",
                    "status": "closed",
                    "notes": f"Historical regime cycle {mode}: PnL={reward:.2f} | Entry: {entry.get('regimeAtEntry')} -> Exit: {exit.get('regimeAtExit')}{attr_str}",
                }
            )
        except Exception as j_err:
            print(f"[NestedLearning] Journal entry failed: {j_err}")

        # 3. Update Aggregate Learning Stats
        # Key: (user_id, strategy="historical_cycle", window="historical_sim")
        strategy_key = "historical_cycle"
        window_key = "historical_sim"

        # Safe probe to silence errors if migration not applied
        supports_aggregate = True
        try:
            # Check if columns exist by trying to select one
            supabase.table("learning_feedback_loops").select("strategy").limit(1).execute()
        except Exception as e:
            if "42703" in str(e): # Undefined column
                supports_aggregate = False
            else:
                pass # Other error, proceed carefully

        if supports_aggregate:
            try:
                existing_feedback = supabase.table("learning_feedback_loops") \
                    .select("*") \
                    .eq("user_id", target_user) \
                    .eq("strategy", strategy_key) \
                    .eq("window", window_key) \
                    .eq("outcome_type", "aggregate") \
                    .execute()

                if existing_feedback.data:
                    rec = existing_feedback.data[0]
                    new_total = (rec.get("total_trades") or 0) + 1
                    new_wins = (rec.get("wins") or 0) + (1 if reward > 0 else 0)
                    new_losses = (rec.get("losses") or 0) + (1 if reward < 0 else 0)
                    # Update average return (simple moving average approximation)
                    current_avg = float(rec.get("avg_return", 0) or 0)
                    old_total = rec.get("total_trades") or 0
                    new_avg = ((current_avg * old_total) + reward) / new_total

                    supabase.table("learning_feedback_loops").update({
                        "total_trades": new_total,
                        "wins": new_wins,
                        "losses": new_losses,
                        "avg_return": new_avg,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                        "outcome_type": "aggregate"
                    }).eq("id", rec["id"]).execute()
                else:
                    feedback_payload = {
                        "user_id": target_user,
                        "strategy": strategy_key,
                        "window": window_key,
                        "total_trades": 1,
                        "wins": 1 if reward > 0 else 0,
                        "losses": 1 if reward < 0 else 0,
                        "avg_return": reward,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                        "outcome_type": "aggregate"
                    }
                    supabase.table("learning_feedback_loops").insert(feedback_payload).execute()
            except Exception as fb_err:
                # Still catch unexpected errors but silence the known 42703 if probe failed to catch it
                if "42703" not in str(fb_err):
                    print(f"[NestedLearning] Failed to update feedback loop stats: {fb_err}")

    except Exception as e:
        print(f"[NestedLearning] Failed to log cycle: {e}")

    # Log to console as well
    print(f"[NestedLearning:{mode}] Cycle closed. PnL: {reward:.2f}. "
          f"EntryRegime: {entry.get('regimeAtEntry')}, ExitRegime: {exit.get('regimeAtExit')}")

class HistoricalCycleService:
    def __init__(self, polygon_service: PolygonService = None):
        self.polygon = polygon_service or PolygonService()
        self.scoring_engine = ScoringEngine(
            DEFAULT_WEIGHT_MATRIX,
            DEFAULT_CATALYST_PROFILES,
            DEFAULT_LIQUIDITY_SCALAR
        )
        self.conviction_transform = ConvictionTransform(DEFAULT_REGIME_PROFILES)
        self.lookback_window = 60 # Days needed for indicators
        self.enable_learning = os.getenv("ENABLE_HISTORICAL_NESTED_LEARNING", "true").lower() == "true"
        self.cost_model = TransactionCostModel() # New V3

    def run_cycle(
        self,
        cursor_date_str: str,
        symbol: str = "SPY",
        user_id: Optional[str] = None,
        config: Optional[Any] = None, # Using Any to avoid runtime issues if import fails, but verified via logic
        mode: str = "deterministic",
        seed: Optional[int] = None # Added seed param
    ) -> Dict[str, Any]:
        """
        Runs exactly one historical trade cycle (Entry -> Exit).
        mode: "deterministic" (default) or "random".
        seed: Optional seed for reproducibility in random mode.
        """
        run_id = str(uuid.uuid4())

        # 0. Setup Parameters & Randomness
        chosen_symbol = symbol

        # Use local RNG instance for thread safety
        # If seed is provided, use it. Else use random source (system time/entropy).
        rng = random.Random(seed)

        if mode == "random":
            # Randomize Symbol
            if not symbol or symbol == "SPY":
                chosen_symbol = rng.choice(HISTORICAL_SIM_UNIVERSE)

            # Randomize Date
            # Configurable lookback
            now = datetime.now()
            min_age_days = HISTORICAL_RANDOM_MIN_AGE_DAYS
            lookback_years = HISTORICAL_RANDOM_LOOKBACK_YEARS

            end_window = now - timedelta(days=min_age_days)
            start_window = end_window - timedelta(days=365 * lookback_years)

            if start_window < datetime(2000, 1, 1): # Hard floor
                start_window = datetime(2000, 1, 1)

            time_delta = end_window - start_window
            if time_delta.days > 0:
                random_days = rng.randrange(time_delta.days)
                start_date = start_window + timedelta(days=random_days)
                cursor_date_str = start_date.strftime("%Y-%m-%d")
            else:
                # Fallback if window is too small
                start_date = start_window
                cursor_date_str = start_date.strftime("%Y-%m-%d")

        # 1. Parse Cursor (Deterministic / Finalized Random)
        try:
            start_date = datetime.strptime(cursor_date_str, "%Y-%m-%d")
        except (ValueError, TypeError):
            # If invalid or empty, default to 2 years ago
            start_date = datetime.now() - timedelta(days=365*2)

        entry_threshold = 0.70
        tp_pct = 0.08
        sl_pct = 0.05
        max_days = 365
        regime_whitelist = []

        if config:
            entry_threshold = config.conviction_floor
            tp_pct = config.take_profit_pct
            sl_pct = config.stop_loss_pct
            max_days = config.max_holding_days
            regime_whitelist = config.regime_whitelist

        # Apply Jitter if enabled
        if mode == "random" and HISTORICAL_RANDOM_PARAMS:
            # entry_threshold ± 0.05, clamped [0.4, 0.95]
            jitter_entry = rng.uniform(-0.05, 0.05)
            entry_threshold = max(0.4, min(0.95, entry_threshold + jitter_entry))

            # tp_pct ± 0.02, clamped [0.01, 0.5]
            jitter_tp = rng.uniform(-0.02, 0.02)
            tp_pct = max(0.01, min(0.5, tp_pct + jitter_tp))

            # sl_pct ± 0.01, clamped [0.01, 0.3]
            jitter_sl = rng.uniform(-0.01, 0.01)
            sl_pct = max(0.01, min(0.3, sl_pct + jitter_sl))

        # 2. Fetch Data Chunk (Start Date -> 1 Year Forward + Lookback)
        simulation_end_date = start_date + timedelta(days=365) # Fetch ample data
        days_needed = 365 + self.lookback_window

        try:
            hist_data = self.polygon.get_historical_prices(
                chosen_symbol,
                days=days_needed,
                to_date=simulation_end_date
            )
        except Exception as e:
            return {
                "error": f"Data fetch failed for {chosen_symbol}: {str(e)}",
                "done": True,
                "status": "no_data",
                "run_id": run_id,
                "chosen_symbol": chosen_symbol
            }

        dates = hist_data.get('dates', [])
        prices = hist_data.get('prices', [])
        # volumes = hist_data.get('volumes', []) # Unused

        # 3. Locate Start Index
        start_idx = -1
        for i, d_str in enumerate(dates):
            d = datetime.strptime(d_str, "%Y-%m-%d")
            if d >= start_date:
                start_idx = i
                break

        if start_idx == -1 or start_idx >= len(dates) - 1:
            return {
                "done": True,
                "status": "no_data",
                "message": "No more historical data starting from cursor",
                "run_id": run_id,
                "chosen_symbol": chosen_symbol
            }

        if start_idx < self.lookback_window:
            start_idx = self.lookback_window

        # 4. Simulation Loop
        in_trade = False
        entry_details = {}
        trajectory = [] # Capture state at each step for learning
        current_idx = start_idx
        days_in_trade = 0

        # Attribution vars
        execution_drag_total = 0.0

        # Pre-calculate indicators vectorized (Optimization)
        # Instead of calculating factors in the loop (O(N*M)), we compute them once (O(N))
        indicators = calculate_indicators_vectorized(prices)
        trend_series = indicators["trend"]
        vol_series = indicators["volatility"]
        rsi_series = indicators["rsi"]

        while current_idx < len(dates):
            # GUARD: Future Leakage Check
            # We strictly slice up to current_idx (inclusive)
            # price_slice = prices[:current_idx+1] # Removed to save memory/cpu
            current_date_str = dates[current_idx]
            current_price = prices[current_idx]

            # --- Shared Logic Usage ---
            # 1. Compute Factors
            # usage of pre-calculated series
            trend = trend_series[current_idx]
            vol_annual = vol_series[current_idx]
            rsi_val = rsi_series[current_idx]

            # 2. Detect Regime (Global Backbone)
            features = {
                "spy_trend": trend.lower(),
                "vix_level": 20.0, # Baseline
            }
            # Enhanced VIX proxy from vol
            if vol_annual > 0.30: features["vix_level"] = 35.0
            elif vol_annual > 0.20: features["vix_level"] = 25.0
            else: features["vix_level"] = 15.0

            global_context: GlobalContext = infer_global_context(features)

            # 3. Map to Scoring Regime (Centralized Helper)
            regime_mapped = map_market_regime({
                "state": global_context.global_regime,
                "vol_annual": vol_annual
            })

            # 4. Score using Centralized Pipeline
            # Map factors to scoring inputs (0-100)
            trend_score = 100.0 if trend == "UP" else (0.0 if trend == "DOWN" else 50.0)

            vol_score = 50.0
            if vol_annual < 0.15: vol_score = 100.0
            elif vol_annual > 0.30: vol_score = 0.0

            value_score = 50.0
            if rsi_val < 30: value_score = 100.0
            elif rsi_val > 70: value_score = 0.0

            factors_input = {
                "trend": trend_score,
                "volatility": vol_score,
                "value": value_score
            }

            scoring_result = run_historical_scoring(
                symbol_data={
                    "symbol": chosen_symbol,
                    "factors": factors_input,
                    "liquidity_tier": "top"
                },
                regime=regime_mapped,
                scoring_engine=self.scoring_engine,
                conviction_transform=self.conviction_transform,
                universe_median=None
            )

            c_i = scoring_result['conviction']

            # Capture state for trajectory
            step_snapshot = {
                "date": current_date_str,
                "price": current_price,
                "regime": regime_mapped,
                "conviction": c_i,
                "factors": factors_input
            }

            # 6. State Machine
            if not in_trade:
                # ENTRY LOGIC

                # Check Regime Whitelist
                regime_ok = True
                if regime_whitelist and regime_mapped not in regime_whitelist:
                    regime_ok = False

                if regime_ok and c_i >= entry_threshold:
                    in_trade = True

                    # Execution Sim (Entry)
                    sim_res = self.cost_model.simulate_fill(
                        price=current_price,
                        quantity=100, # Mock qty
                        side="buy",
                        rng=rng
                    )
                    entry_fill_price = sim_res.fill_price
                    execution_drag_total += sim_res.slippage_paid # In dollars

                    entry_details = {
                        "entryIndex": current_idx,
                        "entryTime": current_date_str,
                        "entryPrice": entry_fill_price,
                        "rawEntryPrice": current_price,
                        "direction": "long",
                        "regimeAtEntry": regime_mapped,
                        "convictionAtEntry": c_i,
                        "symbol": chosen_symbol
                    }
                    trajectory = [step_snapshot] # Start trajectory
                    days_in_trade = 0
                # else: pass (continue scanning)

            else:
                # In Trade - Monitor for Exit
                trajectory.append(step_snapshot)
                days_in_trade += 1
                should_exit = False

                # Exit Rule 1: Loss of Conviction
                if c_i < 0.5: should_exit = True

                # Exit Rule 2: Hard Stops / Targets (Dynamic)
                pnl_pct = (current_price - entry_details['entryPrice']) / entry_details['entryPrice']

                if pnl_pct < -sl_pct: should_exit = True
                if pnl_pct > tp_pct: should_exit = True

                # Exit Rule 3: Max Holding Days
                if days_in_trade > max_days: should_exit = True

                if should_exit:
                    # Execution Sim (Exit)
                    sim_res = self.cost_model.simulate_fill(
                        price=current_price,
                        quantity=100,
                        side="sell",
                        rng=rng
                    )
                    exit_fill_price = sim_res.fill_price
                    execution_drag_total += sim_res.slippage_paid

                    pnl_amount = (exit_fill_price - entry_details['entryPrice'])

                    # PnL Attribution
                    # Alpha = Raw Market Move
                    # Drag = Execution Cost
                    # Regime Shift = PnL accrued while in a regime different from entry
                    raw_pnl = current_price - entry_details['rawEntryPrice']
                    execution_drag = (entry_details['entryPrice'] - entry_details['rawEntryPrice']) + (current_price - exit_fill_price)

                    regime_shift_pnl = 0.0
                    entry_regime = entry_details.get('regimeAtEntry')

                    # Trajectory contains snapshots [Entry, Day1, Day2, ... Exit]
                    # We iterate from index 1 (Day 1) to calculate daily PnL and attribute based on that day's regime
                    if len(trajectory) > 1:
                        for i in range(1, len(trajectory)):
                            step_curr = trajectory[i]
                            step_prev = trajectory[i-1]

                            step_price_delta = step_curr['price'] - step_prev['price']

                            # If the regime on this day (step_curr['regime']) differs from entry regime,
                            # attribute the price move to regime shift.
                            if step_curr.get('regime') != entry_regime:
                                regime_shift_pnl += step_price_delta

                    attribution = {
                        "alpha": raw_pnl,
                        "execution_drag": -abs(execution_drag),
                        "regime_shift": regime_shift_pnl
                    }

                    exit_details = {
                        "exitIndex": current_idx,
                        "exitTime": current_date_str,
                        "exitPrice": exit_fill_price,
                        "regimeAtExit": regime_mapped,
                        "convictionAtExit": c_i,
                        "daysInTrade": days_in_trade
                    }

                    # Nested Learning Trigger
                    if self.enable_learning:
                        learn_from_cycle(
                            trajectory,
                            entry_details,
                            exit_details,
                            pnl_amount,
                            user_id=user_id,
                            mode="historical",
                            attribution=attribution
                        )

                    return {
                        **entry_details,
                        **exit_details,
                        "pnl": pnl_amount,
                        "pnl_pct": pnl_amount / entry_details['entryPrice'],
                        "done": False,
                        "status": "normal_exit",
                        "nextCursor": dates[current_idx + 1] if current_idx + 1 < len(dates) else dates[-1],
                        "run_id": run_id,
                        "chosen_symbol": chosen_symbol,
                        "attribution": attribution
                    }

            current_idx += 1

        # End of Data Loop
        if in_trade:
            # Forced Exit
            sim_res = self.cost_model.simulate_fill(
                price=prices[-1],
                quantity=100,
                side="sell",
                rng=rng
            )
            exit_fill_price = sim_res.fill_price

            pnl_amount = (exit_fill_price - entry_details['entryPrice'])
            pnl_pct = pnl_amount / entry_details['entryPrice']
            exit_details = {
                "exitIndex": len(dates)-1,
                "exitTime": dates[-1],
                "exitPrice": exit_fill_price,
                "regimeAtExit": "unknown", # Data ended
                "convictionAtExit": 0.5,
                "daysInTrade": days_in_trade
            }

            if self.enable_learning:
                learn_from_cycle(
                    trajectory,
                    entry_details,
                    exit_details,
                    pnl_amount,
                    user_id=user_id,
                    mode="historical_forced"
                )

            return {
                **entry_details,
                **exit_details,
                "pnl": pnl_amount,
                "pnl_pct": pnl_pct,
                "done": True,
                "status": "forced_exit",
                "message": "Data ended during trade",
                "nextCursor": None,
                "run_id": run_id,
                "chosen_symbol": chosen_symbol
            }

        return {
            "done": True,
            "status": "no_entry",
            "message": "End of data reached without finding another trade.",
            "nextCursor": None,
            "run_id": run_id,
            "chosen_symbol": chosen_symbol
        }
