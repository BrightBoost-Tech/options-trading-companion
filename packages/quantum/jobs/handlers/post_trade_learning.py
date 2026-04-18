"""
Post-Trade Learning Agent

Runs after paper_learning_ingest completes (4:45 PM CT in EOD chain).
Closes the feedback loop by adjusting calibration weights based on
realized trade outcomes.

Responsibilities:
1. Compute alpha = realized_pnl - predicted_ev for closed trades
2. Update calibration multipliers with exponential decay
3. Detect prediction drift (rolling RMSE vs historical)
4. Flag underperforming strategies for review
5. Check promotion readiness (green days gate)
"""

import logging
import math
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from packages.quantum.jobs.handlers.utils import get_admin_client
from packages.quantum.jobs.handlers.exceptions import PermanentJobError

logger = logging.getLogger(__name__)

JOB_NAME = "post_trade_learning"

# Tuning parameters
DECAY_ALPHA = float(os.environ.get("LEARNING_DECAY_ALPHA", "0.3"))
MIN_TRADES_CALIBRATE = int(os.environ.get("LEARNING_MIN_TRADES_CALIBRATE", "10"))
MIN_TRADES_WEIGHT_ADJ = int(os.environ.get("LEARNING_MIN_TRADES_WEIGHT_ADJ", "20"))
MULTIPLIER_CLAMP_LO = 0.5
MULTIPLIER_CLAMP_HI = 1.5
WEIGHT_REDUCE_FACTOR = 0.9
DRIFT_THRESHOLD = float(os.environ.get("LEARNING_DRIFT_THRESHOLD", "2.0"))
MIN_SHARPE_THRESHOLD = float(os.environ.get("LEARNING_MIN_SHARPE", "0.3"))


def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """Main entry point — called by the job runner."""
    start_time = time.time()
    try:
        agent = PostTradeLearningAgent()
        result = agent.execute(payload)
        result["duration_ms"] = int((time.time() - start_time) * 1000)
        return result
    except Exception as e:
        logger.error(f"[LEARNING] Fatal error: {e}", exc_info=True)
        return {
            "ok": False,
            "error": str(e),
            "duration_ms": int((time.time() - start_time) * 1000),
        }


class PostTradeLearningAgent:

    def __init__(self):
        self.supabase = get_admin_client()

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        user_id = payload.get("user_id") or os.environ.get("USER_ID") or os.environ.get("TASK_USER_ID")
        if not user_id:
            return {"ok": True, "status": "no_user_id", "trades_processed": 0}

        trade_ids = payload.get("trade_ids")

        # 1. Get unprocessed trades
        trades = self._get_unprocessed_trades(user_id, trade_ids)
        if not trades:
            return {"ok": True, "status": "no_unprocessed_trades", "trades_processed": 0}

        logger.info(f"[LEARNING] Processing {len(trades)} unprocessed trades for user {user_id[:8]}")

        # 2. Process each trade
        segments_updated = set()
        strategies_checked = set()
        drift_alerts = 0

        for trade in trades:
            alpha = self._compute_alpha(trade)
            segment_key = self._build_segment_key(trade)

            if segment_key:
                self._update_segment_calibration(segment_key, trade, user_id)
                segments_updated.add(segment_key)

            strategy = trade.get("strategy")
            if strategy and strategy not in strategies_checked:
                self._check_strategy_health(strategy, user_id)
                strategies_checked.add(strategy)

            if segment_key:
                if self._detect_drift(segment_key, user_id):
                    drift_alerts += 1

        # 3. Mark trades as processed
        trade_ids_to_mark = [t.get("id") for t in trades if t.get("id")]
        if trade_ids_to_mark:
            self._mark_trades_processed(trade_ids_to_mark)

        # 4. Check promotion readiness
        promotion_result = self._check_promotion_readiness(user_id)

        result = {
            "ok": True,
            "status": "completed",
            "trades_processed": len(trades),
            "segments_updated": len(segments_updated),
            "strategies_checked": len(strategies_checked),
            "drift_alerts": drift_alerts,
            "promotion": promotion_result,
        }

        logger.info(f"[LEARNING] Complete: {result}")
        return result

    # ── Trade fetching ────────────────────────────────────────────────

    def _get_unprocessed_trades(self, user_id: str, trade_ids: list = None) -> List[Dict]:
        """Fetch closed trades not yet processed by the learning agent.

        Uses a two-query Python join on `suggestion_id` instead of the
        PostgREST embed `.select("*, trade_suggestions(*)")` that
        `dbc0564` shipped. `learning_feedback_loops` has a
        `suggestion_id` column but NO declared FK to `trade_suggestions`
        in the schema, so the embed raised "Could not find a
        relationship" on every call — the try/except swallowed it and
        the job silently processed 0 trades for 9+ days before Issue 3A
        diagnosis.

        The secondary suggestion lookup is treated as advisory: if it
        fails, trades still flow through with `trade_suggestions=None`.
        `_build_segment_key` already reads the suggestion as a fallback
        only when `trade.strategy`/`regime` are missing, so degraded
        lookups just reduce coverage, not correctness.
        """
        try:
            query = self.supabase.table("learning_feedback_loops") \
                .select("*") \
                .eq("user_id", user_id) \
                .in_("outcome_type", ["trade_closed", "individual_trade"]) \
                .eq("learning_processed", False)

            if trade_ids:
                query = query.in_("id", trade_ids)
            else:
                # Last 48h window
                cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
                query = query.gte("created_at", cutoff)

            res = query.order("created_at", desc=False).limit(100).execute()
            trades = res.data or []
        except Exception as e:
            logger.error(f"[LEARNING] Failed to fetch unprocessed trades: {e}")
            return []

        self._attach_trade_suggestions(trades)
        return trades

    def _attach_trade_suggestions(self, trades: List[Dict]) -> None:
        """Attach each trade's linked trade_suggestions row in-place.

        Mirrors what the old PostgREST embed produced so
        `_build_segment_key` can keep reading `trade["trade_suggestions"]`
        as a dict. Only trades with a non-null `suggestion_id` get a
        lookup; others receive `None`. If the bulk lookup raises, all
        trades get `None` — the caller tolerates missing suggestions.
        """
        suggestion_ids = sorted({
            t["suggestion_id"] for t in trades
            if t.get("suggestion_id")
        })
        suggestion_map: Dict[str, Dict[str, Any]] = {}
        if suggestion_ids:
            try:
                sugg_res = self.supabase.table("trade_suggestions") \
                    .select("*") \
                    .in_("id", suggestion_ids) \
                    .execute()
                for row in (sugg_res.data or []):
                    sid = row.get("id")
                    if sid:
                        suggestion_map[sid] = row
            except Exception as e:
                logger.warning(
                    f"[LEARNING] Suggestion lookup failed "
                    f"(n_ids={len(suggestion_ids)}): {e}. "
                    f"Proceeding with trades that have direct "
                    f"strategy/regime fields; others will skip segment update."
                )

        for t in trades:
            sid = t.get("suggestion_id")
            t["trade_suggestions"] = suggestion_map.get(sid) if sid else None

    # ── Alpha computation ─────────────────────────────────────────────

    def _compute_alpha(self, trade: Dict) -> float:
        """alpha = realized_pnl - predicted_ev"""
        realized = float(trade.get("pnl_realized") or 0)
        predicted = float(trade.get("pnl_predicted") or 0)
        return realized - predicted

    def _build_segment_key(self, trade: Dict) -> Optional[str]:
        """Build segment key from trade metadata."""
        strategy = trade.get("strategy")
        regime = trade.get("regime")

        if not strategy or not regime:
            # Try from linked suggestion
            suggestion = trade.get("trade_suggestions")
            if isinstance(suggestion, dict):
                strategy = strategy or suggestion.get("strategy")
                regime = regime or suggestion.get("regime")

        if not strategy or not regime:
            return None

        # Infer DTE bucket from details_json
        dte_bucket = "_all"
        details = trade.get("details_json") or {}
        if isinstance(details, dict):
            dte = details.get("dte_at_entry")
            if dte is not None:
                dte = int(dte)
                if dte <= 21:
                    dte_bucket = "0-21"
                elif dte <= 35:
                    dte_bucket = "21-35"
                elif dte <= 45:
                    dte_bucket = "35-45"
                else:
                    dte_bucket = "45+"

        return f"{strategy}|{regime}|{dte_bucket}"

    # ── Calibration update ────────────────────────────────────────────

    def _update_segment_calibration(self, segment_key: str, trade: Dict, user_id: str):
        """
        Exponential decay update for a (strategy, regime, dte_bucket) segment.
        Only updates if segment has >= MIN_TRADES_CALIBRATE trades.
        """
        parts = segment_key.split("|")
        if len(parts) != 3:
            return
        strategy, regime, dte_bucket = parts

        # Fetch segment stats from learning_trade_outcomes_v3
        try:
            res = self.supabase.rpc("", {}).execute()  # Can't call view via RPC
        except Exception:
            pass

        # Use direct query on learning_feedback_loops for segment stats
        try:
            res = self.supabase.table("learning_feedback_loops") \
                .select("pnl_realized, pnl_predicted") \
                .eq("user_id", user_id) \
                .eq("strategy", strategy) \
                .eq("regime", regime) \
                .in_("outcome_type", ["trade_closed", "individual_trade"]) \
                .execute()

            outcomes = res.data or []
            if len(outcomes) < MIN_TRADES_CALIBRATE:
                return

            # Compute realized vs predicted stats
            wins = sum(1 for o in outcomes if float(o.get("pnl_realized") or 0) > 0)
            total = len(outcomes)
            realized_wr = wins / total if total > 0 else 0.5

            predicted_pops = [float(o.get("pnl_predicted") or 0) for o in outcomes]
            avg_predicted = sum(predicted_pops) / len(predicted_pops) if predicted_pops else 0
            predicted_wr = sum(1 for p in predicted_pops if p > 0) / len(predicted_pops) if predicted_pops else 0.5

            # Fetch current multiplier from calibration_adjustments
            old_mult = self._get_current_multiplier(user_id, strategy, regime, dte_bucket)

            # Exponential decay update
            if predicted_wr > 0:
                ratio = realized_wr / predicted_wr
            else:
                ratio = 1.0
            new_mult = DECAY_ALPHA * ratio + (1 - DECAY_ALPHA) * old_mult
            new_mult = max(MULTIPLIER_CLAMP_LO, min(MULTIPLIER_CLAMP_HI, new_mult))

            if abs(new_mult - old_mult) < 0.01:
                return  # No meaningful change

            # Compute alpha stats
            alphas = [
                float(o.get("pnl_realized") or 0) - float(o.get("pnl_predicted") or 0)
                for o in outcomes
            ]
            alpha_mean = sum(alphas) / len(alphas) if alphas else 0

            # Write to signal_weight_history
            self.supabase.table("signal_weight_history").insert({
                "user_id": user_id,
                "segment_key": segment_key,
                "strategy": strategy,
                "regime": regime,
                "dte_bucket": dte_bucket,
                "old_multiplier": round(old_mult, 4),
                "new_multiplier": round(new_mult, 4),
                "trade_count": total,
                "realized_win_rate": round(realized_wr, 4),
                "predicted_win_rate": round(predicted_wr, 4),
                "alpha_mean": round(alpha_mean, 2),
                "trigger": "calibration_update",
            }).execute()

            logger.info(
                f"[LEARNING] Segment {segment_key}: mult {old_mult:.3f} → {new_mult:.3f} "
                f"(wr: {realized_wr:.0%} vs {predicted_wr:.0%}, n={total})"
            )

        except Exception as e:
            logger.error(f"[LEARNING] Segment calibration failed for {segment_key}: {e}")

    def _get_current_multiplier(self, user_id: str, strategy: str,
                                 regime: str, dte_bucket: str) -> float:
        """Look up current EV multiplier from calibration_adjustments."""
        try:
            res = self.supabase.table("calibration_adjustments") \
                .select("adjustments") \
                .eq("user_id", user_id) \
                .order("computed_at", desc=True) \
                .limit(1) \
                .execute()
            if not res.data:
                return 1.0
            adj = res.data[0].get("adjustments") or {}
            # Navigate nested structure: strategy → regime → dte_bucket → ev_multiplier
            strat_adj = adj.get(strategy, {})
            if isinstance(strat_adj, dict):
                regime_adj = strat_adj.get(regime, {})
                if isinstance(regime_adj, dict):
                    bucket_adj = regime_adj.get(dte_bucket, regime_adj.get("_all", {}))
                    if isinstance(bucket_adj, dict):
                        return float(bucket_adj.get("ev_multiplier", 1.0))
            return 1.0
        except Exception:
            return 1.0

    # ── Strategy health ───────────────────────────────────────────────

    def _check_strategy_health(self, strategy: str, user_id: str):
        """Check if a strategy is underperforming and flag/reduce weight."""
        try:
            res = self.supabase.table("learning_feedback_loops") \
                .select("pnl_realized, pnl_predicted") \
                .eq("user_id", user_id) \
                .eq("strategy", strategy) \
                .in_("outcome_type", ["trade_closed", "individual_trade"]) \
                .order("created_at", desc=True) \
                .limit(30) \
                .execute()

            outcomes = res.data or []
            if len(outcomes) < MIN_TRADES_WEIGHT_ADJ:
                return

            # Compute alpha and Sharpe
            alphas = [
                float(o.get("pnl_realized") or 0) - float(o.get("pnl_predicted") or 0)
                for o in outcomes
            ]
            alpha_mean = sum(alphas) / len(alphas)
            alpha_std = math.sqrt(
                sum((a - alpha_mean) ** 2 for a in alphas) / len(alphas)
            ) if len(alphas) > 1 else 1.0

            sharpe = alpha_mean / alpha_std if alpha_std > 0 else 0

            # Flag if Sharpe too low
            if sharpe < MIN_SHARPE_THRESHOLD:
                self.supabase.table("strategy_adjustments").insert({
                    "user_id": user_id,
                    "strategy": strategy,
                    "action": "flag_review",
                    "reason": f"Sharpe {sharpe:.2f} < {MIN_SHARPE_THRESHOLD} over {len(outcomes)} trades",
                    "supporting_data": {
                        "sharpe": round(sharpe, 3),
                        "alpha_mean": round(alpha_mean, 2),
                        "trade_count": len(outcomes),
                    },
                }).execute()

                logger.warning(
                    f"[LEARNING] Strategy {strategy} flagged: Sharpe={sharpe:.2f} "
                    f"alpha_mean=${alpha_mean:.0f} n={len(outcomes)}"
                )

            # Reduce weight if negative alpha with enough data
            if alpha_mean < 0 and len(outcomes) >= MIN_TRADES_WEIGHT_ADJ:
                self.supabase.table("strategy_adjustments").insert({
                    "user_id": user_id,
                    "strategy": strategy,
                    "action": "weight_reduce",
                    "old_weight": 1.0,
                    "new_weight": WEIGHT_REDUCE_FACTOR,
                    "reason": f"Negative alpha ${alpha_mean:.0f} over {len(outcomes)} trades",
                    "supporting_data": {
                        "alpha_mean": round(alpha_mean, 2),
                        "sharpe": round(sharpe, 3),
                        "trade_count": len(outcomes),
                    },
                }).execute()

                logger.info(
                    f"[LEARNING] Strategy {strategy} weight reduced to "
                    f"{WEIGHT_REDUCE_FACTOR} (alpha_mean=${alpha_mean:.0f})"
                )

        except Exception as e:
            logger.error(f"[LEARNING] Strategy health check failed for {strategy}: {e}")

    # ── Drift detection ───────────────────────────────────────────────

    def _detect_drift(self, segment_key: str, user_id: str) -> bool:
        """
        Detect prediction drift by comparing rolling RMSE to historical.
        Returns True if drift alert was fired.
        """
        parts = segment_key.split("|")
        if len(parts) != 3:
            return False
        strategy, regime, _ = parts

        try:
            res = self.supabase.table("learning_feedback_loops") \
                .select("pnl_realized, pnl_predicted") \
                .eq("user_id", user_id) \
                .eq("strategy", strategy) \
                .eq("regime", regime) \
                .in_("outcome_type", ["trade_closed", "individual_trade"]) \
                .order("created_at", desc=True) \
                .limit(30) \
                .execute()

            outcomes = res.data or []
            if len(outcomes) < 15:
                return False

            # Compute errors
            errors = [
                (float(o.get("pnl_realized") or 0) - float(o.get("pnl_predicted") or 0)) ** 2
                for o in outcomes
            ]

            # Rolling RMSE (last 10)
            rolling_mse = sum(errors[:10]) / 10
            rolling_rmse = math.sqrt(rolling_mse)

            # Historical RMSE (all)
            historical_mse = sum(errors) / len(errors)
            historical_rmse = math.sqrt(historical_mse)

            if historical_rmse > 0 and rolling_rmse > DRIFT_THRESHOLD * historical_rmse:
                self.supabase.table("risk_alerts").insert({
                    "user_id": user_id,
                    "alert_type": "drift",
                    "severity": "high",
                    "message": (
                        f"Prediction drift in {segment_key}: "
                        f"rolling RMSE ${rolling_rmse:.0f} > "
                        f"{DRIFT_THRESHOLD}x historical ${historical_rmse:.0f}"
                    ),
                    "metadata": {
                        "segment_key": segment_key,
                        "rolling_rmse": round(rolling_rmse, 2),
                        "historical_rmse": round(historical_rmse, 2),
                        "threshold": DRIFT_THRESHOLD,
                    },
                }).execute()

                logger.warning(
                    f"[LEARNING] DRIFT ALERT: {segment_key} "
                    f"rolling_rmse=${rolling_rmse:.0f} vs historical=${historical_rmse:.0f}"
                )
                return True

        except Exception as e:
            logger.error(f"[LEARNING] Drift detection failed for {segment_key}: {e}")
        return False

    # ── Promotion check ───────────────────────────────────────────────

    def _check_promotion_readiness(self, user_id: str) -> Dict[str, Any]:
        """Check if user is ready for promotion using existing progression service."""
        try:
            from packages.quantum.services.progression_service import ProgressionService
            svc = ProgressionService(self.supabase)
            state = svc.get_state(user_id)

            phase = state.get("current_phase", "alpaca_paper")
            green_days = state.get("alpaca_paper_green_days", 0)
            required = state.get("alpaca_paper_green_days_required", 4)

            if phase == "alpaca_paper" and green_days >= required:
                logger.info(
                    f"[LEARNING] User {user_id[:8]} promotion-ready: "
                    f"{green_days}/{required} green days"
                )
                return {
                    "ready": True,
                    "phase": phase,
                    "green_days": green_days,
                    "note": "Promotion ready — awaiting manual approval or auto-promote",
                }

            return {"ready": False, "phase": phase, "green_days": green_days}
        except Exception as e:
            logger.error(f"[LEARNING] Promotion check failed: {e}")
            return {"ready": False, "error": str(e)}

    # ── Mark processed ────────────────────────────────────────────────

    def _mark_trades_processed(self, trade_ids: List[str]):
        """Mark learning_feedback_loops rows as processed."""
        try:
            for batch_start in range(0, len(trade_ids), 50):
                batch = trade_ids[batch_start:batch_start + 50]
                self.supabase.table("learning_feedback_loops") \
                    .update({"learning_processed": True}) \
                    .in_("id", batch) \
                    .execute()
        except Exception as e:
            logger.error(f"[LEARNING] Failed to mark trades processed: {e}")
