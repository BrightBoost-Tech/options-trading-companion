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
        option_right = suite_config.get("option_right", "call")
        option_dte = int(suite_config.get("option_dte", 30))
        option_moneyness = suite_config.get("option_moneyness", "atm")

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

            # PR3: Resolve option symbol if instrument_type == "option"
            backtest_symbol = symbol
            if instrument_type == "option" and option_resolver:
                resolved = option_resolver.resolve_contract(
                    underlying=symbol,
                    right=option_right,
                    target_dte=option_dte,
                    moneyness=option_moneyness,
                    as_of_date=start_date
                )
                if resolved:
                    backtest_symbol = resolved
                    logger.info(f"Resolved option contract: {resolved} for window starting {start_date}")
                else:
                    logger.warning(f"Could not resolve option contract for {symbol} as of {start_date}, using underlying")

            bt = engine.run_single(
                symbol=backtest_symbol,
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
                config=cfg,
                cost_model=cost_model,
                seed=0,
                initial_equity=baseline,
            )

            equity = bt.equity_curve or []
            trades = bt.trades or []

            final_equity = equity[-1]["equity"] if equity else baseline
            pnl = final_equity - baseline
            ret = (pnl / baseline) * 100 if baseline else 0.0

            seg = {"seg1": 0.0, "seg2": 0.0, "seg3": 0.0}
            for t in trades:
                pnl_t = float(t.get("pnl", 0.0))
                # Handle possible date formats in trades, assuming ISO or YYYY-MM-DD
                try:
                    d = datetime.strptime(t["exit_date"], "%Y-%m-%d").date()
                except ValueError:
                    d = datetime.fromisoformat(t["exit_date"]).date()

                off = (d - start_date).days
                if off < 30:
                    seg["seg1"] += pnl_t
                elif off < 60:
                    seg["seg2"] += pnl_t
                else:
                    seg["seg3"] += pnl_t

            losing_segment = any(v < 0 for v in seg.values())
            passed = ret >= goal_return_pct and not losing_segment

            return {
                "window_start": start_date.isoformat(),
                "window_end": end_date.isoformat(),
                "symbol": backtest_symbol,  # PR3: Include actual symbol used
                "return_pct": ret,
                "pnl_total": pnl,
                "segment_pnls": seg,
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
