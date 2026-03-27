"""
Walk-Forward Autotune

Replaces threshold mutation with out-of-sample validated parameter tuning.

1. Split trade history into TRAIN (older 70%) and VALIDATE (newer 30%)
2. On TRAIN: find optimal parameter values
3. On VALIDATE: measure out-of-sample performance
4. Only PROMOTE if validation performance improves with confidence

Feature flags:
  AUTOTUNE_ENABLED       (default "0")
  AUTOTUNE_AUTOPROMOTE   (default "0")
  AUTOTUNE_MIN_TRADES    (default "30")
"""

import logging
import math
import os
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

AUTOTUNE_ENABLED = os.environ.get("AUTOTUNE_ENABLED", "0") == "1"
AUTOTUNE_AUTOPROMOTE = os.environ.get("AUTOTUNE_AUTOPROMOTE", "0") == "1"
AUTOTUNE_MIN_TRADES = int(os.environ.get("AUTOTUNE_MIN_TRADES", "30"))

# Promotion thresholds
MIN_IMPROVEMENT_PCT = 10.0      # Candidate must beat current by 10%+
MIN_CONFIDENCE = 0.70           # Bootstrap confidence threshold
MAX_DRAWDOWN_INCREASE = 0.20    # Drawdown can't increase by > 20%
MIN_VALIDATE_TRADES = 15        # Minimum trades in validation set
MIN_WIN_RATE = 0.40             # Win rate floor for promotion


@dataclass
class ParameterCandidate:
    """A candidate parameter value to evaluate."""
    name: str
    current_value: float
    candidate_value: float
    min_value: float
    max_value: float
    step: float


# Tunable parameter space
PARAMETER_SPACE = [
    ParameterCandidate("min_score_threshold", 60.0, 0, 20.0, 90.0, 5.0),
    ParameterCandidate("risk_multiplier", 1.0, 0, 0.5, 2.0, 0.1),
    ParameterCandidate("target_profit_pct", 0.50, 0, 0.20, 0.80, 0.05),
    ParameterCandidate("stop_loss_pct", 2.0, 0, 0.5, 3.0, 0.25),
    ParameterCandidate("min_dte_to_exit", 7, 0, 3, 14, 1),
    ParameterCandidate("max_positions_open", 10, 0, 3, 15, 1),
    ParameterCandidate("budget_cap_pct", 0.35, 0, 0.15, 0.50, 0.05),
]


class WalkForwardAutotune:
    """Walk-forward parameter optimization with promotion/demotion rules."""

    def __init__(
        self,
        supabase,
        min_trades: int = AUTOTUNE_MIN_TRADES,
        train_pct: float = 0.70,
    ):
        self.client = supabase
        self.min_trades = min_trades
        self.train_pct = train_pct

    def run_autotune_cycle(
        self,
        user_id: str,
        lookback_days: int = 60,
        cohort_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Run a full walk-forward autotune cycle.

        1. Load closed trades
        2. Split into train/validate
        3. For each tunable parameter, evaluate candidates
        4. Apply promotion/demotion rules
        5. Return proposed changes with metrics
        """
        trades = self._load_trades(user_id, lookback_days)

        if len(trades) < self.min_trades:
            return {
                "status": "insufficient_data",
                "trade_count": len(trades),
                "minimum_required": self.min_trades,
            }

        # Sort by close time ascending for temporal split
        trades.sort(key=lambda t: t.get("closed_at") or "")

        split_idx = int(len(trades) * self.train_pct)
        train_set = trades[:split_idx]
        validate_set = trades[split_idx:]

        if len(validate_set) < MIN_VALIDATE_TRADES:
            return {
                "status": "insufficient_validation_data",
                "train_size": len(train_set),
                "validate_size": len(validate_set),
                "minimum_validate": MIN_VALIDATE_TRADES,
            }

        # Load current config
        current_config = self._load_current_config(user_id, cohort_name)

        # Evaluate each parameter
        evaluations = []
        for param_def in PARAMETER_SPACE:
            param = ParameterCandidate(
                name=param_def.name,
                current_value=current_config.get(param_def.name, param_def.current_value),
                candidate_value=0,  # Will be computed
                min_value=param_def.min_value,
                max_value=param_def.max_value,
                step=param_def.step,
            )

            result = self._evaluate_parameter(param, train_set, validate_set)
            evaluations.append(result)

        # Apply promotion rules
        promoted = []
        demoted = []
        rejected = []

        for ev in evaluations:
            action = self._apply_promotion_rules(ev)
            ev["action"] = action

            if action == "promoted":
                promoted.append(ev)
            elif action == "demoted":
                demoted.append(ev)
            else:
                rejected.append(ev)

            # Log and record
            self._record_autotune_history(user_id, ev)

        # Apply promoted changes if autopromote is on
        if AUTOTUNE_AUTOPROMOTE and promoted:
            self._apply_changes(user_id, cohort_name, promoted)

        return {
            "status": "ok",
            "total_trades": len(trades),
            "train_size": len(train_set),
            "validate_size": len(validate_set),
            "evaluations": len(evaluations),
            "promoted": [p["parameter"] for p in promoted],
            "demoted": [d["parameter"] for d in demoted],
            "rejected": [r["parameter"] for r in rejected],
            "autopromote": AUTOTUNE_AUTOPROMOTE,
            "details": evaluations,
        }

    # ── Parameter evaluation ────────────────────────────────────────

    def _evaluate_parameter(
        self,
        param: ParameterCandidate,
        train_set: List[Dict],
        validate_set: List[Dict],
    ) -> Dict[str, Any]:
        """
        Find optimal value on train set, measure on validate set.

        Generates candidates by stepping through the range and picks
        the one with best train-set performance. Then measures both
        current and candidate on the validate set.
        """
        # Generate candidate values
        candidates = []
        v = param.min_value
        while v <= param.max_value + 1e-9:
            candidates.append(round(v, 4))
            v += param.step

        # Find best on train set
        best_train_pnl = float("-inf")
        best_value = param.current_value

        for candidate_val in candidates:
            filtered = self._filter_trades_by_param(
                train_set, param.name, candidate_val
            )
            if len(filtered) < 3:
                continue
            pnl = sum(float(t.get("pnl_realized") or 0) for t in filtered)
            if pnl > best_train_pnl:
                best_train_pnl = pnl
                best_value = candidate_val

        # Measure current and candidate on validate set
        current_filtered = self._filter_trades_by_param(
            validate_set, param.name, param.current_value
        )
        candidate_filtered = self._filter_trades_by_param(
            validate_set, param.name, best_value
        )

        current_metrics = self._compute_metrics(current_filtered)
        candidate_metrics = self._compute_metrics(candidate_filtered)

        # Bootstrap confidence
        confidence = self._bootstrap_confidence(
            candidate_filtered, current_filtered
        )

        improvement = 0.0
        if current_metrics["total_pnl"] != 0:
            improvement = (
                (candidate_metrics["total_pnl"] - current_metrics["total_pnl"])
                / abs(current_metrics["total_pnl"])
                * 100
            )
        elif candidate_metrics["total_pnl"] > 0:
            improvement = 100.0

        return {
            "parameter": param.name,
            "current_value": param.current_value,
            "candidate_value": best_value,
            "current_validate_pnl": current_metrics["total_pnl"],
            "candidate_validate_pnl": candidate_metrics["total_pnl"],
            "current_win_rate": current_metrics["win_rate"],
            "candidate_win_rate": candidate_metrics["win_rate"],
            "current_max_drawdown": current_metrics["max_drawdown"],
            "candidate_max_drawdown": candidate_metrics["max_drawdown"],
            "improvement_pct": round(improvement, 2),
            "confidence": round(confidence, 4),
            "train_trades": len(train_set),
            "validate_trades": len(validate_set),
            "current_validate_trades": len(current_filtered),
            "candidate_validate_trades": len(candidate_filtered),
        }

    def _filter_trades_by_param(
        self,
        trades: List[Dict],
        param_name: str,
        param_value: float,
    ) -> List[Dict]:
        """
        Simulate which trades would have been taken with a given param value.

        For threshold parameters (min_score_threshold), filters trades
        whose EV/score was above the threshold. For position limits, etc.,
        applies the constraint retroactively.
        """
        if param_name == "min_score_threshold":
            return [
                t for t in trades
                if float(t.get("ev_predicted") or t.get("pnl_predicted") or 0) >= param_value
            ]
        if param_name == "target_profit_pct":
            # Can't retroactively filter — all trades pass, but the param
            # affects P&L through earlier/later exits (approximated by the
            # existing realized P&L for now).
            return trades
        if param_name == "stop_loss_pct":
            return trades
        if param_name == "min_dte_to_exit":
            return trades
        if param_name == "max_positions_open":
            # Take only the first N trades per day (approximation)
            return trades[:int(param_value * len(trades) / 10)] or trades
        if param_name == "budget_cap_pct":
            return trades
        if param_name == "risk_multiplier":
            return trades
        return trades

    # ── Metrics computation ─────────────────────────────────────────

    @staticmethod
    def _compute_metrics(trades: List[Dict]) -> Dict[str, Any]:
        """Compute P&L metrics for a set of trades."""
        if not trades:
            return {
                "total_pnl": 0, "win_rate": 0, "max_drawdown": 0,
                "avg_pnl": 0, "trade_count": 0,
            }

        pnls = [float(t.get("pnl_realized") or 0) for t in trades]
        wins = sum(1 for p in pnls if p > 0)
        total = len(pnls)

        # Max drawdown: peak-to-trough of cumulative P&L
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for p in pnls:
            cumulative += p
            peak = max(peak, cumulative)
            dd = peak - cumulative
            max_dd = max(max_dd, dd)

        return {
            "total_pnl": round(sum(pnls), 2),
            "avg_pnl": round(sum(pnls) / total, 2),
            "win_rate": round(wins / total, 4) if total > 0 else 0,
            "max_drawdown": round(max_dd, 2),
            "trade_count": total,
        }

    @staticmethod
    def _bootstrap_confidence(
        candidate_trades: List[Dict],
        current_trades: List[Dict],
        n_bootstrap: int = 500,
    ) -> float:
        """
        Bootstrap test: what fraction of resampled validate sets
        show the candidate outperforming current?
        """
        if not candidate_trades or not current_trades:
            return 0.0

        cand_pnls = [float(t.get("pnl_realized") or 0) for t in candidate_trades]
        curr_pnls = [float(t.get("pnl_realized") or 0) for t in current_trades]

        cand_wins = 0
        for _ in range(n_bootstrap):
            cand_sample = random.choices(cand_pnls, k=len(cand_pnls))
            curr_sample = random.choices(curr_pnls, k=len(curr_pnls))
            if sum(cand_sample) > sum(curr_sample):
                cand_wins += 1

        return cand_wins / n_bootstrap

    # ── Promotion/demotion rules ────────────────────────────────────

    @staticmethod
    def _apply_promotion_rules(evaluation: Dict[str, Any]) -> str:
        """
        Decide promote/demote/reject based on validation metrics.

        Promote if ALL:
          - improvement > 10%
          - confidence > 70%
          - no drawdown increase > 20%
          - validate trades >= 15
          - candidate win rate >= 40%

        Demote if ANY:
          - validation PnL decreased > 5%
          - drawdown increased > 20%
          - win rate < 40%
        """
        improvement = evaluation.get("improvement_pct", 0)
        confidence = evaluation.get("confidence", 0)
        curr_dd = evaluation.get("current_max_drawdown", 0)
        cand_dd = evaluation.get("candidate_max_drawdown", 0)
        cand_wr = evaluation.get("candidate_win_rate", 0)
        validate_n = evaluation.get("candidate_validate_trades", 0)

        # Check demotion first
        if improvement < -5.0:
            return "demoted"
        if curr_dd > 0 and cand_dd > curr_dd * (1 + MAX_DRAWDOWN_INCREASE):
            return "demoted"
        if cand_wr < MIN_WIN_RATE and validate_n >= MIN_VALIDATE_TRADES:
            return "demoted"

        # Check promotion
        if (
            improvement >= MIN_IMPROVEMENT_PCT
            and confidence >= MIN_CONFIDENCE
            and validate_n >= MIN_VALIDATE_TRADES
            and cand_wr >= MIN_WIN_RATE
        ):
            # Drawdown guard
            if curr_dd > 0 and cand_dd > curr_dd * (1 + MAX_DRAWDOWN_INCREASE):
                return "rejected"
            return "promoted"

        return "rejected"

    # ── Data loading ────────────────────────────────────────────────

    def _load_trades(
        self, user_id: str, lookback_days: int
    ) -> List[Dict[str, Any]]:
        """Load closed trades with predicted and realized values."""
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=lookback_days)
        ).isoformat()

        try:
            result = (
                self.client.table("learning_trade_outcomes_v3")
                .select(
                    "closed_at, ev_predicted, pop_predicted, pnl_realized, "
                    "pnl_predicted, pnl_alpha, strategy, regime, window, "
                    "ticker, model_version, is_paper"
                )
                .eq("user_id", user_id)
                .gte("closed_at", cutoff)
                .execute()
            )
            return result.data or []
        except Exception as e:
            logger.error(f"[AUTOTUNE] Failed to load trades: {e}")
            return []

    def _load_current_config(
        self, user_id: str, cohort_name: Optional[str]
    ) -> Dict[str, Any]:
        """Load current policy config for the user/cohort."""
        try:
            from packages.quantum.policy_lab.config import (
                load_cohort_configs,
                get_policy_config,
            )
            if cohort_name:
                configs = load_cohort_configs(user_id, self.client)
                cfg = configs.get(cohort_name)
                if cfg:
                    return cfg.to_dict()
            return get_policy_config("neutral").to_dict()
        except Exception:
            return {}

    # ── Persistence ─────────────────────────────────────────────────

    def _record_autotune_history(
        self, user_id: str, evaluation: Dict[str, Any]
    ) -> None:
        """Record autotune decision in history table."""
        try:
            self.client.table("autotune_history").insert({
                "user_id": user_id,
                "parameter_name": evaluation["parameter"],
                "old_value": evaluation["current_value"],
                "new_value": evaluation["candidate_value"],
                "improvement_pct": evaluation["improvement_pct"],
                "confidence": evaluation["confidence"],
                "action": evaluation.get("action", "rejected"),
                "train_trades": evaluation["train_trades"],
                "validate_trades": evaluation["validate_trades"],
                "metrics_snapshot": {
                    "current_pnl": evaluation["current_validate_pnl"],
                    "candidate_pnl": evaluation["candidate_validate_pnl"],
                    "current_win_rate": evaluation["current_win_rate"],
                    "candidate_win_rate": evaluation["candidate_win_rate"],
                    "current_max_drawdown": evaluation["current_max_drawdown"],
                    "candidate_max_drawdown": evaluation["candidate_max_drawdown"],
                },
            }).execute()
        except Exception as e:
            logger.warning(f"[AUTOTUNE] Failed to record history: {e}")

    def _apply_changes(
        self,
        user_id: str,
        cohort_name: Optional[str],
        promoted: List[Dict[str, Any]],
    ) -> None:
        """Apply promoted parameter changes to policy config."""
        try:
            from packages.quantum.policy_lab.config import (
                load_cohort_configs,
                get_policy_config,
                PolicyConfig,
            )

            if cohort_name:
                configs = load_cohort_configs(user_id, self.client)
                cfg = configs.get(cohort_name)
                if not cfg:
                    cfg = get_policy_config("neutral")
            else:
                cfg = get_policy_config("neutral")

            cfg_dict = cfg.to_dict()
            for p in promoted:
                param_name = p["parameter"]
                if param_name in cfg_dict:
                    old = cfg_dict[param_name]
                    cfg_dict[param_name] = p["candidate_value"]
                    logger.info(
                        f"[AUTOTUNE] PROMOTED {param_name}: "
                        f"{old} → {p['candidate_value']} "
                        f"(improvement={p['improvement_pct']:.1f}%, "
                        f"confidence={p['confidence']:.2f})"
                    )

            # Persist via policy_lab_cohorts update
            if cohort_name:
                self.client.table("policy_lab_cohorts").update({
                    "policy_config": cfg_dict,
                }).eq("user_id", user_id).eq("cohort_name", cohort_name).execute()
            else:
                # Update default strategy config
                from packages.quantum.jobs.handlers.strategy_autotune import (
                    _persist_strategy_config,
                )
                _persist_strategy_config(
                    self.client, user_id,
                    "spy_opt_autolearn_v6",
                    cfg_dict.get("version", 1) + 1,
                    cfg_dict,
                    f"Walk-forward autotune: promoted {len(promoted)} params",
                )
        except Exception as e:
            logger.error(f"[AUTOTUNE] Failed to apply changes: {e}")
