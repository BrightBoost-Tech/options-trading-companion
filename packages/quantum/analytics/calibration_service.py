"""
Calibration Service — compares predicted vs realized outcomes.

Reads from the learning_trade_outcomes_v3 view (which joins
learning_feedback_loops → trade_suggestions) and computes
calibration metrics segmented by strategy, regime, DTE bucket,
and other dimensions.

Feature flag: CALIBRATION_ENABLED (default "0" — needs data to be useful)
Minimum sample: MIN_CALIBRATION_TRADES (default 20)
"""

import logging
import math
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from supabase import Client

logger = logging.getLogger(__name__)

CALIBRATION_ENABLED = os.environ.get("CALIBRATION_ENABLED", "1") == "1"
MIN_CALIBRATION_TRADES = int(os.environ.get("MIN_CALIBRATION_TRADES", "8"))

# DTE buckets for segmentation
DTE_BUCKETS = {
    "0-7": (0, 7),
    "7-14": (7, 14),
    "14-30": (14, 30),
    "30-60": (30, 60),
}


class CalibrationService:
    """Compare predicted EV/PoP against realized outcomes."""

    def __init__(self, supabase: Client):
        self.client = supabase

    def compute_calibration_report(
        self,
        user_id: str,
        window_days: int = 30,
    ) -> Dict[str, Any]:
        """
        Compare predicted vs realized across segments.

        Returns segmented calibration metrics including:
        - overall: aggregate EV and PoP calibration
        - by_strategy: per strategy type
        - by_regime: per market regime
        - by_window: per trading window (morning_limit, midday_entry)
        """
        outcomes = self._fetch_outcomes(user_id, window_days)

        if not outcomes:
            return {
                "status": "no_data",
                "sample_size": 0,
                "window_days": window_days,
            }

        return {
            "status": "ok",
            "window_days": window_days,
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "overall": self._compute_segment_metrics(outcomes),
            "by_strategy": self._group_and_compute(outcomes, "strategy"),
            "by_regime": self._group_and_compute(outcomes, "regime"),
            "by_window": self._group_and_compute(outcomes, "window"),
        }

    def compute_calibration_adjustments(
        self,
        user_id: str,
        window_days: int = 30,
    ) -> Dict[str, Any]:
        """
        Compute EV/PoP multipliers based on historical calibration error.

        Returns nested dict: {strategy: {regime: {dte_bucket: {ev_multiplier, pop_multiplier}}}}

        DTE-segmented calibration allows the system to learn that e.g.
        short-DTE debit spreads have different realized returns than
        long-DTE ones, even in the same regime.

        Falls back gracefully: callers that don't pass dte_bucket to
        apply_calibration() will get the "_all" bucket (aggregate).
        """
        outcomes = self._fetch_outcomes(user_id, window_days)

        if len(outcomes) < MIN_CALIBRATION_TRADES:
            return {
                "status": "insufficient_data",
                "sample_size": len(outcomes),
                "minimum_required": MIN_CALIBRATION_TRADES,
            }

        adjustments: Dict[str, Dict[str, Dict[str, Any]]] = {}

        # Group by (strategy, regime, dte_bucket)
        groups: Dict[str, List[Dict]] = {}
        for o in outcomes:
            strategy = o.get("strategy") or "unknown"
            regime = o.get("regime") or "unknown"
            dte_bucket = self._classify_dte(o)
            key = f"{strategy}|{regime}|{dte_bucket}"
            groups.setdefault(key, []).append(o)

            # Also accumulate into "_all" bucket for backward compatibility
            all_key = f"{strategy}|{regime}|_all"
            groups.setdefault(all_key, []).append(o)

        for key, group in groups.items():
            if len(group) < max(3, MIN_CALIBRATION_TRADES // 4):
                continue

            strategy, regime, dte_bucket = key.split("|", 2)
            metrics = self._compute_segment_metrics(group)

            ev_mult = self._compute_ev_multiplier(metrics)
            pop_mult = self._compute_pop_multiplier(metrics)

            # Only include non-trivial adjustments (>5% deviation)
            if abs(1.0 - ev_mult) > 0.05 or abs(1.0 - pop_mult) > 0.05:
                adjustments \
                    .setdefault(strategy, {}) \
                    .setdefault(regime, {})[dte_bucket] = {
                        "ev_multiplier": round(ev_mult, 4),
                        "pop_multiplier": round(pop_mult, 4),
                        "sample_size": metrics["sample_size"],
                        "ev_calibration_error": metrics["ev_calibration_error"],
                        "pop_calibration_error": metrics.get("pop_calibration_error"),
                    }

        return {
            "status": "ok",
            "adjustments": adjustments,
            "total_outcomes": len(outcomes),
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _classify_dte(outcome: Dict[str, Any]) -> str:
        """Classify an outcome into a DTE bucket based on entry DTE."""
        # Try details_json first, then top-level fields
        details = outcome.get("details_json") or {}
        dte = details.get("dte_at_entry") or outcome.get("dte_at_entry") or outcome.get("days_to_expiry")
        if dte is None:
            return "unknown"
        try:
            dte = int(float(dte))
        except (TypeError, ValueError):
            return "unknown"
        for label, (lo, hi) in DTE_BUCKETS.items():
            if lo <= dte < hi:
                return label
        return "60+" if dte >= 60 else "unknown"

    # ── Data fetching ───────────────────────────────────────────────

    def _fetch_outcomes(
        self, user_id: str, window_days: int
    ) -> List[Dict[str, Any]]:
        """Fetch predicted vs realized from learning_trade_outcomes_v3 view."""
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=window_days)
        ).isoformat()

        try:
            result = (
                self.client.table("learning_trade_outcomes_v3")
                .select(
                    "ev_predicted, pop_predicted, pnl_realized, pnl_predicted, "
                    "pnl_alpha, strategy, regime, window, ticker, closed_at, "
                    "model_version, is_paper"
                )
                .eq("user_id", user_id)
                .gte("closed_at", cutoff)
                .execute()
            )
            return result.data or []
        except Exception as e:
            logger.error(f"[CALIBRATION] Failed to fetch outcomes: {e}")
            return []

    # ── Metrics computation ─────────────────────────────────────────

    def _compute_segment_metrics(
        self, outcomes: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Compute calibration metrics for a group of outcomes."""
        n = len(outcomes)
        if n == 0:
            return {"sample_size": 0}

        # EV calibration
        ev_predicted = [float(o.get("ev_predicted") or 0) for o in outcomes]
        pnl_realized = [float(o.get("pnl_realized") or 0) for o in outcomes]

        ev_pred_avg = sum(ev_predicted) / n
        ev_real_avg = sum(pnl_realized) / n
        ev_cal_error = ev_pred_avg - ev_real_avg

        # EV RMSE
        ev_sq_errors = [
            (p - r) ** 2 for p, r in zip(ev_predicted, pnl_realized)
        ]
        ev_rmse = math.sqrt(sum(ev_sq_errors) / n)

        # PoP calibration (predicted probability vs actual win rate)
        pop_predicted_vals = [
            float(o.get("pop_predicted") or 0) for o in outcomes
            if o.get("pop_predicted") is not None
        ]
        wins = sum(1 for o in outcomes if float(o.get("pnl_realized") or 0) > 0)
        pop_realized_rate = wins / n

        pop_pred_avg = (
            sum(pop_predicted_vals) / len(pop_predicted_vals)
            if pop_predicted_vals
            else None
        )
        pop_cal_error = (
            (pop_pred_avg - pop_realized_rate)
            if pop_pred_avg is not None
            else None
        )

        # Win/loss stats
        total_pnl = sum(pnl_realized)
        avg_win = 0.0
        avg_loss = 0.0
        win_pnls = [r for r in pnl_realized if r > 0]
        loss_pnls = [r for r in pnl_realized if r < 0]
        if win_pnls:
            avg_win = sum(win_pnls) / len(win_pnls)
        if loss_pnls:
            avg_loss = sum(loss_pnls) / len(loss_pnls)

        return {
            "sample_size": n,
            "ev_predicted_avg": round(ev_pred_avg, 2),
            "ev_realized_avg": round(ev_real_avg, 2),
            "ev_calibration_error": round(ev_cal_error, 2),
            "ev_rmse": round(ev_rmse, 2),
            "pop_predicted_avg": round(pop_pred_avg, 4) if pop_pred_avg is not None else None,
            "pop_realized_rate": round(pop_realized_rate, 4),
            "pop_calibration_error": round(pop_cal_error, 4) if pop_cal_error is not None else None,
            "total_pnl": round(total_pnl, 2),
            "win_count": wins,
            "loss_count": n - wins,
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
        }

    def _group_and_compute(
        self, outcomes: List[Dict], key: str
    ) -> Dict[str, Dict[str, Any]]:
        """Group outcomes by a field and compute metrics per group."""
        groups: Dict[str, List[Dict]] = {}
        for o in outcomes:
            val = o.get(key) or "unknown"
            groups.setdefault(val, []).append(o)

        return {
            k: self._compute_segment_metrics(v)
            for k, v in groups.items()
            if len(v) >= 3  # minimum for meaningful stats
        }

    # ── Multiplier computation ──────────────────────────────────────

    @staticmethod
    def _compute_ev_multiplier(metrics: Dict[str, Any]) -> float:
        """
        If predicted EV is consistently higher than realized,
        return a multiplier < 1.0 to deflate future predictions.

        Clamped to [0.5, 1.5] to prevent extreme corrections.
        """
        pred = metrics.get("ev_predicted_avg", 0)
        if abs(pred) < 1.0:
            return 1.0  # Too small to calibrate

        realized = metrics.get("ev_realized_avg", 0)
        ratio = realized / pred
        return max(0.5, min(1.5, ratio))

    @staticmethod
    def _compute_pop_multiplier(metrics: Dict[str, Any]) -> float:
        """
        If predicted PoP is consistently higher than realized win rate,
        return a multiplier < 1.0 to deflate future PoP estimates.

        Clamped to [0.5, 1.5].
        """
        pred = metrics.get("pop_predicted_avg")
        if pred is None or pred < 0.05:
            return 1.0

        realized = metrics.get("pop_realized_rate", 0)
        ratio = realized / pred
        return max(0.5, min(1.5, ratio))


def get_calibration_adjustments(
    user_id: str, supabase: Client
) -> Dict[str, Dict[str, Dict[str, float]]]:
    """
    Convenience function: load cached adjustments from Supabase
    or compute fresh if none cached.

    Returns: {strategy: {regime: {ev_multiplier, pop_multiplier}}}
    """
    try:
        result = (
            supabase.table("calibration_adjustments")
            .select("adjustments")
            .eq("user_id", user_id)
            .order("computed_at", desc=True)
            .limit(1)
            .execute()
        )
        if result.data:
            return result.data[0].get("adjustments") or {}
    except Exception:
        pass  # Table may not exist yet — fall through to empty

    return {}


def apply_calibration(
    ev: float,
    pop: float,
    strategy: str,
    regime: str,
    adjustments: Dict[str, Dict[str, Dict[str, float]]],
    dte_bucket: Optional[str] = None,
) -> tuple:
    """
    Apply calibration multipliers to raw EV and PoP.

    Lookup order:
    1. (strategy, regime, dte_bucket) — most specific
    2. (strategy, regime, "_all") — aggregate for that strategy/regime
    3. 1.0 — no adjustment

    Returns (adjusted_ev, adjusted_pop).
    Logs adjustment when applied.
    """
    strat_adj = adjustments.get(strategy, {})
    regime_adj = strat_adj.get(regime, {})

    # New format: regime_adj is {dte_bucket: {ev_multiplier, pop_multiplier}}
    # Old format: regime_adj is {ev_multiplier, pop_multiplier} directly
    # Detect format by checking if ev_multiplier exists at top level (old format)
    if "ev_multiplier" in regime_adj:
        # Old format (backward compatibility with cached rows)
        bucket_adj = regime_adj
    else:
        # New format: try specific DTE bucket, fall back to _all
        bucket_adj = {}
        if dte_bucket:
            bucket_adj = regime_adj.get(dte_bucket, {})
        if not bucket_adj:
            bucket_adj = regime_adj.get("_all", {})

    ev_mult = bucket_adj.get("ev_multiplier", 1.0)
    pop_mult = bucket_adj.get("pop_multiplier", 1.0)

    adj_ev = ev * ev_mult
    adj_pop = pop * pop_mult

    if ev_mult != 1.0 or pop_mult != 1.0:
        bucket_label = dte_bucket or "_all"
        logger.info(
            f"[CALIBRATION] Adjusted {strategy}/{regime}/{bucket_label}: "
            f"EV {ev:.2f}→{adj_ev:.2f} (×{ev_mult:.3f}), "
            f"PoP {pop:.3f}→{adj_pop:.3f} (×{pop_mult:.3f})"
        )

    return adj_ev, adj_pop
