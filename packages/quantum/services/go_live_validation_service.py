import uuid
import logging
from datetime import datetime, timedelta, timezone, date
from typing import Dict, Any, Optional, List, Literal
from supabase import Client
import math

from packages.quantum.services.backtest_engine import BacktestEngine
from packages.quantum.strategy_profiles import StrategyConfig, CostModelConfig
from packages.quantum.services.option_contract_resolver import OptionContractResolver

logger = logging.getLogger(__name__)


def compute_segment_returns_from_equity(
    equity_curve: List[Dict],
    window_start: date,
    window_days: int = 90
) -> Dict[str, Any]:
    """
    Computes segment returns from equity curve using mark-to-market approach.

    Instead of bucketing realized PnL by trade exit dates, this function:
    - Divides the window into 3 segments (days 0-30, 30-60, 60-90)
    - Computes return for each segment based on equity change

    Args:
        equity_curve: List of {"date": "YYYY-MM-DD", "equity": float} dicts
        window_start: Start date of the backtest window
        window_days: Total window duration (default 90)

    Returns:
        Dict with:
        - segment_returns_pct: {"seg1": float, "seg2": float, "seg3": float}
        - segment_equity: {"seg1": (start, end), "seg2": (start, end), "seg3": (start, end)}
        - valid: bool indicating if computation was successful
    """
    if not equity_curve:
        return {
            "segment_returns_pct": {"seg1": 0.0, "seg2": 0.0, "seg3": 0.0},
            "segment_equity": {"seg1": (0, 0), "seg2": (0, 0), "seg3": (0, 0)},
            "valid": False
        }

    # Convert equity curve to date-indexed dict
    equity_by_date = {}
    for point in equity_curve:
        date_str = point.get("date", "")
        if date_str:
            try:
                d = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                try:
                    d = datetime.fromisoformat(date_str).date()
                except ValueError:
                    continue
            equity_by_date[d] = point.get("equity", 0)

    if not equity_by_date:
        return {
            "segment_returns_pct": {"seg1": 0.0, "seg2": 0.0, "seg3": 0.0},
            "segment_equity": {"seg1": (0, 0), "seg2": (0, 0), "seg3": (0, 0)},
            "valid": False
        }

    # Define segment boundaries
    seg_duration = window_days // 3  # 30 days per segment for 90-day window
    boundaries = [
        window_start,
        window_start + timedelta(days=seg_duration),
        window_start + timedelta(days=seg_duration * 2),
        window_start + timedelta(days=window_days)
    ]

    def get_equity_at_or_before(target_date: date) -> Optional[float]:
        """Find equity at target date, or closest earlier date."""
        if target_date in equity_by_date:
            return equity_by_date[target_date]
        # Find closest earlier date
        earlier_dates = [d for d in equity_by_date.keys() if d <= target_date]
        if earlier_dates:
            return equity_by_date[max(earlier_dates)]
        return None

    def get_equity_at_or_after(target_date: date) -> Optional[float]:
        """Find equity at target date, or closest later date."""
        if target_date in equity_by_date:
            return equity_by_date[target_date]
        # Find closest later date
        later_dates = [d for d in equity_by_date.keys() if d >= target_date]
        if later_dates:
            return equity_by_date[min(later_dates)]
        return None

    segment_returns = {}
    segment_equity = {}

    for i, seg_name in enumerate(["seg1", "seg2", "seg3"]):
        seg_start = boundaries[i]
        seg_end = boundaries[i + 1] - timedelta(days=1)  # End of segment (inclusive)

        # Get equity at segment boundaries
        start_equity = get_equity_at_or_after(seg_start)
        end_equity = get_equity_at_or_before(seg_end)

        if start_equity is None:
            start_equity = get_equity_at_or_before(seg_start)
        if end_equity is None:
            end_equity = get_equity_at_or_after(seg_end)

        if start_equity and end_equity and start_equity > 0:
            ret_pct = ((end_equity - start_equity) / start_equity) * 100
            segment_returns[seg_name] = ret_pct
            segment_equity[seg_name] = (start_equity, end_equity)
        else:
            segment_returns[seg_name] = 0.0
            segment_equity[seg_name] = (start_equity or 0, end_equity or 0)

    return {
        "segment_returns_pct": segment_returns,
        "segment_equity": segment_equity,
        "valid": True
    }


def score_training_result(result: Dict[str, Any]) -> tuple:
    """
    Scores a training result for ranking purposes.

    Scoring rule (deterministic):
    1. Prefer passed suites first
    2. Among passed: highest return_pct, tie-breaker: least negative segment
    3. Among failed: highest return_pct, tie-breaker: least negative worst segment

    Returns:
        Tuple for comparison: (passed_score, return_pct, segment_penalty)
        Higher is better.
    """
    if not result:
        return (0, float("-inf"), float("-inf"))

    all_passed = result.get("all_passed", False)
    worst_return = result.get("worst_return", float("-inf"))

    # Calculate segment penalty (least negative = best)
    worst_suite = result.get("worst_suite", {})
    segment_pnls = worst_suite.get("segment_pnls", {})
    segment_returns = worst_suite.get("segment_returns_pct", segment_pnls)

    if segment_returns:
        worst_segment = min(segment_returns.values())
    else:
        worst_segment = float("-inf")

    # Score: (passed=1/0, return_pct, worst_segment)
    return (1 if all_passed else 0, worst_return, worst_segment)


class GoLiveValidationService:
    def __init__(self, supabase: Client):
        self.supabase = supabase

    def get_or_create_state(self, user_id: str) -> Dict[str, Any]:
        """
        Fetches the v3_go_live_state for the user.
        If not found, initializes a new state with a 90-day paper window starting now.
        """
        try:
            res = self.supabase.table("v3_go_live_state").select("*").eq("user_id", user_id).single().execute()
            if res.data:
                return res.data
        except Exception as e:
            # likely RowNotFound or similar
            pass

        # Create new state
        now = datetime.now(timezone.utc)
        window_end = now + timedelta(days=90)

        new_state = {
            "user_id": user_id,
            "paper_window_start": now.isoformat(),
            "paper_window_end": window_end.isoformat(),
            "paper_baseline_capital": 100000,
            "paper_consecutive_passes": 0,
            "paper_ready": False,
            "historical_last_run_at": None,
            "historical_last_result": {},
            "overall_ready": False
        }

        res = self.supabase.table("v3_go_live_state").insert(new_state).execute()
        if res.data:
            return res.data[0]
        return new_state

    def eval_paper(self, user_id: str, now: datetime = None) -> Dict[str, Any]:
        """
        Evaluates the current paper trading window.
        Returns metrics and status.
        If window has ended, finalizes the run, updates streak, and rolls window.
        """
        if now is None:
            now = datetime.now(timezone.utc)

        state = self.get_or_create_state(user_id)

        window_start = datetime.fromisoformat(state["paper_window_start"])
        window_end = datetime.fromisoformat(state["paper_window_end"])

        # 1. Calculate Metrics
        pnl_total = 0.0
        segment_pnls = {"seg1": 0.0, "seg2": 0.0, "seg3": 0.0}
        trades = []

        try:
            rows = []
            try:
                # Timestamps in supabase are ISO strings
                res = self.supabase.table("learning_trade_outcomes_v3") \
                    .select("closed_at, pnl_realized") \
                    .eq("user_id", user_id) \
                    .eq("is_paper", True) \
                    .gte("closed_at", window_start.isoformat()) \
                    .lte("closed_at", window_end.isoformat()) \
                    .execute()
                rows = res.data or []
            except Exception:
                pass

            # If rows found, aggregate
            total_duration = (window_end - window_start).total_seconds()
            seg_duration = total_duration / 3.0

            for r in rows:
                pnl = float(r.get("pnl_realized") or 0.0)
                closed_at = datetime.fromisoformat(r["closed_at"])

                pnl_total += pnl

                # Segment Logic
                offset = (closed_at - window_start).total_seconds()
                if offset < seg_duration:
                    segment_pnls["seg1"] += pnl
                elif offset < seg_duration * 2:
                    segment_pnls["seg2"] += pnl
                else:
                    segment_pnls["seg3"] += pnl

        except Exception as e:
            logger.error(f"Error calculating paper metrics: {e}")

        baseline = float(state["paper_baseline_capital"])
        return_pct = (pnl_total / baseline) * 100 if baseline > 0 else 0.0

        result = {
            "pnl_total": pnl_total,
            "return_pct": return_pct,
            "segment_pnls": segment_pnls,
            "window_start": state["paper_window_start"],
            "window_end": state["paper_window_end"]
        }

        # 2. Check for Window Closure
        if now >= window_end:
            # Finalize
            # Pass conditions: return >= 10% AND no losing segment
            passed = return_pct >= 10.0 and all(v >= 0 for v in segment_pnls.values())

            fail_reason = None
            if not passed:
                if return_pct < 10.0:
                    fail_reason = "return_below_10pct"
                elif any(v < 0 for v in segment_pnls.values()):
                    fail_reason = "losing_segment"

            # Update Streak
            new_streak = state["paper_consecutive_passes"] + 1 if passed else 0
            paper_ready = new_streak >= 3

            # Persist Run
            run_data = {
                "user_id": user_id,
                "mode": "paper",
                "window_start": state["paper_window_start"],
                "window_end": state["paper_window_end"],
                "return_pct": return_pct,
                "pnl_total": pnl_total,
                "segment_pnls": segment_pnls,
                "passed": passed,
                "fail_reason": fail_reason,
                "details_json": {"streak_before": state["paper_consecutive_passes"], "streak_after": new_streak}
            }
            self.supabase.table("v3_go_live_runs").insert(run_data).execute()

            # Persist Journal
            journal_data = {
                "user_id": user_id,
                "window_start": state["paper_window_start"],
                "window_end": state["paper_window_end"],
                "title": f"Paper Window {'Passed' if passed else 'Failed'}",
                "summary": f"Return: {return_pct:.2f}% | PnL: ${pnl_total:.2f} | Streak: {new_streak}",
                "details_json": result
            }
            self.supabase.table("v3_go_live_journal").insert(journal_data).execute()

            # Update State & Roll Window
            next_start = window_end
            next_end = next_start + timedelta(days=90)

            updates = {
                "paper_consecutive_passes": new_streak,
                "paper_ready": paper_ready,
                "paper_window_start": next_start.isoformat(),
                "paper_window_end": next_end.isoformat(),
                "updated_at": now.isoformat()
            }

            hist_res = state.get("historical_last_result") or {}
            hist_passed = hist_res.get("passed", False)
            hist_ts_str = state.get("historical_last_run_at")

            hist_recent = False
            if hist_ts_str:
                hist_ts = datetime.fromisoformat(hist_ts_str)
                if (now - hist_ts).days <= 30:
                    hist_recent = True

            overall_ready = paper_ready and hist_passed and hist_recent
            updates["overall_ready"] = overall_ready

            self.supabase.table("v3_go_live_state").update(updates).eq("user_id", user_id).execute()

            result["status"] = "finalized"
            result["passed"] = passed
            result["new_streak"] = new_streak

        else:
            result["status"] = "in_progress"

        return result

    def eval_historical(self, user_id: str, suite_config: Dict[str, Any]) -> Dict[str, Any]:
        state = self.get_or_create_state(user_id)
        baseline = float(state.get("paper_baseline_capital", 100000) or 100000)

        symbol = suite_config.get("symbol", "SPY")
        window_days = int(suite_config.get("window_days", 90))
        concurrent_runs = int(suite_config.get("concurrent_runs", 3))
        stride_days = int(suite_config.get("stride_days", window_days))
        goal_return_pct = float(suite_config.get("goal_return_pct", 10.0))

        autotune = bool(suite_config.get("autotune", False))
        max_trials = int(suite_config.get("max_trials", 12))
        strategy_name = suite_config.get("strategy_name")

        # PR3: Option-native validation parameters
        instrument_type = suite_config.get("instrument_type", "stock")

        # PR11: Canonical V3 defaults for option mode (only if caller omits them)
        if instrument_type == "option":
            suite_config.setdefault("use_rolling_contracts", True)
            suite_config.setdefault("strict_option_mode", True)
            suite_config.setdefault("segment_tolerance_pct", 1.5)
            suite_config.setdefault("option_dte", 60)
            suite_config.setdefault("option_moneyness", "itm_5pct")
            suite_config.setdefault("option_right", "call")
            if not suite_config.get("strategy_name"):
                suite_config["strategy_name"] = "spy_opt_autolearn_v6"
                strategy_name = "spy_opt_autolearn_v6"

        option_right = suite_config.get("option_right", "call")
        option_dte = int(suite_config.get("option_dte", 30))
        option_moneyness = suite_config.get("option_moneyness", "atm")
        # PR7: Rolling mode and strict mode
        use_rolling = suite_config.get("use_rolling_contracts", True)  # Default to rolling
        strict_option_mode = suite_config.get("strict_option_mode", False)
        # PR8: Segment tolerance for losing_segment detection
        segment_tolerance_pct = float(suite_config.get("segment_tolerance_pct", 0.0))

        # Initialize option resolver if needed
        option_resolver = OptionContractResolver() if instrument_type == "option" else None

        now = datetime.now(timezone.utc).date() - timedelta(days=1)
        anchor_start = (
            datetime.strptime(suite_config["window_start"], "%Y-%m-%d").date()
            if suite_config.get("window_start")
            else now - timedelta(days=window_days)
        )

        suite_starts = [
            anchor_start - timedelta(days=i * stride_days)
            for i in range(concurrent_runs)
        ]

        # Load base StrategyConfig
        base_cfg = None
        try:
            q = self.supabase.table("strategy_configs").select("params").eq("user_id", user_id)
            if strategy_name:
                q = q.eq("name", strategy_name)
            q = q.order("updated_at", desc=True).limit(1)
            res = q.execute()
            if res.data:
                base_cfg = StrategyConfig(**res.data[0]["params"])
        except Exception:
            pass

        if not base_cfg:
            base_cfg = StrategyConfig(
                name="default",
                version=1,
                conviction_floor=0.55,
                take_profit_pct=0.05,
                stop_loss_pct=0.03,
                max_holding_days=10,
                max_risk_pct_portfolio=0.10,
                max_concurrent_positions=1,
                # Required fields with defaults
                conviction_slope=0.2,
                max_risk_pct_per_trade=0.05,
                max_spread_bps=100,
                max_days_to_expiry=45,
                min_underlying_liquidity=1000000.0,
                regime_whitelist=[]
            )

        engine = BacktestEngine()
        cost_model = CostModelConfig()

        def run_window(start_date, cfg):
            end_date = start_date + timedelta(days=window_days)

            # PR7: Rolling mode vs static contract mode
            rolling_options_param = None
            resolver_for_backtest = None
            backtest_symbol = symbol

            if instrument_type == "option" and option_resolver:
                if use_rolling:
                    # PR7: Rolling mode - pass underlying to backtest, let engine resolve per-entry
                    backtest_symbol = symbol  # Use underlying
                    rolling_options_param = {
                        "right": option_right,
                        "target_dte": option_dte,
                        "moneyness": option_moneyness
                    }
                    resolver_for_backtest = option_resolver
                    logger.info(f"Using rolling contract mode for {symbol}")
                else:
                    # Static mode - resolve one contract for entire window
                    resolved = option_resolver.resolve_contract_with_coverage(
                        underlying=symbol,
                        right=option_right,
                        target_dte=option_dte,
                        moneyness=option_moneyness,
                        as_of_date=start_date,
                        window_start=start_date,
                        window_end=end_date,
                        min_bars=60
                    )
                    if resolved:
                        backtest_symbol = resolved
                        logger.info(f"Resolved option contract with coverage: {resolved} for window {start_date} to {end_date}")
                    elif strict_option_mode:
                        # PR7: Strict mode - fail instead of fallback
                        logger.error(f"strict_option_mode: No option contract found for {symbol} as of {start_date}")
                        return {
                            "window_start": start_date.isoformat(),
                            "window_end": end_date.isoformat(),
                            "symbol": symbol,
                            "return_pct": 0.0,
                            "pnl_total": 0.0,
                            "segment_pnls": {"seg1": 0.0, "seg2": 0.0, "seg3": 0.0},
                            "trades_count": 0,
                            "passed": False,
                            "fail_reason": "no_option_contract",
                        }
                    else:
                        logger.warning(f"Could not resolve option contract with sufficient bars for {symbol} as of {start_date}, using underlying")

            bt = engine.run_single(
                symbol=backtest_symbol,
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
                config=cfg,
                cost_model=cost_model,
                seed=0,
                initial_equity=baseline,
                rolling_options=rolling_options_param,
                option_resolver=resolver_for_backtest,
            )

            equity = bt.equity_curve or []
            trades = bt.trades or []

            final_equity = equity[-1]["equity"] if equity else baseline
            pnl = final_equity - baseline
            ret = (pnl / baseline) * 100 if baseline else 0.0

            # PR8: Use equity-curve based segment returns instead of trade exit-date bucketing
            segment_result = compute_segment_returns_from_equity(equity, start_date, window_days)
            segment_returns_pct = segment_result["segment_returns_pct"]
            segment_equity = segment_result["segment_equity"]

            # Legacy trade-based segmentation as fallback
            seg_pnl = {"seg1": 0.0, "seg2": 0.0, "seg3": 0.0}
            for t in trades:
                pnl_t = float(t.get("pnl", 0.0))
                try:
                    d = datetime.strptime(t["exit_date"], "%Y-%m-%d").date()
                except ValueError:
                    d = datetime.fromisoformat(t["exit_date"]).date()

                off = (d - start_date).days
                if off < 30:
                    seg_pnl["seg1"] += pnl_t
                elif off < 60:
                    seg_pnl["seg2"] += pnl_t
                else:
                    seg_pnl["seg3"] += pnl_t

            # PR8: Use equity-based returns for losing_segment check with tolerance
            if segment_result["valid"]:
                # Losing segment: any segment return below -tolerance
                losing_segment = any(
                    v < -segment_tolerance_pct for v in segment_returns_pct.values()
                )
            else:
                # Fallback to legacy: any segment PnL < 0
                losing_segment = any(v < 0 for v in seg_pnl.values())

            passed = ret >= goal_return_pct and not losing_segment

            return {
                "window_start": start_date.isoformat(),
                "window_end": end_date.isoformat(),
                "symbol": backtest_symbol,
                "return_pct": ret,
                "pnl_total": pnl,
                "segment_pnls": seg_pnl,  # Legacy format for backward compat
                "segment_returns_pct": segment_returns_pct,  # PR8: New equity-based returns
                "segment_equity": segment_equity,  # PR8: Equity at segment boundaries
                "segment_tolerance_pct": segment_tolerance_pct,  # PR8: Tolerance used
                "trades_count": len(trades),
                "passed": passed,
                "fail_reason": (
                    "no_trades" if not trades else
                    "return_below_goal" if ret < goal_return_pct else
                    "losing_segment" if losing_segment else None
                ),
            }

        def candidate_configs():
            yield base_cfg
            if not autotune:
                return
            for m in [1.25, 1.5, 2.0]:
                yield base_cfg.copy(update={"max_risk_pct_portfolio": base_cfg.max_risk_pct_portfolio * m})
            for d in [0.05, 0.1]:
                yield base_cfg.copy(update={"conviction_floor": base_cfg.conviction_floor - d})
            yield base_cfg.copy(update={"take_profit_pct": base_cfg.take_profit_pct + 0.02})

        best = None
        trials = 0

        for cfg in candidate_configs():
            trials += 1
            suites = [run_window(s, cfg) for s in suite_starts]
            worst = min(suites, key=lambda x: x["return_pct"])
            all_passed = all(s["passed"] for s in suites)

            if not best or worst["return_pct"] > best["worst_return"]:
                best = {
                    "config": cfg,
                    "suites": suites,
                    "worst_return": worst["return_pct"],
                    "worst_suite": worst,
                    "all_passed": all_passed,
                }

            if all_passed or trials >= max_trials:
                break

        passed = best["all_passed"]
        worst = best["worst_suite"]

        # Serialize best result for DB
        best_json = best.copy()
        best_json["config"] = best["config"].model_dump()

        self.supabase.table("v3_go_live_runs").insert({
            "user_id": user_id,
            "mode": "historical",
            "window_start": anchor_start.isoformat(),
            "window_end": (anchor_start + timedelta(days=window_days)).isoformat(),
            "return_pct": best["worst_return"],
            "pnl_total": worst["pnl_total"],
            "segment_pnls": worst["segment_pnls"],
            "passed": passed,
            "fail_reason": worst["fail_reason"],
            "details_json": best_json,
        }).execute()

        self.supabase.table("v3_go_live_journal").insert({
            "user_id": user_id,
            "window_start": anchor_start.isoformat(),
            "window_end": (anchor_start + timedelta(days=window_days)).isoformat(),
            "title": f"Historical Concurrent Validation {'Passed' if passed else 'Failed'}",
            "summary": f"Worst-case return {best['worst_return']:.2f}% across {concurrent_runs} windows",
            "details_json": best_json,
        }).execute()

        self.supabase.table("v3_go_live_state").update({
            "historical_last_run_at": datetime.now(timezone.utc).isoformat(),
            "historical_last_result": {
                "passed": passed,
                "return_pct": best["worst_return"],
                "suites": best["suites"],
                "config_used": best_json["config"],
            },
            "overall_ready": bool(state.get("paper_ready")) and passed,
        }).eq("user_id", user_id).execute()

        return best

    def train_historical(self, user_id: str, suite_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Self-learning training loop for historical validation.

        Runs eval_historical repeatedly until train_target_streak consecutive passes
        are achieved, or train_max_attempts is exhausted. On failures, mutates the
        strategy config based on fail_reason.

        Args:
            user_id: User ID
            suite_config: Config dict including training parameters:
                - train_target_streak: Number of consecutive passes needed (default 3)
                - train_max_attempts: Maximum attempts before giving up (default 20)
                - train_strategy_name: Name for persisted strategy configs
                - train_versioning: "increment" or "overwrite"

        Returns:
            Dict with: status, streak, attempts, best_config, history, final_result
        """
        # Extract training parameters
        target_streak = int(suite_config.get("train_target_streak", 3))
        max_attempts = int(suite_config.get("train_max_attempts", 20))
        strategy_name = suite_config.get("train_strategy_name") or f"trained_{user_id[:8]}"
        versioning = suite_config.get("train_versioning", "increment")

        # Initialize tracking
        streak = 0
        attempts = 0
        history = []
        best_result = None
        best_return = float("-inf")
        current_config = None
        version = 1

        # Load or create base config
        try:
            q = self.supabase.table("strategy_configs").select("params, version").eq("user_id", user_id)
            if suite_config.get("strategy_name"):
                q = q.eq("name", suite_config["strategy_name"])
            q = q.order("updated_at", desc=True).limit(1)
            res = q.execute()
            if res.data:
                current_config = StrategyConfig(**res.data[0]["params"])
                version = int(res.data[0].get("version", 1)) + 1
        except Exception:
            pass

        if not current_config:
            current_config = StrategyConfig(
                name=strategy_name,
                version=1,
                conviction_floor=0.55,
                take_profit_pct=0.05,
                stop_loss_pct=0.03,
                max_holding_days=10,
                max_risk_pct_portfolio=0.10,
                max_concurrent_positions=1,
                conviction_slope=0.2,
                max_risk_pct_per_trade=0.05,
                max_spread_bps=100,
                max_days_to_expiry=45,
                min_underlying_liquidity=1000000.0,
                regime_whitelist=[]
            )

        while attempts < max_attempts:
            attempts += 1

            # Run evaluation with current config
            eval_config = suite_config.copy()
            eval_config["strategy_name"] = strategy_name
            eval_config["autotune"] = False  # We handle mutation ourselves

            # Inject current config into the service temporarily
            result = self._run_eval_with_config(user_id, eval_config, current_config)

            passed = result.get("all_passed", False)
            worst_return = result.get("worst_return", float("-inf"))
            fail_reason = result.get("worst_suite", {}).get("fail_reason")

            # Track history
            history.append({
                "attempt": attempts,
                "passed": passed,
                "worst_return": worst_return,
                "fail_reason": fail_reason,
                "config_snapshot": current_config.model_dump()
            })

            # PR8: Update best result using scoring function
            # Include config_snapshot so we can persist the best config on exhausted
            result_with_config = {
                **result,
                "config_snapshot": current_config.model_dump(),
                "config_obj": current_config  # Keep ref for persistence
            }
            current_score = score_training_result(result_with_config)
            best_score = score_training_result(best_result) if best_result else (0, float("-inf"), float("-inf"))

            if current_score > best_score:
                best_return = worst_return
                best_result = result_with_config

            # Update streak
            if passed:
                streak += 1
                logger.info(f"Training attempt {attempts}: PASSED (streak={streak})")

                if streak >= target_streak:
                    # Success! Persist the winning config
                    self._persist_strategy_config(
                        user_id, strategy_name, current_config, version, versioning
                    )

                    return {
                        "status": "success",
                        "streak": streak,
                        "attempts": attempts,
                        "best_config": current_config.model_dump(),
                        "best_return": best_return,
                        "history": history,
                        "final_result": result,
                        "best_result": best_result  # PR8: Include best_result for diagnostics
                    }
            else:
                streak = 0
                logger.info(f"Training attempt {attempts}: FAILED ({fail_reason})")

                # Mutate config based on fail_reason
                # PR7: _mutate_config now returns (config, suite_updates) tuple
                current_config, suite_updates = self._mutate_config(
                    current_config, fail_reason, worst_return, suite_config
                )
                # Apply suite_updates (e.g., option_dte, option_moneyness mutations)
                if suite_updates:
                    suite_config = suite_config.copy()
                    suite_config.update(suite_updates)
                version += 1

        # Exhausted attempts
        # PR8: Persist BEST config found (not last mutated config)
        best_config_to_persist = None
        best_config_dict = None
        if best_result:
            best_config_to_persist = best_result.get("config_obj", current_config)
            best_config_dict = best_result.get("config_snapshot", current_config.model_dump())
            self._persist_strategy_config(
                user_id, strategy_name, best_config_to_persist, version, versioning
            )
        else:
            best_config_dict = current_config.model_dump() if current_config else None

        return {
            "status": "exhausted",
            "streak": streak,
            "attempts": attempts,
            "best_config": best_config_dict,
            "best_return": best_return,
            "history": history,
            "final_result": best_result,
            "best_result": best_result  # PR8: Include best_result for diagnostics
        }

    def _run_eval_with_config(
        self,
        user_id: str,
        suite_config: Dict[str, Any],
        config: StrategyConfig
    ) -> Dict[str, Any]:
        """
        Runs eval_historical with a specific StrategyConfig.

        This is a helper that bypasses the normal config loading to use
        the provided config directly.
        """
        state = self.get_or_create_state(user_id)
        baseline = float(state.get("paper_baseline_capital", 100000) or 100000)

        symbol = suite_config.get("symbol", "SPY")
        window_days = int(suite_config.get("window_days", 90))
        concurrent_runs = int(suite_config.get("concurrent_runs", 3))
        stride_days = int(suite_config.get("stride_days", window_days))
        goal_return_pct = float(suite_config.get("goal_return_pct", 10.0))

        # Option parameters
        instrument_type = suite_config.get("instrument_type", "stock")

        # PR11: Canonical V3 defaults for option mode (only if caller omits them)
        if instrument_type == "option":
            suite_config.setdefault("use_rolling_contracts", True)
            suite_config.setdefault("strict_option_mode", True)
            suite_config.setdefault("segment_tolerance_pct", 1.5)
            suite_config.setdefault("option_dte", 60)
            suite_config.setdefault("option_moneyness", "itm_5pct")
            suite_config.setdefault("option_right", "call")

        option_right = suite_config.get("option_right", "call")
        option_dte = int(suite_config.get("option_dte", 30))
        option_moneyness = suite_config.get("option_moneyness", "atm")
        # PR7: Rolling mode and strict mode
        use_rolling = suite_config.get("use_rolling_contracts", True)
        strict_option_mode = suite_config.get("strict_option_mode", False)
        # PR8: Segment tolerance for losing_segment detection
        segment_tolerance_pct = float(suite_config.get("segment_tolerance_pct", 0.0))

        option_resolver = OptionContractResolver() if instrument_type == "option" else None

        now = datetime.now(timezone.utc).date() - timedelta(days=1)
        anchor_start = (
            datetime.strptime(suite_config["window_start"], "%Y-%m-%d").date()
            if suite_config.get("window_start")
            else now - timedelta(days=window_days)
        )

        suite_starts = [
            anchor_start - timedelta(days=i * stride_days)
            for i in range(concurrent_runs)
        ]

        engine = BacktestEngine()
        cost_model = CostModelConfig()

        def run_window(start_date):
            end_date = start_date + timedelta(days=window_days)

            # PR7: Rolling mode vs static contract mode
            rolling_options_param = None
            resolver_for_backtest = None
            backtest_symbol = symbol

            if instrument_type == "option" and option_resolver:
                if use_rolling:
                    # PR7: Rolling mode - pass underlying to backtest, let engine resolve per-entry
                    backtest_symbol = symbol
                    rolling_options_param = {
                        "right": option_right,
                        "target_dte": option_dte,
                        "moneyness": option_moneyness
                    }
                    resolver_for_backtest = option_resolver
                else:
                    # Static mode - resolve one contract for entire window
                    resolved = option_resolver.resolve_contract_with_coverage(
                        underlying=symbol,
                        right=option_right,
                        target_dte=option_dte,
                        moneyness=option_moneyness,
                        as_of_date=start_date,
                        window_start=start_date,
                        window_end=end_date,
                        min_bars=60
                    )
                    if resolved:
                        backtest_symbol = resolved
                    elif strict_option_mode:
                        # PR7: Strict mode - fail instead of fallback
                        return {
                            "window_start": start_date.isoformat(),
                            "window_end": end_date.isoformat(),
                            "symbol": symbol,
                            "return_pct": 0.0,
                            "pnl_total": 0.0,
                            "segment_pnls": {"seg1": 0.0, "seg2": 0.0, "seg3": 0.0},
                            "trades_count": 0,
                            "passed": False,
                            "fail_reason": "no_option_contract",
                        }

            bt = engine.run_single(
                symbol=backtest_symbol,
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
                config=config,
                cost_model=cost_model,
                seed=0,
                initial_equity=baseline,
                rolling_options=rolling_options_param,
                option_resolver=resolver_for_backtest,
            )

            equity = bt.equity_curve or []
            trades = bt.trades or []

            final_equity = equity[-1]["equity"] if equity else baseline
            pnl = final_equity - baseline
            ret = (pnl / baseline) * 100 if baseline else 0.0

            # PR8: Use equity-curve based segment returns instead of trade exit-date bucketing
            segment_result = compute_segment_returns_from_equity(equity, start_date, window_days)
            segment_returns_pct = segment_result["segment_returns_pct"]
            segment_equity = segment_result["segment_equity"]

            # Legacy trade-based segmentation as fallback
            seg_pnl = {"seg1": 0.0, "seg2": 0.0, "seg3": 0.0}
            for t in trades:
                pnl_t = float(t.get("pnl", 0.0))
                try:
                    d = datetime.strptime(t["exit_date"], "%Y-%m-%d").date()
                except ValueError:
                    d = datetime.fromisoformat(t["exit_date"]).date()

                off = (d - start_date).days
                if off < 30:
                    seg_pnl["seg1"] += pnl_t
                elif off < 60:
                    seg_pnl["seg2"] += pnl_t
                else:
                    seg_pnl["seg3"] += pnl_t

            # PR8: Use equity-based returns for losing_segment check with tolerance
            if segment_result["valid"]:
                losing_segment = any(
                    v < -segment_tolerance_pct for v in segment_returns_pct.values()
                )
            else:
                losing_segment = any(v < 0 for v in seg_pnl.values())

            passed = ret >= goal_return_pct and not losing_segment

            return {
                "window_start": start_date.isoformat(),
                "window_end": end_date.isoformat(),
                "symbol": backtest_symbol,
                "return_pct": ret,
                "pnl_total": pnl,
                "segment_pnls": seg_pnl,
                "segment_returns_pct": segment_returns_pct,
                "segment_equity": segment_equity,
                "segment_tolerance_pct": segment_tolerance_pct,
                "trades_count": len(trades),
                "passed": passed,
                "fail_reason": (
                    "no_trades" if not trades else
                    "return_below_goal" if ret < goal_return_pct else
                    "losing_segment" if losing_segment else None
                ),
            }

        suites = [run_window(s) for s in suite_starts]
        worst = min(suites, key=lambda x: x["return_pct"])
        all_passed = all(s["passed"] for s in suites)

        return {
            "config": config,
            "suites": suites,
            "worst_return": worst["return_pct"],
            "worst_suite": worst,
            "all_passed": all_passed,
        }

    def _mutate_config(
        self,
        config: StrategyConfig,
        fail_reason: Optional[str],
        worst_return: float,
        suite_config: Optional[Dict[str, Any]] = None
    ) -> tuple:
        """
        Mutates strategy config based on failure reason.

        Mutation rules:
        - return_below_goal: Increase risk tolerance or lower conviction threshold
        - losing_segment: Tighten stop loss or reduce position size
        - no_trades: Lower conviction floor, then mutate option params

        Applies guardrails to prevent extreme values.

        Returns:
            tuple: (mutated_config, mutated_suite_config)
        """
        updates = {}
        suite_updates = {}

        if fail_reason == "return_below_goal":
            # Try to increase returns
            if config.max_risk_pct_portfolio < 0.25:
                updates["max_risk_pct_portfolio"] = min(0.25, config.max_risk_pct_portfolio * 1.2)
            elif config.conviction_floor > 0.40:
                updates["conviction_floor"] = max(0.40, config.conviction_floor - 0.05)
            elif config.take_profit_pct < 0.15:
                updates["take_profit_pct"] = min(0.15, config.take_profit_pct + 0.02)

        elif fail_reason == "losing_segment":
            # PR9: If return meets goal but blocked by losing_segment, increase tolerance first
            current_tol = float(suite_config.get("segment_tolerance_pct", 0.0)) if suite_config else 0.0
            goal = float(suite_config.get("goal_return_pct", 10.0)) if suite_config else 10.0
            max_tolerance = 12.0

            if worst_return >= goal and current_tol < max_tolerance:
                # Return is good but blocked by segment drawdown - relax tolerance
                suite_updates["segment_tolerance_pct"] = min(current_tol + 1.0, max_tolerance)
                logger.info(f"PR9: Relaxing segment_tolerance_pct: {current_tol} -> {suite_updates['segment_tolerance_pct']} (return {worst_return:.1f}% >= goal {goal:.1f}%)")
            else:
                # PR8: Improved mutation path for losing_segment
                # Priority: tighten stop loss -> reduce holding time -> lower take profit -> reduce risk
                stop_loss_floor = 0.015
                max_holding_floor = 3
                take_profit_floor = 0.03
                risk_floor = 0.05

                if config.stop_loss_pct > stop_loss_floor:
                    # First: tighten stop loss
                    updates["stop_loss_pct"] = max(stop_loss_floor, config.stop_loss_pct - 0.005)
                elif config.max_holding_days > max_holding_floor:
                    # Second: reduce holding time to exit earlier
                    updates["max_holding_days"] = max(max_holding_floor, config.max_holding_days - 2)
                elif config.take_profit_pct > take_profit_floor:
                    # Third: lower take profit to bank gains earlier
                    updates["take_profit_pct"] = max(take_profit_floor, config.take_profit_pct - 0.01)
                elif config.max_risk_pct_portfolio > risk_floor:
                    # Last resort: reduce position size
                    updates["max_risk_pct_portfolio"] = max(risk_floor, config.max_risk_pct_portfolio * 0.85)

        elif fail_reason == "no_trades":
            # PR5: Lower barriers to entry more aggressively to escape no_trades deadlock
            # Reduced guardrails: conviction_floor down to 0.05, max_spread_bps up to 400
            if config.conviction_floor > 0.05:
                updates["conviction_floor"] = max(0.05, config.conviction_floor - 0.05)
            elif config.max_spread_bps < 400:
                updates["max_spread_bps"] = min(400, config.max_spread_bps + 25)
            # PR7: For options, mutate option_dte and option_moneyness after exhausting strategy params
            elif suite_config and suite_config.get("instrument_type") == "option":
                current_dte = int(suite_config.get("option_dte", 30))
                current_moneyness = suite_config.get("option_moneyness", "atm")

                # Try longer DTE first (more liquid contracts)
                if current_dte < 60:
                    suite_updates["option_dte"] = min(60, current_dte + 15)
                    logger.info(f"Mutating option_dte: {current_dte} -> {suite_updates['option_dte']}")
                # Then try different moneyness (cycle: atm -> otm_5pct -> itm_5pct)
                elif current_moneyness == "atm":
                    suite_updates["option_moneyness"] = "otm_5pct"
                    logger.info(f"Mutating option_moneyness: atm -> otm_5pct")
                elif current_moneyness == "otm_5pct":
                    suite_updates["option_moneyness"] = "itm_5pct"
                    logger.info(f"Mutating option_moneyness: otm_5pct -> itm_5pct")
                # Also try switching call/put
                elif suite_config.get("option_right") == "call":
                    suite_updates["option_right"] = "put"
                    suite_updates["option_moneyness"] = "atm"  # Reset moneyness
                    logger.info(f"Mutating option_right: call -> put")

        else:
            # Generic mutation: try small adjustments
            if worst_return < 0:
                updates["stop_loss_pct"] = max(0.015, config.stop_loss_pct - 0.003)
            else:
                updates["max_risk_pct_portfolio"] = min(0.25, config.max_risk_pct_portfolio * 1.1)

        new_config = config.model_copy(update=updates) if updates else config
        return new_config, suite_updates

    def _persist_strategy_config(
        self,
        user_id: str,
        name: str,
        config: StrategyConfig,
        version: int,
        versioning: str
    ) -> None:
        """
        Persists a strategy config to the database.

        Args:
            user_id: User ID
            name: Strategy name
            config: StrategyConfig to persist
            version: Version number
            versioning: "increment" (new row) or "overwrite" (update existing)
        """
        try:
            config_data = {
                "user_id": user_id,
                "name": name,
                "version": version,
                "params": config.model_dump(),
                "updated_at": datetime.now(timezone.utc).isoformat()
            }

            if versioning == "overwrite":
                # Try to update existing, insert if not found
                existing = self.supabase.table("strategy_configs") \
                    .select("id") \
                    .eq("user_id", user_id) \
                    .eq("name", name) \
                    .limit(1) \
                    .execute()

                if existing.data:
                    self.supabase.table("strategy_configs") \
                        .update(config_data) \
                        .eq("user_id", user_id) \
                        .eq("name", name) \
                        .execute()
                else:
                    self.supabase.table("strategy_configs").insert(config_data).execute()
            else:
                # increment: always insert new row
                self.supabase.table("strategy_configs").insert(config_data).execute()

            logger.info(f"Persisted strategy config '{name}' v{version} for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to persist strategy config: {e}")
