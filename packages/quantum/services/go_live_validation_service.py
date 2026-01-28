import uuid
import logging
import os
from datetime import datetime, timedelta, timezone, date
from typing import Dict, Any, Optional, List, Literal, Tuple
from supabase import Client
import math

from packages.quantum.services.backtest_engine import BacktestEngine
from packages.quantum.strategy_profiles import StrategyConfig, CostModelConfig
from packages.quantum.services.option_contract_resolver import OptionContractResolver

logger = logging.getLogger(__name__)


# =============================================================================
# Rolling Paper Streak Configuration
# =============================================================================

# Rolling window size for daily checkpoint (default 14 days = 2 weeks)
PAPER_STREAK_WINDOW_DAYS = int(os.getenv("PAPER_STREAK_WINDOW_DAYS", "14"))

# Checkpoint mode: "rolling" (continuous daily) or "fixed" (end-of-window only)
PAPER_STREAK_CHECKPOINT_MODE = os.getenv("PAPER_STREAK_CHECKPOINT_MODE", "rolling")

# Minimum return threshold for rolling window pass (default 2% for 2-week window)
PAPER_STREAK_MIN_RETURN_PCT = float(os.getenv("PAPER_STREAK_MIN_RETURN_PCT", "2.0"))

# Required consecutive passing days to achieve paper_ready
PAPER_STREAK_REQUIRED_DAYS = int(os.getenv("PAPER_STREAK_REQUIRED_DAYS", "14"))


# =============================================================================
# DST-Safe Chicago Day Window Helpers
# =============================================================================

def chicago_day_window_utc(now_utc: datetime) -> Tuple[datetime, datetime]:
    """
    Compute the Chicago day window [00:00, next day 00:00) in UTC.

    Uses ZoneInfo for proper DST handling (CDT = UTC-5, CST = UTC-6).
    Falls back to UTC-6 approximation if ZoneInfo unavailable.

    Args:
        now_utc: Current time in UTC (must be timezone-aware)

    Returns:
        Tuple of (start_utc, end_utc) representing the Chicago day boundaries in UTC.
    """
    try:
        from zoneinfo import ZoneInfo
        chicago_tz = ZoneInfo("America/Chicago")

        # Convert UTC to Chicago time
        now_chicago = now_utc.astimezone(chicago_tz)

        # Get start of day in Chicago (00:00:00)
        day_start_chicago = now_chicago.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end_chicago = day_start_chicago + timedelta(days=1)

        # Convert back to UTC
        start_utc = day_start_chicago.astimezone(timezone.utc)
        end_utc = day_end_chicago.astimezone(timezone.utc)

        return (start_utc, end_utc)

    except Exception as e:
        logger.warning(f"ZoneInfo unavailable, using UTC-6 fallback for Chicago window: {e}")
        # Fallback: Use CST (UTC-6) as conservative approximation
        # This is safe because it errs on the side of a wider window
        chicago_offset = timedelta(hours=-6)
        now_chicago = now_utc + chicago_offset
        day_start_chicago = now_chicago.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end_chicago = day_start_chicago + timedelta(days=1)

        start_utc = day_start_chicago - chicago_offset
        end_utc = day_end_chicago - chicago_offset

        return (start_utc, end_utc)


def is_weekend_chicago(now_utc: datetime) -> bool:
    """
    Check if the current time is a weekend (Saturday or Sunday) in Chicago timezone.

    Uses ZoneInfo for proper DST handling (CDT = UTC-5, CST = UTC-6).
    Falls back to UTC-6 approximation if ZoneInfo unavailable.

    Args:
        now_utc: Current time in UTC (must be timezone-aware)

    Returns:
        True if it's Saturday or Sunday in Chicago, False otherwise.
    """
    try:
        from zoneinfo import ZoneInfo
        chicago_tz = ZoneInfo("America/Chicago")
        now_chicago = now_utc.astimezone(chicago_tz)
        return now_chicago.weekday() >= 5  # Saturday=5, Sunday=6

    except Exception as e:
        logger.warning(f"ZoneInfo unavailable, using UTC-6 fallback for weekend check: {e}")
        # Fallback: Use CST (UTC-6) as conservative approximation
        chicago_offset = timedelta(hours=-6)
        now_chicago = now_utc + chicago_offset
        return now_chicago.weekday() >= 5


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

        New fields for rolling streak (Phase 2.1):
        - paper_streak_days: Consecutive passing days (reset on fail)
        - paper_last_checkpoint_at: Last daily checkpoint timestamp
        - paper_checkpoint_window_days: Rolling window size used
        """
        try:
            res = self.supabase.table("v3_go_live_state").select("*").eq("user_id", user_id).single().execute()
            if res.data:
                # Ensure new fields have defaults for existing records
                state = res.data
                if "paper_streak_days" not in state or state.get("paper_streak_days") is None:
                    state["paper_streak_days"] = 0
                if "paper_last_checkpoint_at" not in state:
                    state["paper_last_checkpoint_at"] = None
                if "paper_checkpoint_window_days" not in state or state.get("paper_checkpoint_window_days") is None:
                    state["paper_checkpoint_window_days"] = PAPER_STREAK_WINDOW_DAYS
                return state
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
            "overall_ready": False,
            # Rolling streak fields (Phase 2.1)
            "paper_streak_days": 0,
            "paper_last_checkpoint_at": None,
            "paper_checkpoint_window_days": PAPER_STREAK_WINDOW_DAYS
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

    def checkpoint_paper_streak(
        self,
        user_id: str,
        now: Optional[datetime] = None,
        force: bool = False
    ) -> Dict[str, Any]:
        """
        Daily checkpoint for rolling paper trading streak (Phase 2.1).

        *** v4-L1F GUARD: This is the LEGACY rolling streak mechanism. ***
        *** For Phase 3 go-live streak, use eval_paper_forward_checkpoint() instead. ***
        *** validation_eval MUST call eval_paper_forward_checkpoint, NOT this method. ***
        *** If called from validation_eval, this should be a NO-OP or shadow-only. ***

        This method:
        1. Checks idempotency (already run today?) unless force=True
        2. Calculates rolling window return (last PAPER_STREAK_WINDOW_DAYS days)
        3. Pass/fail with streak increment/reset
        4. Updates paper_ready if streak hits PAPER_STREAK_REQUIRED_DAYS

        Args:
            user_id: User ID
            now: Override timestamp for testing
            force: Skip idempotency check (for testing)

        Returns:
            Dict with checkpoint results:
            - status: "skipped" | "pass" | "fail"
            - streak_days: Current streak after this checkpoint
            - rolling_return_pct: Return over rolling window
            - paper_ready: Whether user is now paper_ready
            - window_start/window_end: Rolling window boundaries
            - idempotency_key: Date string for this checkpoint
        """
        if now is None:
            now = datetime.now(timezone.utc)

        state = self.get_or_create_state(user_id)
        baseline = float(state.get("paper_baseline_capital", 100000) or 100000)

        # 1. Idempotency check
        today_key = now.date().isoformat()
        last_checkpoint = state.get("paper_last_checkpoint_at")

        if not force and last_checkpoint:
            try:
                last_date = datetime.fromisoformat(last_checkpoint).date()
                if last_date >= now.date():
                    return {
                        "status": "skipped",
                        "reason": "already_checkpointed_today",
                        "idempotency_key": today_key,
                        "streak_days": state.get("paper_streak_days", 0),
                        "paper_ready": state.get("paper_ready", False)
                    }
            except (ValueError, TypeError):
                pass  # Invalid date, proceed with checkpoint

        # 2. Calculate rolling window return
        window_days = state.get("paper_checkpoint_window_days") or PAPER_STREAK_WINDOW_DAYS
        window_start = now - timedelta(days=window_days)
        window_end = now

        pnl_total = 0.0
        trade_count = 0

        try:
            res = self.supabase.table("learning_trade_outcomes_v3") \
                .select("closed_at, pnl_realized") \
                .eq("user_id", user_id) \
                .eq("is_paper", True) \
                .gte("closed_at", window_start.isoformat()) \
                .lte("closed_at", window_end.isoformat()) \
                .execute()

            rows = res.data or []
            for r in rows:
                pnl = float(r.get("pnl_realized") or 0.0)
                pnl_total += pnl
                trade_count += 1

        except Exception as e:
            logger.error(f"Error calculating rolling paper metrics: {e}")
            return {
                "status": "error",
                "error": str(e),
                "idempotency_key": today_key,
                "streak_days": state.get("paper_streak_days", 0),
                "paper_ready": state.get("paper_ready", False)
            }

        rolling_return_pct = (pnl_total / baseline) * 100 if baseline > 0 else 0.0

        # 3. Pass/fail determination
        # Pass if return >= minimum threshold (default 2% for 2-week window)
        min_return = PAPER_STREAK_MIN_RETURN_PCT
        passed = rolling_return_pct >= min_return

        # 4. Update streak
        current_streak = state.get("paper_streak_days", 0)
        if passed:
            new_streak = current_streak + 1
        else:
            new_streak = 0  # Reset on fail

        # 5. Check if paper_ready threshold reached
        paper_ready_from_streak = new_streak >= PAPER_STREAK_REQUIRED_DAYS

        # Combine with existing paper_ready (don't downgrade if already ready from 90-day eval)
        existing_paper_ready = state.get("paper_ready", False)
        paper_ready = existing_paper_ready or paper_ready_from_streak

        # 6. Persist checkpoint
        updates = {
            "paper_streak_days": new_streak,
            "paper_last_checkpoint_at": now.isoformat(),
            "paper_ready": paper_ready,
            "updated_at": now.isoformat()
        }

        # Update overall_ready if paper_ready changed
        if paper_ready and not existing_paper_ready:
            hist_res = state.get("historical_last_result") or {}
            hist_passed = hist_res.get("passed", False)
            hist_ts_str = state.get("historical_last_run_at")

            hist_recent = False
            if hist_ts_str:
                try:
                    hist_ts = datetime.fromisoformat(hist_ts_str)
                    if (now - hist_ts).days <= 30:
                        hist_recent = True
                except (ValueError, TypeError):
                    pass

            updates["overall_ready"] = paper_ready and hist_passed and hist_recent

        self.supabase.table("v3_go_live_state").update(updates).eq("user_id", user_id).execute()

        # 7. Log to v3_go_live_runs for audit trail
        run_data = {
            "user_id": user_id,
            "mode": "paper_checkpoint",
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "return_pct": rolling_return_pct,
            "pnl_total": pnl_total,
            "segment_pnls": {},  # N/A for rolling checkpoint
            "passed": passed,
            "fail_reason": None if passed else "rolling_return_below_threshold",
            "details_json": {
                "checkpoint_date": today_key,
                "trade_count": trade_count,
                "streak_before": current_streak,
                "streak_after": new_streak,
                "min_return_threshold": min_return,
                "window_days": window_days
            }
        }
        self.supabase.table("v3_go_live_runs").insert(run_data).execute()

        return {
            "status": "pass" if passed else "fail",
            "streak_days": new_streak,
            "streak_before": current_streak,
            "rolling_return_pct": rolling_return_pct,
            "min_return_threshold": min_return,
            "trade_count": trade_count,
            "paper_ready": paper_ready,
            "paper_ready_from_streak": paper_ready_from_streak,
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "window_days": window_days,
            "idempotency_key": today_key
        }

    # =========================================================================
    # v4-L1: Forward Checkpoint Evaluation (Rolling + Fail-Fast)
    # =========================================================================

    def _checkpoint_bucket(self, ts: datetime, cadence: str = "daily") -> str:
        """
        Compute checkpoint bucket key for deduplication.

        Args:
            ts: Timestamp to bucket
            cadence: Bucket cadence ("daily" for now)

        Returns:
            Bucket key string (e.g., "2024-01-15" for daily)
        """
        if cadence == "daily":
            return ts.date().isoformat()
        # Future: support "hourly", "4h", etc.
        return ts.date().isoformat()

    def _ensure_forward_checkpoint_defaults(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Ensure forward checkpoint fields have defaults.

        Args:
            state: Current state dict

        Returns:
            State dict with defaults applied (mutates in place)
        """
        # paper_window_days: default 21 (3 weeks)
        if state.get("paper_window_days") is None:
            state["paper_window_days"] = 21

        # paper_checkpoint_target: default 10
        if state.get("paper_checkpoint_target") is None:
            state["paper_checkpoint_target"] = 10

        # paper_fail_fast_triggered: default False
        if state.get("paper_fail_fast_triggered") is None:
            state["paper_fail_fast_triggered"] = False

        # paper_fail_fast_reason: default None (OK)
        # paper_checkpoint_last_run_at: default None (OK)

        return state

    def _repair_window_if_needed(
        self,
        state: Dict[str, Any],
        now: datetime
    ) -> Tuple[datetime, datetime, bool]:
        """
        Repair paper_window_start/end if missing or invalid.

        Args:
            state: Current state dict
            now: Current timestamp

        Returns:
            Tuple of (window_start, window_end, was_repaired)
        """
        window_days = state.get("paper_window_days") or 21
        was_repaired = False

        # Parse existing values
        window_start = None
        window_end = None

        try:
            if state.get("paper_window_start"):
                window_start = datetime.fromisoformat(state["paper_window_start"])
                if window_start.tzinfo is None:
                    window_start = window_start.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            pass

        try:
            if state.get("paper_window_end"):
                window_end = datetime.fromisoformat(state["paper_window_end"])
                if window_end.tzinfo is None:
                    window_end = window_end.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            pass

        # Repair if missing or invalid
        if window_start is None or window_end is None:
            window_start = now
            window_end = now + timedelta(days=window_days)
            was_repaired = True
        elif window_end <= window_start:
            # Invalid: end before start
            window_start = now
            window_end = now + timedelta(days=window_days)
            was_repaired = True

        return window_start, window_end, was_repaired

    def _compute_drawdown(self, outcomes: List[Dict[str, Any]], baseline: float) -> float:
        """
        Compute max drawdown from outcomes using peak-to-trough on cumulative PnL.

        Args:
            outcomes: List of outcome dicts with pnl_realized
            baseline: Baseline capital

        Returns:
            Max drawdown as negative percentage (e.g., -0.03 for -3%)
        """
        if not outcomes or baseline <= 0:
            return 0.0

        # Sort by closed_at
        sorted_outcomes = sorted(
            outcomes,
            key=lambda x: x.get("closed_at", "")
        )

        # Build cumulative PnL curve
        cumulative_pnl = 0.0
        peak_pnl = 0.0
        max_drawdown = 0.0

        for outcome in sorted_outcomes:
            pnl = float(outcome.get("pnl_realized") or 0.0)
            cumulative_pnl += pnl

            # Update peak
            if cumulative_pnl > peak_pnl:
                peak_pnl = cumulative_pnl

            # Calculate drawdown from peak
            if peak_pnl > 0:
                drawdown = (cumulative_pnl - peak_pnl) / baseline
            else:
                drawdown = cumulative_pnl / baseline if cumulative_pnl < 0 else 0.0

            # Track worst drawdown
            if drawdown < max_drawdown:
                max_drawdown = drawdown

        return max_drawdown

    def _log_checkpoint_run(
        self,
        user_id: str,
        mode: str,
        window_start: datetime,
        window_end: datetime,
        return_pct: float,
        pnl_total: float,
        passed: bool,
        fail_reason: Optional[str],
        details: Dict[str, Any]
    ) -> None:
        """
        Log a checkpoint run to v3_go_live_runs.

        Args:
            user_id: User ID
            mode: Run mode (paper_checkpoint, paper_fail_fast, paper_window_final)
            window_start: Window start timestamp
            window_end: Window end timestamp
            return_pct: Return percentage
            pnl_total: Total PnL
            passed: Whether checkpoint passed
            fail_reason: Failure reason if applicable
            details: Additional details dict
        """
        try:
            run_data = {
                "user_id": user_id,
                "mode": mode,
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
                "return_pct": return_pct,
                "pnl_total": pnl_total,
                "segment_pnls": {},
                "passed": passed,
                "fail_reason": fail_reason,
                "details_json": details
            }
            self.supabase.table("v3_go_live_runs").insert(run_data).execute()
        except Exception as e:
            logger.error(f"Failed to log checkpoint run: {e}")

    def _get_paper_forward_policy_overrides(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        v4-L1E: Extract paper forward policy overrides from state.

        Reads state.paper_forward_policy JSONB and returns a dict of override values.
        Only returns keys that are present and valid.

        Supported overrides:
        - paper_window_days: int
        - target_return_pct: float (decimal, e.g., 0.10)
        - fail_fast_drawdown_pct: float (decimal, e.g., -0.03)
        - fail_fast_return_pct: float (decimal, e.g., -0.02)
        """
        policy = state.get("paper_forward_policy") or {}
        if not isinstance(policy, dict):
            return {}

        overrides = {}

        # Extract and validate each override
        if "paper_window_days" in policy:
            try:
                overrides["paper_window_days"] = int(policy["paper_window_days"])
            except (ValueError, TypeError):
                pass

        if "target_return_pct" in policy:
            try:
                overrides["target_return_pct"] = float(policy["target_return_pct"])
            except (ValueError, TypeError):
                pass

        if "fail_fast_drawdown_pct" in policy:
            try:
                overrides["fail_fast_drawdown_pct"] = float(policy["fail_fast_drawdown_pct"])
            except (ValueError, TypeError):
                pass

        if "fail_fast_return_pct" in policy:
            try:
                overrides["fail_fast_return_pct"] = float(policy["fail_fast_return_pct"])
            except (ValueError, TypeError):
                pass

        return overrides

    # =========================================================================
    # Phase 3 Hardening: Patchable DB Read Seams
    # =========================================================================
    # These helper methods encapsulate DB reads used in the "no outcomes" branch
    # of eval_paper_forward_checkpoint. They exist to enable deterministic testing
    # without complex Supabase query-chain mocking.

    def _get_paper_portfolio_ids(self, user_id: str) -> List[str]:
        """Get paper portfolio IDs for a user."""
        try:
            res = self.supabase.table("paper_portfolios").select("id").eq("user_id", user_id).execute()
            return [p["id"] for p in (res.data or [])]
        except Exception as e:
            logger.warning(f"Failed to get paper portfolios for user {user_id}: {e}")
            return []

    def _has_open_paper_positions(self, portfolio_ids: List[str]) -> bool:
        """Check if any open positions (quantity != 0) exist in given portfolios."""
        if not portfolio_ids:
            return False
        try:
            res = self.supabase.table("paper_positions") \
                .select("id") \
                .in_("portfolio_id", portfolio_ids) \
                .neq("quantity", 0) \
                .limit(1) \
                .execute()
            return bool(res.data)
        except Exception as e:
            logger.warning(f"Failed to check open positions: {e}")
            return False

    def _recent_paper_fills_count(self, portfolio_ids: List[str], since_utc: datetime) -> int:
        """Count recent filled orders (ingestion lag detection)."""
        if not portfolio_ids:
            return 0
        try:
            res = self.supabase.table("paper_orders") \
                .select("id") \
                .in_("portfolio_id", portfolio_ids) \
                .eq("status", "filled") \
                .gte("filled_at", since_utc.isoformat()) \
                .execute()
            return len(res.data or [])
        except Exception as e:
            logger.warning(f"Failed to count recent fills: {e}")
            return 0

    def _pending_suggestion_ids(self, user_id: str, start_utc: datetime, end_utc: datetime) -> List[str]:
        """Get pending suggestion IDs in the given time window."""
        try:
            res = self.supabase.table("trade_suggestions") \
                .select("id") \
                .eq("user_id", user_id) \
                .gte("created_at", start_utc.isoformat()) \
                .lt("created_at", end_utc.isoformat()) \
                .eq("status", "pending") \
                .execute()
            return [s["id"] for s in (res.data or [])]
        except Exception as e:
            logger.warning(f"Failed to get pending suggestions for user {user_id}: {e}")
            return []

    def _has_linked_orders(self, portfolio_ids: List[str], suggestion_ids: List[str], start_utc: datetime, end_utc: datetime) -> bool:
        """Check if any orders exist that are linked to the given suggestions."""
        if not portfolio_ids or not suggestion_ids:
            return False
        try:
            res = self.supabase.table("paper_orders") \
                .select("id") \
                .in_("portfolio_id", portfolio_ids) \
                .gte("created_at", start_utc.isoformat()) \
                .lt("created_at", end_utc.isoformat()) \
                .in_("suggestion_id", suggestion_ids) \
                .limit(1) \
                .execute()
            return bool(res.data)
        except Exception as e:
            logger.warning(f"Failed to check linked orders: {e}")
            return False

    def eval_paper_forward_checkpoint(
        self,
        user_id: str,
        now: Optional[datetime] = None,
        fail_fast_drawdown_pct: float = -0.03,
        fail_fast_return_pct: float = -0.02,
        target_return_pct: float = 0.10
    ) -> Dict[str, Any]:
        """
        v4-L1: Forward checkpoint evaluation with rolling checkpoints and fail-fast.

        This method implements:
        - Daily checkpoint deduplication (one checkpoint per bucket)
        - Window expiry handling with finalization
        - Fail-fast rules (drawdown, total return)
        - Pacing target (progress-based return target)
        - v4-L1E: Per-user policy overrides from state.paper_forward_policy

        Args:
            user_id: User ID
            now: Override timestamp for testing
            fail_fast_drawdown_pct: Max drawdown before fail-fast (default -3%)
            fail_fast_return_pct: Min return before fail-fast (default -2%)
            target_return_pct: Target return at window end (default 10%)

        Returns:
            Dict with checkpoint results:
            - status: "skipped" | "pass" | "miss" | "fail_fast" | "window_final"
            - paper_consecutive_passes: Current streak
            - paper_ready: Whether user achieved paper_ready
            - return_pct: Total return in window
            - target_return_now: Current pacing target
            - max_drawdown_pct: Max drawdown observed
            - progress: Window progress (0.0 to 1.0)
        """
        if now is None:
            now = datetime.now(timezone.utc)

        # Ensure timezone awareness
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        # 1. Load and prepare state
        state = self.get_or_create_state(user_id)
        state = self._ensure_forward_checkpoint_defaults(state)

        # v4-L1E: Apply policy overrides from state
        policy_overrides = self._get_paper_forward_policy_overrides(state)
        if policy_overrides:
            if "fail_fast_drawdown_pct" in policy_overrides:
                fail_fast_drawdown_pct = policy_overrides["fail_fast_drawdown_pct"]
            if "fail_fast_return_pct" in policy_overrides:
                fail_fast_return_pct = policy_overrides["fail_fast_return_pct"]
            if "target_return_pct" in policy_overrides:
                target_return_pct = policy_overrides["target_return_pct"]
            logger.info(f"Applied policy overrides for user {user_id}: {policy_overrides}")

        baseline = float(state.get("paper_baseline_capital", 100000) or 100000)
        window_days = policy_overrides.get("paper_window_days") or state.get("paper_window_days") or 21
        checkpoint_target = state.get("paper_checkpoint_target") or 10

        # 2. Repair window if needed
        window_start, window_end, was_repaired = self._repair_window_if_needed(state, now)

        if was_repaired:
            # Persist repaired window
            self.supabase.table("v3_go_live_state").update({
                "paper_window_start": window_start.isoformat(),
                "paper_window_end": window_end.isoformat(),
                "updated_at": now.isoformat()
            }).eq("user_id", user_id).execute()
            logger.info(f"Repaired paper window for user {user_id}")

        # 3. Checkpoint deduplication (official checkpoints only)
        # Note: Shadow checkpoints do NOT participate in deduplication - they are side-effect free
        # and can run multiple times per bucket without state mutation.
        bucket_key = self._checkpoint_bucket(now)
        last_run_at = state.get("paper_checkpoint_last_run_at")

        if last_run_at:
            try:
                last_run_ts = datetime.fromisoformat(last_run_at)
                if last_run_ts.tzinfo is None:
                    last_run_ts = last_run_ts.replace(tzinfo=timezone.utc)
                last_bucket = self._checkpoint_bucket(last_run_ts)

                if last_bucket == bucket_key:
                    # v4-L1F Optimization: Log deduplication for observability
                    logger.info(
                        f"Checkpoint dedup for user {user_id}: "
                        f"bucket={bucket_key}, last_run={last_run_at}, "
                        f"streak={state.get('paper_consecutive_passes', 0)}"
                    )
                    return {
                        "status": "skipped",
                        "reason": "already_checkpointed_this_bucket",
                        "bucket": bucket_key,
                        "last_run_at": last_run_at,
                        "paper_consecutive_passes": state.get("paper_consecutive_passes", 0),
                        "paper_ready": state.get("paper_ready", False)
                    }
            except (ValueError, TypeError):
                logger.warning(f"Invalid last_run_at timestamp for user {user_id}: {last_run_at}")
                pass  # Invalid timestamp, proceed

        # 4. Check for window expiry
        if now >= window_end:
            return self._finalize_paper_window_forward(
                user_id, state, now, window_start, window_end,
                baseline, window_days, checkpoint_target, target_return_pct
            )

        # 5. Fetch outcomes for active window
        outcomes = []
        try:
            res = self.supabase.table("learning_trade_outcomes_v3") \
                .select("closed_at, pnl_realized, profit_pct") \
                .eq("user_id", user_id) \
                .eq("is_paper", True) \
                .gte("closed_at", window_start.isoformat()) \
                .lte("closed_at", now.isoformat()) \
                .order("closed_at", desc=False) \
                .execute()
            outcomes = res.data or []
        except Exception as e:
            logger.error(f"Error fetching paper outcomes: {e}")

        # 6. Calculate metrics
        total_pnl = sum(float(o.get("pnl_realized") or 0.0) for o in outcomes)
        total_return_pct = (total_pnl / baseline) if baseline > 0 else 0.0
        max_drawdown_pct = self._compute_drawdown(outcomes, baseline)

        # 7. Calculate progress and pacing target
        elapsed = (now - window_start).total_seconds()
        duration = (window_end - window_start).total_seconds()
        progress = max(0.0, min(1.0, elapsed / duration)) if duration > 0 else 0.0
        target_return_now = target_return_pct * progress

        # Build base result
        current_streak = state.get("paper_consecutive_passes", 0)
        result_base = {
            "return_pct": total_return_pct * 100,  # Convert to percentage
            "target_return_now": target_return_now * 100,
            "max_drawdown_pct": max_drawdown_pct * 100,
            "progress": progress,
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "bucket": bucket_key,
            "outcome_count": len(outcomes),
            "pnl_total": total_pnl
        }

        # 8. Handle no outcomes yet
        if not outcomes:
            # v4-L1G Hardening (Strict): Strict rules for streak reset on "no outcomes"
            # Constraint: "No outcomes" must NEVER reset streak unless we prove a missed opportunity.
            # In practice, with strict constraints, "no outcomes" almost always results in a SKIP.

            # Statuses:
            # - skipped_non_trading_day: Weekend (Saturday/Sunday in Chicago time)
            # - skipped_no_close_activity: Open positions exist
            # - skipped_no_signal_day: No pending suggestions
            # - skipped_no_signal_day (autopilot_inactive): Suggestions exist but no linked orders
            # - skipped_no_fill_activity: Orders exist but no fills (Ambiguous)

            # A. Weekend Check (Chicago Time)
            # Skip streak evaluation on weekends (no trading activity expected).
            if is_weekend_chicago(now):
                return {
                    **result_base,
                    "status": "skipped_non_trading_day",
                    "reason": "weekend",
                    "paper_consecutive_passes": current_streak,
                    "streak_before": current_streak,
                    "paper_ready": state.get("paper_ready", False)
                }

            # B. Open Positions Check (via portfolio_id join)
            portfolio_ids = self._get_paper_portfolio_ids(user_id)
            if self._has_open_paper_positions(portfolio_ids):
                return {
                    **result_base,
                    "status": "skipped_no_close_activity",
                    "reason": "open_positions_held",
                    "paper_consecutive_passes": current_streak,
                    "streak_before": current_streak,
                    "paper_ready": state.get("paper_ready", False)
                }

            # C. Ingestion Lag Check
            lag_window = now - timedelta(hours=4)
            recent_fills_count = self._recent_paper_fills_count(portfolio_ids, lag_window)

            if recent_fills_count > 0:
                self._log_checkpoint_run(
                    user_id, "paper_checkpoint", window_start, now,
                    0.0, 0.0, False, "ingestion_lag_detected",
                    {"streak_before": current_streak, "recent_fills_count": recent_fills_count}
                )
                return {
                    **result_base,
                    "status": "error",
                    "reason": "ingestion_lag_detected",
                    "paper_consecutive_passes": current_streak,
                    "streak_before": current_streak,
                    "paper_ready": state.get("paper_ready", False)
                }

            # D. Executable Suggestions & Autopilot Activity Check (Strict Linkage)
            # Compute DST-safe Chicago day window using ZoneInfo
            query_start_utc, query_end_utc = chicago_day_window_utc(now)

            # 1. Fetch pending suggestions in window
            pending_suggestion_ids = self._pending_suggestion_ids(user_id, query_start_utc, query_end_utc)

            if not pending_suggestion_ids:
                return {
                    **result_base,
                    "status": "skipped_no_signal_day",
                    "reason": "no_pending_suggestions",
                    "paper_consecutive_passes": current_streak,
                    "streak_before": current_streak,
                    "paper_ready": state.get("paper_ready", False)
                }

            # 2. Check for Linked Orders
            has_linked_orders = self._has_linked_orders(portfolio_ids, pending_suggestion_ids, query_start_utc, query_end_utc)

            if not has_linked_orders:
                return {
                    **result_base,
                    "status": "skipped_no_signal_day",
                    "reason": "autopilot_inactive",
                    "paper_consecutive_passes": current_streak,
                    "streak_before": current_streak,
                    "paper_ready": state.get("paper_ready", False)
                }

            # 3. Ambiguous Path: Suggestions and Linked Orders Exist, but No Outcomes/Positions check matched
            # This implies "No Fill" or "Order active but not filled"
            # STRICT RULE: Never reset streak on No Outcomes.
            return {
                **result_base,
                "status": "skipped_no_fill_activity",
                "reason": "orders_exist_no_outcomes",
                "paper_consecutive_passes": current_streak,
                "streak_before": current_streak,
                "paper_ready": state.get("paper_ready", False)
            }

        # 9. Fail-fast checks
        if max_drawdown_pct <= fail_fast_drawdown_pct:
            return self._handle_fail_fast(
                user_id, state, now, window_start, window_end,
                total_return_pct, total_pnl, max_drawdown_pct,
                f"max_drawdown_exceeded_{max_drawdown_pct*100:.1f}pct",
                window_days, result_base
            )

        if total_return_pct <= fail_fast_return_pct:
            return self._handle_fail_fast(
                user_id, state, now, window_start, window_end,
                total_return_pct, total_pnl, max_drawdown_pct,
                f"total_return_below_{fail_fast_return_pct*100:.1f}pct",
                window_days, result_base
            )

        # 10. Pacing check: pass or miss
        if total_return_pct >= target_return_now:
            # PASS checkpoint
            new_streak = current_streak + 1
            paper_ready = new_streak >= checkpoint_target

            # Clear fail-fast flags if previously set
            updates = {
                "paper_consecutive_passes": new_streak,
                "paper_checkpoint_last_run_at": now.isoformat(),
                "paper_fail_fast_triggered": False,
                "paper_fail_fast_reason": None,
                "updated_at": now.isoformat()
            }

            if paper_ready and not state.get("paper_ready", False):
                updates["paper_ready"] = True

            self.supabase.table("v3_go_live_state").update(updates).eq("user_id", user_id).execute()

            # Log pass
            self._log_checkpoint_run(
                user_id, "paper_checkpoint", window_start, now,
                total_return_pct * 100, total_pnl, True, None,
                {
                    "bucket": bucket_key,
                    "streak_before": current_streak,
                    "streak_after": new_streak,
                    "target": target_return_now * 100,
                    "progress": progress,
                    "drawdown": max_drawdown_pct * 100
                }
            )

            return {
                **result_base,
                "status": "pass",
                "paper_consecutive_passes": new_streak,
                "streak_before": current_streak,
                "paper_ready": paper_ready
            }

        else:
            # MISS checkpoint - reset streak
            updates = {
                "paper_consecutive_passes": 0,
                "paper_checkpoint_last_run_at": now.isoformat(),
                "updated_at": now.isoformat()
            }

            self.supabase.table("v3_go_live_state").update(updates).eq("user_id", user_id).execute()

            # Log miss
            self._log_checkpoint_run(
                user_id, "paper_checkpoint", window_start, now,
                total_return_pct * 100, total_pnl, False, "below_pacing_target",
                {
                    "bucket": bucket_key,
                    "streak_before": current_streak,
                    "streak_after": 0,
                    "target": target_return_now * 100,
                    "progress": progress,
                    "drawdown": max_drawdown_pct * 100
                }
            )

            return {
                **result_base,
                "status": "miss",
                "reason": "below_pacing_target",
                "paper_consecutive_passes": 0,
                "streak_before": current_streak,
                "paper_ready": state.get("paper_ready", False)
            }

    def _handle_fail_fast(
        self,
        user_id: str,
        state: Dict[str, Any],
        now: datetime,
        window_start: datetime,
        window_end: datetime,
        total_return_pct: float,
        total_pnl: float,
        max_drawdown_pct: float,
        reason: str,
        window_days: int,
        result_base: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Handle fail-fast: reset streak and restart window.

        Args:
            user_id: User ID
            state: Current state
            now: Current timestamp
            window_start: Current window start
            window_end: Current window end
            total_return_pct: Total return (decimal)
            total_pnl: Total PnL
            max_drawdown_pct: Max drawdown (decimal)
            reason: Fail-fast reason string
            window_days: Window duration for restart
            result_base: Base result dict

        Returns:
            Fail-fast result dict
        """
        new_window_start = now
        new_window_end = now + timedelta(days=window_days)

        # Update state: reset streak, set fail-fast flags, restart window
        updates = {
            "paper_consecutive_passes": 0,
            "paper_fail_fast_triggered": True,
            "paper_fail_fast_reason": reason,
            "paper_checkpoint_last_run_at": now.isoformat(),
            "paper_window_start": new_window_start.isoformat(),
            "paper_window_end": new_window_end.isoformat(),
            "updated_at": now.isoformat()
        }

        self.supabase.table("v3_go_live_state").update(updates).eq("user_id", user_id).execute()

        # Log fail-fast run
        self._log_checkpoint_run(
            user_id, "paper_fail_fast", window_start, now,
            total_return_pct * 100, total_pnl, False, reason,
            {
                "bucket": result_base.get("bucket"),
                "streak_before": state.get("paper_consecutive_passes", 0),
                "streak_after": 0,
                "drawdown": max_drawdown_pct * 100,
                "new_window_start": new_window_start.isoformat(),
                "new_window_end": new_window_end.isoformat()
            }
        )

        return {
            **result_base,
            "status": "fail_fast",
            "reason": reason,
            "paper_consecutive_passes": 0,
            "streak_before": state.get("paper_consecutive_passes", 0),
            "paper_ready": False,
            "new_window_start": new_window_start.isoformat(),
            "new_window_end": new_window_end.isoformat()
        }

    def _finalize_paper_window_forward(
        self,
        user_id: str,
        state: Dict[str, Any],
        now: datetime,
        window_start: datetime,
        window_end: datetime,
        baseline: float,
        window_days: int,
        checkpoint_target: int,
        target_return_pct: float
    ) -> Dict[str, Any]:
        """
        Finalize paper window when it expires.

        If consecutive passes >= target: paper_ready=True
        Else: paper_ready=False and restart window

        Args:
            user_id: User ID
            state: Current state
            now: Current timestamp
            window_start: Window start
            window_end: Window end
            baseline: Baseline capital
            window_days: Window duration for restart
            checkpoint_target: Required passes for paper_ready
            target_return_pct: Target return percentage

        Returns:
            Window finalization result
        """
        current_streak = state.get("paper_consecutive_passes", 0)

        # Fetch final outcomes for the window
        outcomes = []
        try:
            res = self.supabase.table("learning_trade_outcomes_v3") \
                .select("closed_at, pnl_realized") \
                .eq("user_id", user_id) \
                .eq("is_paper", True) \
                .gte("closed_at", window_start.isoformat()) \
                .lte("closed_at", window_end.isoformat()) \
                .execute()
            outcomes = res.data or []
        except Exception as e:
            logger.error(f"Error fetching final outcomes: {e}")

        total_pnl = sum(float(o.get("pnl_realized") or 0.0) for o in outcomes)
        total_return_pct = (total_pnl / baseline) * 100 if baseline > 0 else 0.0

        # Determine if passed
        passed = current_streak >= checkpoint_target
        paper_ready = passed

        # Start new window
        new_window_start = now
        new_window_end = now + timedelta(days=window_days)

        # Update state
        updates = {
            "paper_ready": paper_ready,
            "paper_window_start": new_window_start.isoformat(),
            "paper_window_end": new_window_end.isoformat(),
            "paper_checkpoint_last_run_at": now.isoformat(),
            "updated_at": now.isoformat()
        }

        # Reset streak if not passed
        if not passed:
            updates["paper_consecutive_passes"] = 0

        self.supabase.table("v3_go_live_state").update(updates).eq("user_id", user_id).execute()

        # Log window finalization
        self._log_checkpoint_run(
            user_id, "paper_window_final", window_start, window_end,
            total_return_pct, total_pnl, passed,
            None if passed else "checkpoint_target_not_reached",
            {
                "streak_final": current_streak,
                "checkpoint_target": checkpoint_target,
                "outcome_count": len(outcomes),
                "new_window_start": new_window_start.isoformat(),
                "new_window_end": new_window_end.isoformat()
            }
        )

        return {
            "status": "window_final",
            "passed": passed,
            "paper_ready": paper_ready,
            "paper_consecutive_passes": current_streak if passed else 0,
            "checkpoint_target": checkpoint_target,
            "return_pct": total_return_pct,
            "pnl_total": total_pnl,
            "outcome_count": len(outcomes),
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "new_window_start": new_window_start.isoformat(),
            "new_window_end": new_window_end.isoformat()
        }

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

    # =========================================================================
    # v4-L1D: Shadow Checkpoint Evaluation (Side-Effect Free)
    # =========================================================================

    def _shadow_checkpoint_bucket(self, ts: datetime, cadence: str = "intraday") -> str:
        """
        Compute shadow checkpoint bucket key for deduplication.

        Args:
            ts: Timestamp to bucket
            cadence: Bucket cadence ("intraday" for hourly, "daily" for date)

        Returns:
            Bucket key string (e.g., "2024-01-15-14" for intraday hour 14)
        """
        if cadence == "intraday":
            return ts.strftime("%Y-%m-%d-%H")
        return ts.date().isoformat()

    def eval_paper_forward_checkpoint_shadow(
        self,
        user_id: str,
        now: Optional[datetime] = None,
        cadence: str = "intraday",
        cohort_name: Optional[str] = None,
        overrides: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        v4-L1D: Shadow checkpoint evaluation - computes metrics WITHOUT mutating state.

        This method computes the SAME metrics as eval_paper_forward_checkpoint but:
        - Does NOT update v3_go_live_state fields
        - Does NOT reset streaks or trigger fail-fast
        - DOES log the run with shadow=True tag
        - Returns would_pass / would_fail_fast for "what-if" analysis

        Args:
            user_id: User ID
            now: Override timestamp for testing
            cadence: Bucket cadence ("intraday" for hourly, "daily" for date)
            cohort_name: Optional cohort identifier for tracking
            overrides: Optional dict to override default thresholds:
                - paper_window_days: Override window duration
                - target_return_pct: Override target return (decimal, e.g., 0.10)
                - fail_fast_drawdown_pct: Override drawdown threshold (decimal, e.g., -0.03)
                - fail_fast_return_pct: Override return threshold (decimal, e.g., -0.02)

        Returns:
            Dict with shadow checkpoint results:
            - status: "ok" | "error"
            - return_pct: Total return in window
            - max_drawdown_pct: Max drawdown observed
            - progress: Window progress (0.0 to 1.0)
            - target_return_now: Current pacing target
            - would_pass: Boolean - would this pass official checkpoint?
            - would_fail_fast: Boolean - would this trigger fail-fast?
            - reason: Explanation string
            - shadow: True (always)
            - cohort: Cohort name if provided
        """
        if now is None:
            now = datetime.now(timezone.utc)

        # Ensure timezone awareness
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        overrides = overrides or {}

        # Extract override thresholds with defaults
        fail_fast_drawdown_pct = overrides.get("fail_fast_drawdown_pct", -0.03)
        fail_fast_return_pct = overrides.get("fail_fast_return_pct", -0.02)
        target_return_pct = overrides.get("target_return_pct", 0.10)
        override_window_days = overrides.get("paper_window_days")

        try:
            # 1. Load state (read-only)
            state = self.get_or_create_state(user_id)
            state = self._ensure_forward_checkpoint_defaults(state)

            baseline = float(state.get("paper_baseline_capital", 100000) or 100000)
            window_days = override_window_days or state.get("paper_window_days") or 21

            # 2. Repair window in memory only (no persist)
            window_start, window_end, _ = self._repair_window_if_needed(state, now)

            # If override window_days, recalculate window_end
            if override_window_days:
                window_end = window_start + timedelta(days=override_window_days)

            # 3. Calculate bucket key for logging
            bucket_key = self._shadow_checkpoint_bucket(now, cadence)

            # 4. Check if window has expired (for informational purposes)
            window_expired = now >= window_end

            # 5. Fetch outcomes for the window
            query_end = window_end if window_expired else now
            outcomes = []
            try:
                res = self.supabase.table("learning_trade_outcomes_v3") \
                    .select("closed_at, pnl_realized, profit_pct") \
                    .eq("user_id", user_id) \
                    .eq("is_paper", True) \
                    .gte("closed_at", window_start.isoformat()) \
                    .lte("closed_at", query_end.isoformat()) \
                    .order("closed_at", desc=False) \
                    .execute()
                outcomes = res.data or []
            except Exception as e:
                logger.error(f"Error fetching shadow outcomes: {e}")
                return {
                    "status": "error",
                    "error": str(e),
                    "shadow": True,
                    "cohort": cohort_name,
                    "cadence": cadence
                }

            # 6. Calculate metrics
            total_pnl = sum(float(o.get("pnl_realized") or 0.0) for o in outcomes)
            total_return_pct = (total_pnl / baseline) if baseline > 0 else 0.0
            max_drawdown_pct = self._compute_drawdown(outcomes, baseline)

            # 7. Calculate progress and pacing target
            elapsed = (query_end - window_start).total_seconds()
            duration = (window_end - window_start).total_seconds()
            progress = max(0.0, min(1.0, elapsed / duration)) if duration > 0 else 0.0
            target_return_now = target_return_pct * progress

            # 8. Determine would_pass / would_fail_fast
            would_fail_fast = False
            would_fail_fast_reason = None

            if max_drawdown_pct <= fail_fast_drawdown_pct:
                would_fail_fast = True
                would_fail_fast_reason = f"max_drawdown_exceeded_{max_drawdown_pct*100:.1f}pct"
            elif total_return_pct <= fail_fast_return_pct:
                would_fail_fast = True
                would_fail_fast_reason = f"total_return_below_{fail_fast_return_pct*100:.1f}pct"

            # would_pass: meets pacing target and no fail-fast
            would_pass = (total_return_pct >= target_return_now) and not would_fail_fast

            # Determine reason string
            if would_fail_fast:
                reason = would_fail_fast_reason
            elif not outcomes:
                reason = "no_outcomes_yet"
                would_pass = False  # No outcomes = miss
            elif would_pass:
                reason = "on_pace"
            else:
                reason = "below_pacing_target"

            # Build result
            result = {
                "status": "ok",
                "return_pct": total_return_pct * 100,
                "target_return_now": target_return_now * 100,
                "max_drawdown_pct": max_drawdown_pct * 100,
                "progress": progress,
                "would_pass": would_pass,
                "would_fail_fast": would_fail_fast,
                "reason": reason,
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
                "window_expired": window_expired,
                "bucket": bucket_key,
                "outcome_count": len(outcomes),
                "pnl_total": total_pnl,
                "shadow": True,
                "cohort": cohort_name,
                "cadence": cadence,
                # Include thresholds used for transparency
                "thresholds": {
                    "target_return_pct": target_return_pct * 100,
                    "fail_fast_drawdown_pct": fail_fast_drawdown_pct * 100,
                    "fail_fast_return_pct": fail_fast_return_pct * 100,
                    "paper_window_days": window_days
                },
                # Include current state for comparison (read-only)
                "current_streak": state.get("paper_consecutive_passes", 0),
                "paper_ready": state.get("paper_ready", False)
            }

            # 9. Log shadow run (fail-open: don't break if logging fails)
            try:
                self._log_checkpoint_run(
                    user_id=user_id,
                    mode="paper_checkpoint_shadow",
                    window_start=window_start,
                    window_end=query_end,
                    return_pct=total_return_pct * 100,
                    pnl_total=total_pnl,
                    passed=would_pass,
                    fail_reason=reason if not would_pass else None,
                    details={
                        "shadow": True,
                        "cohort": cohort_name,
                        "cadence": cadence,
                        "bucket": bucket_key,
                        "would_pass": would_pass,
                        "would_fail_fast": would_fail_fast,
                        "target_return_now": target_return_now * 100,
                        "progress": progress,
                        "thresholds": result["thresholds"]
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to log shadow checkpoint run: {e}")
                # Fail-open: return results anyway

            return result

        except Exception as e:
            logger.error(f"Shadow checkpoint failed for user {user_id}: {e}")
            return {
                "status": "error",
                "error": str(e),
                "shadow": True,
                "cohort": cohort_name,
                "cadence": cadence
            }

    # =========================================================================
    # v4-L1F: 10-Day Readiness Hardening Helpers
    # =========================================================================

    def ensure_forward_window_initialized(
        self,
        user_id: str,
        now: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        v4-L1F: Ensure forward checkpoint window fields are valid and initialized.

        This method is called daily before Day 1 of the test to prevent
        "repair window at checkpoint time" surprises. It ONLY updates
        window fields (start/end/days) and does NOT:
        - Increment or reset streak
        - Change readiness fields
        - Trigger fail-fast

        Args:
            user_id: User ID
            now: Override timestamp for testing

        Returns:
            Dict with:
            - status: "ok" | "repaired" | "error"
            - paper_window_start: Current window start
            - paper_window_end: Current window end
            - paper_window_days: Window duration
            - was_repaired: Boolean indicating if repair was needed
        """
        if now is None:
            now = datetime.now(timezone.utc)

        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        try:
            state = self.get_or_create_state(user_id)
            state = self._ensure_forward_checkpoint_defaults(state)

            window_days = state.get("paper_window_days") or 21
            window_start, window_end, was_repaired = self._repair_window_if_needed(state, now)

            if was_repaired:
                # Persist ONLY window fields - no streak or readiness changes
                self.supabase.table("v3_go_live_state").update({
                    "paper_window_start": window_start.isoformat(),
                    "paper_window_end": window_end.isoformat(),
                    "paper_window_days": window_days,
                    "updated_at": now.isoformat()
                }).eq("user_id", user_id).execute()
                logger.info(f"Repaired paper window for user {user_id}: {window_start} to {window_end}")

            return {
                "status": "repaired" if was_repaired else "ok",
                "paper_window_start": window_start.isoformat(),
                "paper_window_end": window_end.isoformat(),
                "paper_window_days": window_days,
                "was_repaired": was_repaired,
                "user_id": user_id
            }

        except Exception as e:
            logger.error(f"Failed to ensure window initialized for user {user_id}: {e}")
            return {
                "status": "error",
                "error": str(e),
                "user_id": user_id
            }

    def compute_forward_checkpoint_snapshot(
        self,
        user_id: str,
        now: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        v4-L1F: Compute preflight snapshot for readiness reporting.

        Returns metrics used for the daily preflight report WITHOUT
        mutating any state. This is similar to shadow eval but with
        additional fields needed for layman-friendly reporting.

        Args:
            user_id: User ID
            now: Override timestamp for testing

        Returns:
            Dict with:
            - return_pct: Total return in window (percentage)
            - target_return_now: Current pacing target (percentage)
            - margin_to_target: return_pct - target_return_now
            - max_drawdown_pct: Max drawdown observed (percentage)
            - fail_fast_drawdown_pct: Fail-fast threshold (percentage)
            - outcomes_today_count: Paper closed trades today
            - open_positions_count: Currently open paper positions
            - on_track: Boolean - currently meeting pacing target
            - at_risk_reason: Explanation if not on track
            - time_until_checkpoint: Seconds until 6:30 PM Chicago
            - progress: Window progress (0.0 to 1.0)
            - current_streak: Current consecutive passes
        """
        if now is None:
            now = datetime.now(timezone.utc)

        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        try:
            state = self.get_or_create_state(user_id)
            state = self._ensure_forward_checkpoint_defaults(state)

            # v4-L1E: Apply policy overrides if present
            policy_overrides = self._get_paper_forward_policy_overrides(state)

            baseline = float(state.get("paper_baseline_capital", 100000) or 100000)
            window_days = policy_overrides.get("paper_window_days") or state.get("paper_window_days") or 21
            fail_fast_drawdown_pct = policy_overrides.get("fail_fast_drawdown_pct", -0.03)
            fail_fast_return_pct = policy_overrides.get("fail_fast_return_pct", -0.02)
            target_return_pct = policy_overrides.get("target_return_pct", 0.10)

            # Get window bounds (in memory, no repair)
            window_start, window_end, _ = self._repair_window_if_needed(state, now)

            # Calculate today's UTC date range
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            today_end = today_start + timedelta(days=1)

            # Fetch outcomes for window
            outcomes = []
            try:
                res = self.supabase.table("learning_trade_outcomes_v3") \
                    .select("closed_at, pnl_realized") \
                    .eq("user_id", user_id) \
                    .eq("is_paper", True) \
                    .gte("closed_at", window_start.isoformat()) \
                    .lte("closed_at", now.isoformat()) \
                    .order("closed_at", desc=False) \
                    .execute()
                outcomes = res.data or []
            except Exception as e:
                logger.error(f"Error fetching outcomes for snapshot: {e}")

            # Count today's outcomes
            outcomes_today_count = 0
            for o in outcomes:
                try:
                    closed_at = datetime.fromisoformat(o["closed_at"])
                    if closed_at.tzinfo is None:
                        closed_at = closed_at.replace(tzinfo=timezone.utc)
                    if today_start <= closed_at < today_end:
                        outcomes_today_count += 1
                except (ValueError, TypeError):
                    pass

            # Fetch open paper positions count
            open_positions_count = 0
            try:
                # Get user's paper portfolios
                p_res = self.supabase.table("paper_portfolios").select("id").eq("user_id", user_id).execute()
                portfolio_ids = [p["id"] for p in (p_res.data or [])]

                if portfolio_ids:
                    pos_res = self.supabase.table("paper_positions") \
                        .select("id") \
                        .in_("portfolio_id", portfolio_ids) \
                        .execute()
                    open_positions_count = len(pos_res.data or [])
            except Exception as e:
                logger.warning(f"Error fetching open positions for snapshot: {e}")

            # Calculate metrics
            total_pnl = sum(float(o.get("pnl_realized") or 0.0) for o in outcomes)
            total_return_pct = (total_pnl / baseline) * 100 if baseline > 0 else 0.0
            max_drawdown_pct = self._compute_drawdown(outcomes, baseline) * 100

            # Calculate progress and pacing target
            elapsed = (now - window_start).total_seconds()
            duration = (window_end - window_start).total_seconds()
            progress = max(0.0, min(1.0, elapsed / duration)) if duration > 0 else 0.0
            target_return_now = target_return_pct * progress * 100  # Convert to percentage

            # Margin to target
            margin_to_target = total_return_pct - target_return_now

            # Determine on_track status
            on_track = True
            at_risk_reason = None

            if len(outcomes) == 0:
                on_track = False
                at_risk_reason = "no_outcomes_yet"
            elif max_drawdown_pct <= (fail_fast_drawdown_pct * 100):
                on_track = False
                at_risk_reason = f"drawdown_at_risk_{max_drawdown_pct:.1f}pct"
            elif total_return_pct <= (fail_fast_return_pct * 100):
                on_track = False
                at_risk_reason = f"return_at_risk_{total_return_pct:.1f}pct"
            elif total_return_pct < target_return_now:
                on_track = False
                at_risk_reason = f"below_pacing_{margin_to_target:.2f}pct"

            # Calculate time until 6:30 PM Chicago checkpoint
            try:
                from zoneinfo import ZoneInfo
                chicago_tz = ZoneInfo("America/Chicago")
                now_chicago = now.astimezone(chicago_tz)
                checkpoint_time = now_chicago.replace(hour=18, minute=30, second=0, microsecond=0)
                if now_chicago >= checkpoint_time:
                    # Checkpoint already passed today, calculate to tomorrow
                    checkpoint_time = checkpoint_time + timedelta(days=1)
                time_until_checkpoint = (checkpoint_time - now_chicago).total_seconds()
            except Exception:
                time_until_checkpoint = 0

            return {
                "status": "ok",
                "return_pct": round(total_return_pct, 4),
                "target_return_now": round(target_return_now, 4),
                "margin_to_target": round(margin_to_target, 4),
                "max_drawdown_pct": round(max_drawdown_pct, 4),
                "fail_fast_drawdown_pct": round(fail_fast_drawdown_pct * 100, 4),
                "outcomes_today_count": outcomes_today_count,
                "open_positions_count": open_positions_count,
                "on_track": on_track,
                "at_risk_reason": at_risk_reason,
                "time_until_checkpoint": int(time_until_checkpoint),
                "progress": round(progress, 4),
                "current_streak": state.get("paper_consecutive_passes", 0),
                "paper_ready": state.get("paper_ready", False),
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
                "user_id": user_id,
                "baseline_capital": baseline
            }

        except Exception as e:
            logger.error(f"Failed to compute snapshot for user {user_id}: {e}")
            return {
                "status": "error",
                "error": str(e),
                "user_id": user_id
            }
