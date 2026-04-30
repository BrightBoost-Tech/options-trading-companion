"""
Paper Exit Evaluator

Replaces the blanket EOD force-close with condition-based exits.
Checks open positions against exit conditions and closes only those that trigger.

Exit conditions (checked in order — first match triggers close):
1. target_profit: Captured >= 50% of max credit (credit spreads)
   or unrealized P&L >= 50% of entry cost (debit spreads)
2. stop_loss: Loss exceeds 2x credit (credit) or 50% of entry cost (debit)
3. dte_threshold: 7 DTE or less (gamma risk)
4. expiration_day: Expires today — must close

Schedule: 3:00 PM CDT (before mark-to-market at 3:30 PM).
"""

import logging
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Dict, Any, List, Tuple, Optional, Callable

from packages.quantum.services.close_math import (
    compute_realized_pl,
    PartialFillDetected,
)
from packages.quantum.services.close_helper import (
    close_position_shared,
    PositionAlreadyClosed,
)
from packages.quantum.observability.alerts import alert, _get_admin_supabase

PDT_MAX_DAY_TRADES = int(os.environ.get("PDT_MAX_DAY_TRADES", "3"))
EXIT_RANKING_ENABLED = os.environ.get("EXIT_RANKING_ENABLED", "1") == "1"

logger = logging.getLogger(__name__)


# Mapping from exit-evaluator reason strings (emitted by EXIT_CONDITIONS
# and by intraday_risk_monitor) to the 9-value close_reason enum that
# close_position_shared accepts. The exit-evaluator side still emits
# legacy-style reasons ('target_profit', 'stop_loss') because that's
# the API the conditions dict and the intraday caller use; the mapping
# translates them at the close-write boundary so only the 9 canonical
# values reach the DB. Phase 2 of the enum migration drops the legacy
# values entirely; this mapping is the last place they exist post-PR-#6.
_REASON_MAP = {
    "target_profit": "target_profit_hit",
    "target_profit_hit": "target_profit_hit",
    "stop_loss": "stop_loss_hit",
    "stop_loss_hit": "stop_loss_hit",
    "dte_threshold": "dte_threshold",
    "expiration_day": "expiration_day",
}


def _map_close_reason(raw_reason: str) -> Optional[str]:
    """Translate an exit-evaluator reason string to a canonical
    close_reason enum value. Returns None on unknown reasons — caller
    writes a severity='critical' risk_alert and skips the close rather
    than guessing. The `risk_envelope:*` prefix (from intraday monitor)
    maps to 'envelope_force_close'."""
    if raw_reason is None:
        return None
    s = str(raw_reason).strip()
    if not s:
        return None
    if s.startswith("risk_envelope:"):
        return "envelope_force_close"
    return _REASON_MAP.get(s)


def _write_exit_eval_critical_alert(
    supabase,
    position: Dict[str, Any],
    user_id: str,
    stage: str,
    reason: str,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Write a severity='critical' risk_alert when the exit-evaluator
    close pipeline aborts (partial-fill anomaly, unknown reason,
    PositionAlreadyClosed race).

    Swallows its own exceptions — an alert-write failure must not
    cascade to a handler crash."""
    try:
        metadata = {
            "detector": "paper_exit_evaluator",
            "stage": stage,
            "reason": reason,
        }
        if extra_metadata:
            metadata.update(extra_metadata)
        supabase.table("risk_alerts").insert({
            "user_id": user_id or position.get("user_id"),
            "alert_type": "close_path_anomaly",
            "severity": "critical",
            "position_id": position.get("id"),
            "symbol": position.get("symbol"),
            "message": (
                f"Exit-evaluator close aborted at {stage}: {reason[:200]}"
            ),
            "metadata": metadata,
        }).execute()
    except Exception as alert_err:
        logger.error(
            f"[EXIT_EVAL] Failed to write critical risk_alert for "
            f"position {(position.get('id') or '?')[:8]}: {alert_err}. "
            f"Original anomaly at {stage}: {reason[:200]}"
        )


def days_to_expiry(position: Dict[str, Any]) -> int:
    """
    Compute days to expiration from position's nearest_expiry or legs.

    Returns large number (999) if no expiry information available,
    so the position won't be falsely triggered by DTE conditions.
    """
    # 1. Try nearest_expiry column (set at position creation)
    nearest = position.get("nearest_expiry")
    if nearest:
        try:
            if isinstance(nearest, str):
                exp_date = date.fromisoformat(nearest[:10])
            elif isinstance(nearest, date):
                exp_date = nearest
            else:
                exp_date = None

            if exp_date:
                return (exp_date - date.today()).days
        except (ValueError, TypeError):
            pass

    # 2. Fallback: scan legs for earliest expiry
    legs = position.get("legs") or []
    expiry_dates = []
    for leg in legs:
        if not isinstance(leg, dict):
            continue
        exp = leg.get("expiry") or leg.get("expiration")
        if exp:
            try:
                expiry_dates.append(date.fromisoformat(str(exp)[:10]))
            except (ValueError, TypeError):
                continue

    if expiry_dates:
        nearest_date = min(expiry_dates)
        return (nearest_date - date.today()).days

    return 999  # No expiry info — don't trigger DTE conditions


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Strategy type detection
# ---------------------------------------------------------------------------

def _is_debit_spread(position: Dict[str, Any]) -> bool:
    """
    Detect whether a position is a debit spread (long entry).

    Debit spreads: you PAY to enter, profit when spread widens.
    Credit spreads: you RECEIVE premium, profit when spread narrows.

    Detection priority:
    1. Strategy name contains LONG_ or DEBIT
    2. Quantity > 0 (long position)
    """
    strategy = (position.get("strategy_key") or position.get("strategy") or "").upper()
    if "LONG_" in strategy or "DEBIT" in strategy:
        return True
    qty = float(position.get("quantity") or 0)
    return qty > 0


def _time_scaled_target_profit_pct(pos: Dict, base_pct: float = 0.35) -> float:
    """
    Scale profit target by time remaining in the trade using sqrt-decay.

    Theta decay on debit spreads is exponential (accelerates in the final
    10-15 days). A sqrt-decay target curve drops faster as DTE shrinks,
    matching theta's acceleration and locking in profits before erosion.

    At entry (dte/entry_dte=1.0): target = 50%
    At 50% elapsed:               target ≈ 35%
    At 5 DTE / 35 entry:          target ≈ 19%

    Falls back to base_pct if DTE data is missing.
    """
    dte = days_to_expiry(pos)
    entry_dte = pos.get("entry_dte") or 35  # scanner default

    if entry_dte <= 0 or dte <= 0:
        return base_pct

    # Sqrt-decay: drops faster as DTE shrinks, matching theta acceleration
    dte_ratio = max(dte / entry_dte, 0.0)
    target = 0.50 * (dte_ratio ** 0.5)
    return max(base_pct * 0.7, min(0.55, target))


def _check_target_profit(pos: Dict, tp_pct: float = 0.50) -> bool:
    """Check if position has reached target profit (debit-aware)."""
    mc = pos.get("max_credit")
    if mc is None:
        return False
    mc = float(mc)
    if mc == 0:
        return False
    upl = float(pos.get("unrealized_pl") or 0)
    entry_cost = abs(mc) * 100

    if _is_debit_spread(pos):
        # Debit spread: profit target = tp_pct of what we paid
        return upl >= entry_cost * tp_pct
    else:
        # Credit spread: profit target = tp_pct of credit received
        return mc > 0 and upl >= entry_cost * tp_pct


def _check_stop_loss(pos: Dict, sl_pct: float = 2.0) -> bool:
    """Check if position has exceeded stop loss (debit-aware)."""
    mc = pos.get("max_credit")
    if mc is None:
        return False
    mc = float(mc)
    if mc == 0:
        return False
    upl = float(pos.get("unrealized_pl") or 0)
    entry_cost = abs(mc) * 100

    if _is_debit_spread(pos):
        # Debit spread: stop loss at sl_pct of entry cost (0.5 = lose half)
        # For debit spreads sl_pct is reinterpreted as fraction of entry cost
        # (default 2.0 → clamp to 1.0 since you can't lose more than you paid)
        effective_sl = min(sl_pct, 1.0) if sl_pct > 1.0 else sl_pct
        return upl <= -(entry_cost * effective_sl)
    else:
        # Credit spread: stop loss at sl_pct × credit received
        return mc > 0 and upl <= -(entry_cost * sl_pct)


# Exit condition definitions
# ---------------------------------------------------------------------------
# Exit ranking — orders triggered exits by priority
# ---------------------------------------------------------------------------

def rank_triggered_exits(close_candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Rank positions that already triggered exit conditions.

    Does NOT create new exit triggers — only orders the execution.

    Priority:
    1. Emergency stops (loss > 80% of entry) — always first
    2. Stop losses — worst loss first
    3. DTE exits — nearest expiry first
    4. Target profits — biggest winner first (lock in most profit)

    Within stop_loss and target_profit, secondary sort by marginal_value:
      marginal_value = unrealized_pl / (time_remaining_pct * entry_value)
      Lower = worse risk/reward = close first for stops.
    """
    emergency: List[Dict] = []
    stops: List[Dict] = []
    targets: List[Dict] = []
    dte_exits: List[Dict] = []

    for c in close_candidates:
        reason = c.get("reason", "")
        unrealized = float(c.get("unrealized_pl") or 0)
        mc = float(c.get("max_credit") or 0)
        qty = abs(float(c.get("quantity") or 1))
        entry_value = abs(mc) * qty * 100
        dte = c.get("dte", 30)

        # Marginal value: P&L per unit of remaining time × capital
        time_remaining_pct = max(dte / 30.0, 0.01)
        c["marginal_value"] = round(
            unrealized / max(entry_value * time_remaining_pct, 1.0), 4
        )

        # Emergency: loss exceeds 80% of entry value
        if entry_value > 0 and unrealized <= -(entry_value * 0.80):
            emergency.append(c)
        elif reason == "stop_loss":
            stops.append(c)
        elif reason in ("dte_threshold", "expiration_day"):
            dte_exits.append(c)
        elif reason == "target_profit":
            targets.append(c)
        else:
            dte_exits.append(c)  # unknown reasons treated as dte

    # Sort within categories
    emergency.sort(key=lambda p: p["marginal_value"])               # worst first
    stops.sort(key=lambda p: p["marginal_value"])                    # worst first
    dte_exits.sort(key=lambda p: p.get("dte", 999))                  # nearest expiry first
    targets.sort(key=lambda p: p["marginal_value"], reverse=True)    # biggest win first

    ranked = emergency + stops + dte_exits + targets

    # Log ranking
    if ranked:
        lines = [f"[EXIT_RANK] {len(ranked)} positions triggered exits:"]
        for i, c in enumerate(ranked, 1):
            lines.append(
                f"  #{i} {c.get('symbol','?')} {c.get('reason','?')}  "
                f"marginal={c['marginal_value']:+.2f}  "
                f"unrealized=${c.get('unrealized_pl', 0):+,.0f}  "
                f"dte={c.get('dte', '?')}"
            )
        msg = "\n".join(lines)
        logger.info(msg)
        print(msg, flush=True)

    return ranked


# Exit condition definitions
# ---------------------------------------------------------------------------

# Default exit thresholds — used when no cohort config is resolved.
# These match the neutral cohort for a small ($500) account.
_DEFAULT_TARGET_PROFIT_PCT = float(os.environ.get("EXIT_TARGET_PROFIT_PCT", "0.35"))
_DEFAULT_STOP_LOSS_PCT = float(os.environ.get("EXIT_STOP_LOSS_PCT", "0.50"))
_DEFAULT_MIN_DTE_TO_EXIT = int(os.environ.get("EXIT_MIN_DTE", "10"))

EXIT_CONDITIONS: Dict[str, Dict[str, Any]] = {
    "target_profit": {
        "description": "Position has reached time-scaled target profit",
        "check": lambda pos: _check_target_profit(pos, _time_scaled_target_profit_pct(pos, _DEFAULT_TARGET_PROFIT_PCT)),
    },
    "stop_loss": {
        "description": f"Position has exceeded {_DEFAULT_STOP_LOSS_PCT:.0%} stop loss",
        "check": lambda pos: _check_stop_loss(pos, _DEFAULT_STOP_LOSS_PCT),
    },
    "dte_threshold": {
        "description": f"Position is within {_DEFAULT_MIN_DTE_TO_EXIT} DTE (gamma risk)",
        "check": lambda pos: 0 < days_to_expiry(pos) <= _DEFAULT_MIN_DTE_TO_EXIT,
    },
    "expiration_day": {
        "description": "Position expires today — must close",
        "check": lambda pos: days_to_expiry(pos) <= 0,
    },
}


def build_exit_conditions(
    target_profit_pct: float = 0.50,
    stop_loss_pct: float = 2.0,
    min_dte_to_exit: int = 7,
) -> Dict[str, Dict[str, Any]]:
    """Build exit conditions with configurable thresholds (used by Policy Lab)."""
    return {
        "target_profit": {
            "description": f"Position has reached {target_profit_pct:.0%} target profit",
            "check": lambda pos, tp=target_profit_pct: _check_target_profit(pos, tp),
        },
        "stop_loss": {
            "description": f"Position has exceeded {stop_loss_pct}x max loss",
            "check": lambda pos, sl=stop_loss_pct: _check_stop_loss(pos, sl),
        },
        "dte_threshold": {
            "description": f"Position is within {min_dte_to_exit} DTE (gamma risk)",
            "check": lambda pos, dte_min=min_dte_to_exit: 0 < days_to_expiry(pos) <= dte_min,
        },
        "expiration_day": {
            "description": "Position expires today — must close",
            "check": lambda pos: days_to_expiry(pos) <= 0,
        },
    }


def evaluate_position_exit(
    position: Dict[str, Any],
    conditions: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Optional[str]:
    """
    Check a single position against exit conditions.

    Args:
        position: Position dict with max_credit, unrealized_pl, etc.
        conditions: Override exit conditions (for Policy Lab cohorts).
                    Defaults to global EXIT_CONDITIONS.

    Returns the name of the first triggered condition, or None if position should hold.
    """
    if conditions is None:
        conditions = EXIT_CONDITIONS

    pos_id = position.get("id", "?")
    symbol = position.get("symbol", "?")
    max_credit = position.get("max_credit")
    unrealized_pl = position.get("unrealized_pl")
    nearest_expiry = position.get("nearest_expiry")
    qty = position.get("quantity")
    dte = days_to_expiry(position)

    fields_msg = (
        f"[EXIT_EVAL_DEBUG] position={pos_id} symbol={symbol} "
        f"qty={qty} max_credit={max_credit} (type={type(max_credit).__name__}) "
        f"unrealized_pl={unrealized_pl} (type={type(unrealized_pl).__name__}) "
        f"nearest_expiry={nearest_expiry} dte={dte}"
    )
    logger.info(fields_msg)
    print(fields_msg, flush=True)

    # Log threshold computations if max_credit is available
    # Use actual thresholds from conditions (cohort or default), not hardcoded values
    _active_tp = _DEFAULT_TARGET_PROFIT_PCT
    _active_sl = _DEFAULT_STOP_LOSS_PCT
    _active_dte = _DEFAULT_MIN_DTE_TO_EXIT
    if conditions:
        # Extract actual thresholds from the condition descriptions
        tp_desc = conditions.get("target_profit", {}).get("description", "")
        sl_desc = conditions.get("stop_loss", {}).get("description", "")
        dte_desc = conditions.get("dte_threshold", {}).get("description", "")

    is_debit = _is_debit_spread(position)
    if max_credit is not None:
        try:
            mc = float(max_credit)
            upl = float(unrealized_pl or 0)
            entry_cost = abs(mc) * 100
            if is_debit:
                tp_threshold = entry_cost * _active_tp
                sl_threshold = -(entry_cost * min(_active_sl, 1.0))
                spread_type = "DEBIT"
            else:
                tp_threshold = entry_cost * _active_tp
                sl_threshold = -(entry_cost * _active_sl)
                spread_type = "CREDIT"
            thresh_msg = (
                f"[EXIT_EVAL_DEBUG] position={pos_id} type={spread_type} "
                f"target_profit: {upl} >= {tp_threshold} ? {upl >= tp_threshold} | "
                f"stop_loss: {upl} <= {sl_threshold} ? {upl <= sl_threshold} | "
                f"dte_threshold: 0 < {dte} <= 7 ? {0 < dte <= 7} | "
                f"expiration_day: {dte} <= 0 ? {dte <= 0}"
            )
            logger.info(thresh_msg)
            print(thresh_msg, flush=True)
        except (TypeError, ValueError) as e:
            logger.warning(f"[EXIT_EVAL_DEBUG] position={pos_id} threshold calc error: {e}")
            print(f"[EXIT_EVAL_DEBUG] position={pos_id} threshold calc error: {e}", flush=True)
    else:
        print(f"[EXIT_EVAL_DEBUG] position={pos_id} max_credit is None — skipping P&L conditions", flush=True)

    # #72-H5a: aggregation list for per-condition eval failures
    per_condition_failures = []

    for condition_name, condition in conditions.items():
        try:
            result = condition["check"](position)
            logger.info(
                f"[EXIT_EVAL_DEBUG] position={pos_id} condition={condition_name} result={result}"
            )
            print(f"[EXIT_EVAL_DEBUG] position={pos_id} condition={condition_name} result={result}", flush=True)
            if result:
                return condition_name
        except Exception as e:
            logger.warning(
                f"Exit condition '{condition_name}' error for position "
                f"{position.get('id')}: {e}"
            )
            print(f"[EXIT_EVAL_DEBUG] position={pos_id} condition={condition_name} ERROR: {e}", flush=True)
            per_condition_failures.append({
                "position_id": position.get("id"),
                "symbol": position.get("symbol"),
                "condition_name": condition_name,
                "error_class": type(e).__name__,
                "error_message": str(e)[:200],
            })

    # #72-H5a: aggregated alert for per-condition exit eval failures
    if per_condition_failures:
        _failed_symbols = list({f["symbol"] for f in per_condition_failures if f.get("symbol")})[:20]
        _distinct_error_classes = sorted({f["error_class"] for f in per_condition_failures})
        alert(
            _get_admin_supabase(),
            alert_type="paper_exit_per_condition_eval_failed",
            severity="warning",
            message=f"{len(per_condition_failures)} per-condition exit evaluations failed",
            user_id=position.get("user_id"),
            metadata={
                "function_name": "evaluate_position_exit",
                "failed_count": len(per_condition_failures),
                "failed_symbols": _failed_symbols,
                "distinct_error_classes": _distinct_error_classes,
                "position_id": position.get("id"),
                "consequence": f"{len(per_condition_failures)} exit conditions skipped — positions may not exit when triggers fire",
            },
        )

    return None


class PaperExitEvaluator:
    """Evaluates open positions against exit conditions and closes triggered ones."""

    def __init__(self, supabase_client):
        self.client = supabase_client

    def evaluate_exits(self, user_id: str) -> Dict[str, Any]:
        """
        Check all open positions against exit conditions. Close those that trigger.

        Returns summary with closes, holds, and close_reasons breakdown.
        """
        from packages.quantum.services.paper_mark_to_market_service import (
            PaperMarkToMarketService,
        )

        print(f"[EXIT_EVAL_DEBUG] evaluate_exits called for user={user_id}", flush=True)

        # 0. Ops control: check if trading is paused
        try:
            from packages.quantum.ops_endpoints import is_trading_paused
            paused, reason = is_trading_paused()
            if paused:
                logger.info(f"exit_eval_paused: reason={reason}")
                return {"status": "paused", "reason": reason, "closes": [], "holds": []}
        except Exception:
            pass  # If ops_control unavailable, continue

        # 1. Refresh marks first so unrealized_pl is current
        mtm = PaperMarkToMarketService(self.client)
        mtm_result = mtm.refresh_marks(user_id)
        logger.info(f"[EXIT_EVAL_DEBUG] refresh_marks result: {mtm_result}")
        print(f"[EXIT_EVAL_DEBUG] refresh_marks result: {mtm_result}", flush=True)

        # 2. Get enriched open positions
        positions = self._get_open_positions(user_id)
        logger.info(
            f"[EXIT_EVAL_DEBUG] fetched {len(positions)} open positions for user={user_id}"
        )
        print(f"[EXIT_EVAL_DEBUG] fetched {len(positions)} open positions", flush=True)
        for p in positions:
            msg = (
                f"[EXIT_EVAL_DEBUG] position_row: id={p.get('id')} "
                f"symbol={p.get('symbol')} qty={p.get('quantity')} "
                f"avg_entry={p.get('avg_entry_price')} "
                f"max_credit={p.get('max_credit')} "
                f"unrealized_pl={p.get('unrealized_pl')} "
                f"current_mark={p.get('current_mark')} "
                f"nearest_expiry={p.get('nearest_expiry')}"
            )
            logger.info(msg)
            print(msg, flush=True)
        if not positions:
            return {
                "status": "ok",
                "total_open": 0,
                "closing": 0,
                "holding": 0,
                "closes": [],
                "close_reasons": {},
            }

        # 3. Evaluate each position with cohort-specific exit conditions.
        #    Always loads cohort configs from DB (not gated by POLICY_LAB_ENABLED).
        #    If no cohorts exist, falls back to global EXIT_CONDITIONS.
        closes: List[Dict[str, Any]] = []
        holds: List[Dict[str, Any]] = []

        # Build cohort → exit conditions map
        cohort_conditions_cache: Dict[str, Dict] = {}
        try:
            from packages.quantum.policy_lab.config import load_cohort_configs
            cohort_cfgs = load_cohort_configs(user_id, self.client)
            for cname, cfg in cohort_cfgs.items():
                cohort_conditions_cache[cname] = build_exit_conditions(
                    target_profit_pct=cfg.target_profit_pct,
                    stop_loss_pct=cfg.stop_loss_pct,
                    min_dte_to_exit=cfg.min_dte_to_exit,
                )
            if cohort_conditions_cache:
                logger.info(
                    f"[EXIT_EVAL] Loaded {len(cohort_conditions_cache)} cohort configs: "
                    + ", ".join(
                        f"{k}(tp={cohort_cfgs[k].target_profit_pct:.0%},sl={cohort_cfgs[k].stop_loss_pct})"
                        for k in cohort_conditions_cache
                    )
                )
        except Exception as e:
            logger.warning(f"[EXIT_EVAL] Failed to load cohort configs: {e}")
            alert(
                _get_admin_supabase(),
                alert_type="paper_exit_cohort_configs_load_failed",
                severity="warning",
                message=f"Cohort configs load failed: {type(e).__name__}",
                user_id=user_id,
                metadata={
                    "function_name": "evaluate_exits",
                    "error_class": type(e).__name__,
                    "error_message": str(e)[:500],
                    "consequence": "exit evaluation continues with default cohort routing — cohort-specific exit logic may not apply",
                },
            )

        for position in positions:
            # Resolve cohort-specific exit conditions
            pos_conditions = None
            cohort = self._resolve_position_cohort(position)
            if cohort and cohort in cohort_conditions_cache:
                pos_conditions = cohort_conditions_cache[cohort]

            triggered = evaluate_position_exit(position, conditions=pos_conditions)
            active_conditions = pos_conditions or EXIT_CONDITIONS
            if triggered:
                closes.append({
                    "position_id": position["id"],
                    "symbol": position.get("symbol"),
                    "reason": triggered,
                    "description": active_conditions[triggered]["description"],
                    "unrealized_pl": float(position.get("unrealized_pl") or 0),
                    "max_credit": float(position.get("max_credit") or 0),
                    "quantity": float(position.get("quantity") or 1),
                    "dte": days_to_expiry(position),
                })
            else:
                holds.append(position)

        # 4. Rank triggered exits by marginal value (if enabled)
        if EXIT_RANKING_ENABLED and closes:
            closes = rank_triggered_exits(closes)

        # 5. PDT Guard — separate same-day vs overnight exits
        from packages.quantum.services.pdt_guard_service import (
            is_pdt_enabled, get_pdt_status, is_same_day_close,
            is_emergency_stop, record_day_trade, _chicago_today,
        )

        pdt_on = is_pdt_enabled()
        pdt_summary = {
            "enabled": pdt_on,
            "day_trades_used": 0,
            "day_trades_remaining": PDT_MAX_DAY_TRADES,
            "same_day_exits_requested": 0,
            "same_day_exits_allowed": 0,
            "same_day_exits_blocked": 0,
            "emergency_overrides": 0,
        }

        # Build a position lookup so we can access full position data for PDT checks
        pos_by_id = {p["id"]: p for p in positions}

        if pdt_on:
            pdt_status = get_pdt_status(self.client, user_id)
            pdt_summary["day_trades_used"] = pdt_status["day_trades_used"]
            pdt_summary["day_trades_remaining"] = pdt_status["day_trades_remaining"]

            today_chicago = _chicago_today()
            remaining_day_trades = pdt_status["day_trades_remaining"]

            logger.info(
                f"[PDT] Status: {pdt_status['day_trades_used']}/{PDT_MAX_DAY_TRADES} "
                f"day trades used ({remaining_day_trades} remaining)"
            )

            # Partition closes into same-day and overnight (preserving ranked order)
            same_day_closes = []
            overnight_closes = []

            for close_item in closes:
                pos = pos_by_id.get(close_item["position_id"], {})
                if is_same_day_close(pos, today_chicago):
                    same_day_closes.append(close_item)
                else:
                    overnight_closes.append(close_item)

            pdt_summary["same_day_exits_requested"] = len(same_day_closes)

            # Overnight exits: always allowed (no PDT concern)
            allowed_closes = list(overnight_closes)

            # Same-day exits: apply PDT limit using ranked order
            if same_day_closes:
                for c in same_day_closes:
                    pos = pos_by_id.get(c["position_id"], {})

                    # Emergency stops always close regardless of PDT
                    if is_emergency_stop(pos):
                        allowed_closes.append(c)
                        pdt_summary["emergency_overrides"] += 1
                        logger.critical(
                            f"[PDT] EMERGENCY: {c['symbol']} unrealized_pl={c['unrealized_pl']:.0f} "
                            f"— closing despite PDT limit (capital protection)"
                        )
                        continue

                    if remaining_day_trades > 0:
                        allowed_closes.append(c)
                        remaining_day_trades -= 1
                        pdt_summary["same_day_exits_allowed"] += 1
                        action = "CLOSE"
                    else:
                        holds.append(pos_by_id.get(c["position_id"], {}))
                        pdt_summary["same_day_exits_blocked"] += 1
                        action = "HOLD"

                    logger.info(
                        f"[EXIT_RANK] {action}: {c['symbol']} {c.get('reason','?')} "
                        f"marginal={c.get('marginal_value', 0):+.2f} "
                        f"${c.get('unrealized_pl', 0):+,.0f}"
                        + (f" — day trade {PDT_MAX_DAY_TRADES - remaining_day_trades}/{PDT_MAX_DAY_TRADES}"
                           if action == "CLOSE" else " — PDT limit, overnight hold")
                    )

            closes = allowed_closes
        # else: pdt_on is False — close everything as before (no filtering)

        # 6. Close triggered positions
        closed_results = []
        # #72-H5a: aggregation list for close-loop failures (close itself
        # plus the record_day_trade write — both are caught by the outer
        # except and would otherwise be log-only).
        _close_loop_failures = []
        for close_item in closes:
            try:
                result = self._close_position(
                    user_id,
                    close_item["position_id"],
                    close_item["reason"],
                )
                closed_results.append({**close_item, **result})

                # Record day trade if PDT enabled and this was a same-day close
                if pdt_on:
                    pos = pos_by_id.get(close_item["position_id"], {})
                    today_chicago = _chicago_today()
                    if is_same_day_close(pos, today_chicago):
                        record_day_trade(
                            supabase=self.client,
                            user_id=user_id,
                            position_id=close_item["position_id"],
                            symbol=close_item.get("symbol", ""),
                            opened_at=pos.get("created_at", ""),
                            closed_at=datetime.now(timezone.utc).isoformat(),
                            trade_date=today_chicago,
                            realized_pl=close_item.get("unrealized_pl", 0),
                            close_reason=close_item.get("reason", ""),
                        )
            except Exception as e:
                logger.error(
                    f"Failed to close position {close_item['position_id']}: {e}"
                )
                closed_results.append({**close_item, "error": str(e)})
                _close_loop_failures.append({
                    "position_id": close_item.get("position_id"),
                    "symbol": close_item.get("symbol"),
                    "error_class": type(e).__name__,
                    "error_message": str(e)[:200],
                })

        # #72-H5a: aggregated alert for close-loop failures (record_day_trade
        # writes + any unhandled exceptions from _close_position).
        if _close_loop_failures:
            _failed_symbols = list({f["symbol"] for f in _close_loop_failures if f.get("symbol")})[:20]
            _distinct_error_classes = sorted({f["error_class"] for f in _close_loop_failures})
            alert(
                _get_admin_supabase(),
                alert_type="paper_exit_day_trade_record_failed",
                severity="warning",
                message=f"{len(_close_loop_failures)} close-loop processing failures during exits",
                user_id=user_id,
                metadata={
                    "function_name": "evaluate_exits",
                    "failed_count": len(_close_loop_failures),
                    "failed_symbols": _failed_symbols,
                    "distinct_error_classes": _distinct_error_classes,
                    "consequence": f"{len(_close_loop_failures)} positions: day-trade history records lost (PDT counter may drift) and/or close-pipeline post-processing failed",
                },
            )

        # 7. Build reason summary
        close_reasons: Dict[str, int] = {}
        for c in closes:
            reason = c["reason"]
            close_reasons[reason] = close_reasons.get(reason, 0) + 1

        logger.info(
            f"exit_evaluation_summary: user_id={user_id} "
            f"total_open={len(positions)} closing={len(closes)} "
            f"holding={len(holds)} reasons={close_reasons} "
            f"pdt={pdt_summary}"
        )

        return {
            "status": "ok",
            "total_open": len(positions),
            "closing": len(closes),
            "holding": len(holds),
            "closes": closed_results,
            "close_reasons": close_reasons,
            "pdt_status": pdt_summary,
        }

    def _get_open_positions(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all open paper positions for a user."""
        try:
            port_res = self.client.table("paper_portfolios") \
                .select("id") \
                .eq("user_id", user_id) \
                .execute()

            portfolio_ids = [p["id"] for p in (port_res.data or [])]
            if not portfolio_ids:
                return []

            pos_res = self.client.table("paper_positions") \
                .select("*") \
                .in_("portfolio_id", portfolio_ids) \
                .eq("status", "open") \
                .neq("quantity", 0) \
                .execute()

            return pos_res.data or []
        except Exception as e:
            logger.error(f"Failed to fetch positions for exit eval: {e}")
            alert(
                _get_admin_supabase(),
                alert_type="paper_exit_open_positions_fetch_failed",
                severity="warning",
                message=f"Open positions fetch failed: {type(e).__name__}",
                user_id=user_id,
                metadata={
                    "function_name": "_get_open_positions",
                    "error_class": type(e).__name__,
                    "error_message": str(e)[:500],
                    "consequence": "exit evaluation skipped this cycle — open positions not exited regardless of triggers",
                },
            )
            return []

    def _resolve_position_cohort(self, position: Dict[str, Any]) -> Optional[str]:
        """
        Resolve which cohort a position belongs to.

        Priority:
        1. Direct cohort_id on paper_positions (set at creation time)
        2. Fallback: portfolio_id → policy_lab_cohorts lookup
        3. Fallback: champion cohort for positions on the default portfolio

        #72-H5a: tracks each fallback's failure reason; alerts only when
        ALL three paths failed (cohort genuinely unresolvable). If any
        path returns a cohort, the alert is suppressed.
        """
        # #72-H5a: track resolution failures across all 3 paths
        _resolution_failures = []

        # Fast path: direct cohort_id (new positions have this set)
        cohort_id = position.get("cohort_id")
        if cohort_id:
            try:
                res = self.client.table("policy_lab_cohorts") \
                    .select("cohort_name") \
                    .eq("id", cohort_id) \
                    .limit(1) \
                    .execute()
                if res.data:
                    return res.data[0]["cohort_name"]
            except Exception as _path1_err:
                _resolution_failures.append(("cohort_id", type(_path1_err).__name__, str(_path1_err)[:200]))

        portfolio_id = position.get("portfolio_id")
        user_id = position.get("user_id")

        # Fallback: portfolio_id → cohort lookup
        if portfolio_id:
            try:
                res = self.client.table("policy_lab_cohorts") \
                    .select("cohort_name") \
                    .eq("portfolio_id", portfolio_id) \
                    .limit(1) \
                    .execute()
                if res.data:
                    return res.data[0]["cohort_name"]
            except Exception as _path2_err:
                _resolution_failures.append(("portfolio_id", type(_path2_err).__name__, str(_path2_err)[:200]))

        # Fallback: champion cohort for positions on the default portfolio
        if user_id:
            try:
                res = self.client.table("policy_lab_cohorts") \
                    .select("cohort_name") \
                    .eq("user_id", user_id) \
                    .eq("is_champion", True) \
                    .eq("is_active", True) \
                    .limit(1) \
                    .execute()
                if res.data:
                    return res.data[0]["cohort_name"]
            except Exception as _path3_err:
                _resolution_failures.append(("champion", type(_path3_err).__name__, str(_path3_err)[:200]))

        # #72-H5a: all three paths failed (each raised) — alert.
        # If a path simply returned no data (no exception), no alert.
        if len(_resolution_failures) == 3:
            alert(
                _get_admin_supabase(),
                alert_type="paper_exit_cohort_resolve_exhausted",
                severity="warning",
                message=f"All cohort resolution paths failed for position {position.get('id')}",
                user_id=user_id,
                metadata={
                    "function_name": "_resolve_position_cohort",
                    "position_id": position.get("id"),
                    "symbol": position.get("symbol"),
                    "resolution_attempts": [
                        {"path": p, "error_class": ec, "error_message": em}
                        for p, ec, em in _resolution_failures
                    ],
                    "consequence": "position routed to default cohort — cohort-specific exit logic bypassed",
                },
            )

        return None

    def _close_position(
        self,
        user_id: str,
        position_id: str,
        reason: str,
    ) -> Dict[str, Any]:
        """
        Close a single position using the position's current_mark as exit price.
        """
        from packages.quantum.paper_endpoints import (
            _stage_order_internal,
            get_analytics_service,
        )
        from packages.quantum.models import TradeTicket
        from packages.quantum.services.paper_autopilot_service import (
            PaperAutopilotService,
        )
        from packages.quantum.services.paper_ledger_service import (
            PaperLedgerService,
            PaperLedgerEventType,
        )

        supabase = self.client
        analytics = get_analytics_service()

        # ── HARD ROUTING CHECK (cannot be bypassed) ──────────────────
        # Determine how the position was opened BEFORE doing anything else.
        # This decision controls ALL downstream routing.
        position_is_alpaca = False
        entry_order_id = "none"
        try:
            entry_res = supabase.table("paper_orders") \
                .select("id, alpaca_order_id") \
                .eq("position_id", position_id) \
                .order("created_at", desc=False) \
                .limit(1) \
                .execute()
            if entry_res.data:
                entry_order_id = entry_res.data[0]["id"][:8]
                position_is_alpaca = entry_res.data[0].get("alpaca_order_id") is not None
        except Exception as e:
            entry_order_id = f"error:{e}"
            alert(
                _get_admin_supabase(),
                alert_type="paper_exit_routing_query_failed",
                severity="warning",
                message=f"Entry-routing query failed for close path: {type(e).__name__}",
                user_id=user_id,
                metadata={
                    "function_name": "_close_position",
                    "position_id": position_id,
                    "error_class": type(e).__name__,
                    "error_message": str(e)[:500],
                    "consequence": "close path defaulted (may use wrong execution route)",
                },
            )

        print(
            f"[EXIT_ROUTING] position={position_id[:8]} "
            f"entry_order={entry_order_id} "
            f"has_alpaca_entry={position_is_alpaca} "
            f"→ {'ALPACA' if position_is_alpaca else 'INTERNAL'}",
            flush=True,
        )
        logger.info(
            f"[EXIT_ROUTING] position={position_id[:8]} "
            f"entry_order={entry_order_id} "
            f"has_alpaca_entry={position_is_alpaca} "
            f"→ {'ALPACA' if position_is_alpaca else 'INTERNAL'}"
        )

        # ── Idempotency: block if a close order already exists ──────
        # Check ALL non-terminal statuses including needs_manual_review.
        # Without this, every caller (_execute_force_close, evaluate_exits)
        # creates a new staged order on each invocation, causing 100+ orders
        # to pile up when submission repeatedly fails (e.g. held_for_orders).
        try:
            existing_close = supabase.table("paper_orders") \
                .select("id, status, created_at") \
                .eq("position_id", position_id) \
                .in_("status", [
                    "staged", "submitted", "working", "partial", "pending",
                    "needs_manual_review",
                ]) \
                .order("created_at", desc=True) \
                .limit(1) \
                .execute()
            if existing_close.data:
                existing = existing_close.data[0]
                logger.info(
                    f"[CLOSE_POSITION] Skipping — close order already exists "
                    f"for position={position_id[:8]}: "
                    f"order={existing['id'][:8]} status={existing['status']}"
                )
                return {
                    "order_id": existing["id"],
                    "processed": 0,
                    "routed_to": "skipped_duplicate",
                    "note": f"Existing close order {existing['id'][:8]} "
                            f"status={existing['status']}",
                }
        except Exception as e:
            logger.warning(
                f"[CLOSE_POSITION] Idempotency check failed for "
                f"position={position_id[:8]}: {e}"
            )
            alert(
                _get_admin_supabase(),
                alert_type="paper_exit_idempotency_check_failed",
                severity="warning",
                message=f"Idempotency check failed for close: {type(e).__name__}",
                user_id=user_id,
                metadata={
                    "function_name": "_close_position",
                    "position_id": position_id,
                    "error_class": type(e).__name__,
                    "error_message": str(e)[:500],
                    "consequence": "close proceeds without idempotency guard — duplicate close orders possible",
                },
            )

        # ── Fetch position ───────────────────────────────────────────
        pos_res = supabase.table("paper_positions") \
            .select("*") \
            .eq("id", position_id) \
            .single() \
            .execute()
        position = pos_res.data

        qty = float(position["quantity"])
        side = "sell" if qty > 0 else "buy"
        abs_qty = abs(qty)
        multiplier = 100.0

        exit_price = float(position.get("current_mark") or position.get("avg_entry_price") or 0)
        entry_price = float(position.get("avg_entry_price") or 0)

        # ── Build close ticket with ALL legs ─────────────────────────
        orig_legs = position.get("legs") or []

        if len(orig_legs) >= 2:
            # Multi-leg: build close legs from all original legs (invert sides).
            # Stored legs use "action" (from OptionLeg model), not "side".
            close_legs = []
            for i, leg in enumerate(orig_legs):
                orig_action = leg.get("action") or leg.get("side") or "buy"
                inverted = "sell" if orig_action == "buy" else "buy"
                logger.info(
                    f"[CLOSE_LEG_BUILD] leg[{i}] symbol={leg.get('symbol', '?')[:20]} "
                    f"raw_action={leg.get('action')!r} raw_side={leg.get('side')!r} "
                    f"→ orig_action={orig_action!r} → inverted={inverted!r}"
                )
                close_legs.append({
                    "symbol": leg.get("symbol") or leg.get("occ_symbol") or "",
                    "action": inverted,
                    "quantity": abs_qty,
                    "type": leg.get("type", "call"),
                    "strike": leg.get("strike"),
                    "expiry": leg.get("expiry"),
                })
        else:
            # Single-leg or no legs: use OCC symbol resolution
            occ_symbol = PaperAutopilotService._resolve_occ_symbol(position, supabase)
            orig_leg = orig_legs[0] if orig_legs else {}
            close_legs = [{
                "symbol": occ_symbol,
                "action": side,
                "quantity": abs_qty,
                "type": orig_leg.get("type", "call"),
                "strike": orig_leg.get("strike"),
                "expiry": orig_leg.get("expiry"),
            }]

        ticket = TradeTicket(
            symbol=position["symbol"],
            quantity=abs_qty,
            order_type="limit",
            limit_price=round(exit_price, 2),
            strategy_type="custom",
            source_engine="paper_exit_evaluator",
            legs=close_legs,
        )

        if position.get("suggestion_id"):
            ticket.source_ref_id = position["suggestion_id"]

        # ── Stage and route ──────────────────────────────────────────
        # For internal positions: force internal_paper mode during staging
        # so _stage_order_internal does NOT submit to Alpaca.
        dry_run = os.environ.get("ALPACA_DRY_RUN", "0") == "1"
        _saved_mode = os.environ.get("EXECUTION_MODE", "")

        if not position_is_alpaca:
            os.environ["EXECUTION_MODE"] = "internal_paper"

        try:
            order_id = _stage_order_internal(
                supabase,
                analytics,
                user_id,
                ticket,
                position["portfolio_id"],
                position_id=position_id,
                trace_id_override=position.get("trace_id"),
            )
        finally:
            os.environ["EXECUTION_MODE"] = _saved_mode

        now = datetime.now(timezone.utc).isoformat()

        if position_is_alpaca:
            if dry_run:
                # Log what we WOULD submit, but hold the position open
                from packages.quantum.brokers.alpaca_order_handler import build_alpaca_order_request
                try:
                    order_row = supabase.table("paper_orders") \
                        .select("*").eq("id", order_id).single().execute().data
                    req = build_alpaca_order_request(order_row)
                    logger.info(
                        f"[ALPACA_DRY_RUN] Exit order_id={order_id} "
                        f"symbol={position['symbol']}: {req}"
                    )
                except Exception as e:
                    logger.warning(
                        f"[ALPACA_DRY_RUN] Exit build failed: order_id={order_id} "
                        f"symbol={position['symbol']} error={e}"
                    )
                    alert(
                        _get_admin_supabase(),
                        alert_type="paper_exit_alpaca_dry_run_build_failed",
                        severity="warning",
                        message=f"Alpaca DRY_RUN order build failed: {type(e).__name__}",
                        user_id=user_id,
                        symbol=position.get("symbol"),
                        metadata={
                            "function_name": "_close_position",
                            "position_id": position_id,
                            "order_id": order_id,
                            "symbol": position.get("symbol"),
                            "error_class": type(e).__name__,
                            "error_message": str(e)[:500],
                            "consequence": "DRY_RUN simulation skipped — close proceeds without dry-run validation",
                        },
                    )
                # Do NOT fall through to internal fill — position stays open
                return {
                    "order_id": order_id,
                    "processed": 0,
                    "routed_to": "alpaca_dry_run",
                    "note": "Dry run — position held, order staged but not filled",
                }
            else:
                # #62a-D4-PR2a: gate broker submission on portfolio routing_mode.
                # shadow_only positions shouldn't normally exist post-PR2a (entry
                # path blocks), but pre-PR2a phantom positions need their close
                # path gated too. Block Alpaca submit; PR2b will handle the
                # shadow close fill machinery.
                from packages.quantum.brokers.execution_router import should_submit_to_broker
                if not should_submit_to_broker(position["portfolio_id"], supabase):
                    supabase.table("paper_orders") \
                        .update({"execution_mode": "shadow_blocked"}) \
                        .eq("id", order_id) \
                        .execute()
                    logger.info(
                        f"[ROUTING] Blocked Alpaca close for shadow_only portfolio: "
                        f"order_id={order_id} position_id={position_id[:8]}"
                    )
                    return {
                        "order_id": order_id,
                        "processed": 0,
                        "routed_to": "shadow_blocked",
                        "note": "shadow_only portfolio — Alpaca close blocked, position remains open pending PR2b",
                    }
                try:
                    from packages.quantum.brokers.alpaca_order_handler import submit_and_track
                    from packages.quantum.brokers.alpaca_client import get_alpaca_client
                    alpaca = get_alpaca_client()

                    order_row = supabase.table("paper_orders") \
                        .select("*").eq("id", order_id).single().execute().data

                    submit_and_track(alpaca, supabase, order_row, user_id)

                    logger.info(
                        f"[EXIT_EVAL] Submitted close to Alpaca: order_id={order_id} "
                        f"symbol={position['symbol']} side={side} qty={abs_qty}"
                    )

                    # Don't fill or close position here — alpaca_order_sync will
                    # pick up the fill and _commit_fill / _process_orders_for_user
                    # handles position updates.
                    return {
                        "order_id": order_id,
                        "processed": 0,
                        "routed_to": "alpaca",
                        "note": "Fill pending — will be synced by alpaca_order_sync",
                    }
                except Exception as e:
                    # #72-H5a SAFETY-CRITICAL: 2026-04-16 ghost-position bug shape.
                    # Alpaca submit failed; code falls through to internal fill,
                    # marking the position filled when broker order may not have
                    # submitted. Alert fires BEFORE the fall-through so operator
                    # awareness precedes phantom-fill accumulation.
                    alert(
                        _get_admin_supabase(),
                        alert_type="paper_exit_alpaca_submit_fallback_to_internal",
                        severity="critical",
                        message=f"Alpaca submit failed during close, falling back to internal fill: {type(e).__name__}",
                        user_id=user_id,
                        symbol=position.get("symbol"),
                        position_id=position_id,
                        metadata={
                            "function_name": "_close_position",
                            "position_id": position_id,
                            "order_id": order_id,
                            "symbol": position.get("symbol"),
                            "error_class": type(e).__name__,
                            "error_message": str(e)[:500],
                            "consequence": "Alpaca order may not have submitted; position will be marked filled internally regardless. Risk: phantom internal fill while real broker state diverges (2026-04-16 ghost-position pattern).",
                            "operator_action_required": "Verify Alpaca order status manually for this position before treating internal fill as authoritative. Check for ghost-position pattern from 2026-04-16 incident. If broker order did not submit, manually reconcile position state.",
                        },
                    )
                    logger.error(
                        f"[EXIT_EVAL] Alpaca submit failed for close order {order_id}: {e}. "
                        f"Falling back to internal fill."
                    )
                    # Fall through to internal fill below

        # --- Internal fill at current_mark (internal_paper or Alpaca fallback) ---

        # 1. Mark order as filled
        supabase.table("paper_orders").update({
            "status": "filled",
            "filled_qty": abs_qty,
            "avg_fill_price": round(exit_price, 2),
            "fees_usd": 0,
            "filled_at": now,
        }).eq("id", order_id).execute()

        # 2. Update portfolio cash
        #    Buy-to-close (short position): cash -= exit_price * qty * 100
        #    Sell-to-close (long position): cash += exit_price * qty * 100
        txn_value = exit_price * abs_qty * multiplier
        cash_delta = txn_value if side == "sell" else -txn_value

        port_res = supabase.table("paper_portfolios") \
            .select("cash_balance") \
            .eq("id", position["portfolio_id"]) \
            .single() \
            .execute()
        current_cash = float(port_res.data["cash_balance"])
        new_cash = current_cash + cash_delta

        supabase.table("paper_portfolios").update({
            "cash_balance": new_cash,
        }).eq("id", position["portfolio_id"]).execute()

        # 3. Emit ledger entry
        ledger = PaperLedgerService(supabase)
        ledger.emit_fill(
            portfolio_id=position["portfolio_id"],
            amount=cash_delta,
            balance_after=new_cash,
            order_id=order_id,
            position_id=position_id,
            trace_id=position.get("trace_id"),
            user_id=user_id,
            metadata={
                "side": side,
                "qty": abs_qty,
                "price": exit_price,
                "symbol": position["symbol"],
                "fees": 0,
                "source": "exit_evaluator",
                "reason": reason,
            },
        )

        # 4. Close position via shared pipeline.
        #
        # PR #6 refactor. Route the internal-fill close through the
        # canonical close_math + close_helper stack so all 4 handlers
        # produce bit-identical realized_pl for equivalent inputs.
        #
        # Internal simulation vs real broker fill: the reconciler path
        # extracts close_legs from Alpaca fill data (actual per-leg
        # prices). The internal-fill path has only a per-spread
        # current_mark, so we synthesize a single LegFill from it.
        # This is the legitimate architectural difference between real
        # leg-level reconciliation and internal MTM simulation — both
        # flow through the same compute_realized_pl contract.
        synth_action = "sell" if qty > 0 else "buy"
        spread_type = "debit" if qty > 0 else "credit"
        synth_legs = [{
            "symbol": position.get("symbol"),
            "action": synth_action,
            "filled_qty": abs_qty,
            "filled_avg_price": exit_price,
        }]

        try:
            realized_pl_dec = compute_realized_pl(
                close_legs=synth_legs,
                entry_price=Decimal(str(entry_price)),
                qty=int(abs_qty),
                spread_type=spread_type,
            )
        except PartialFillDetected as exc:
            # Internal synthesis should never trip this; if it does,
            # something is wrong with abs_qty/exit_price inputs.
            _write_exit_eval_critical_alert(
                supabase, position, user_id,
                stage="compute_realized_pl",
                reason=str(exc),
            )
            return {
                "order_id": order_id,
                "processed": 0,
                "routed_to": "internal_aborted",
                "note": f"compute_realized_pl failed: {str(exc)[:120]}",
            }

        mapped_reason = _map_close_reason(reason)
        if mapped_reason is None:
            _write_exit_eval_critical_alert(
                supabase, position, user_id,
                stage="map_close_reason",
                reason=f"Unknown exit reason {reason!r}; close aborted.",
            )
            return {
                "order_id": order_id,
                "processed": 0,
                "routed_to": "internal_aborted",
                "note": f"Unknown reason {reason!r}",
            }

        try:
            close_position_shared(
                supabase=supabase,
                position_id=position_id,
                realized_pl=realized_pl_dec,
                close_reason=mapped_reason,
                fill_source="exit_evaluator",
                closed_at=datetime.now(timezone.utc),
            )
        except PositionAlreadyClosed as exc:
            _write_exit_eval_critical_alert(
                supabase, position, user_id,
                stage="close_position_shared",
                reason=str(exc),
                extra_metadata={
                    "existing_close_reason": exc.existing_close_reason,
                    "existing_fill_source": exc.existing_fill_source,
                    "existing_closed_at": exc.existing_closed_at,
                },
            )
            return {
                "order_id": order_id,
                "processed": 0,
                "routed_to": "internal_aborted",
                "note": "PositionAlreadyClosed — race with another close handler",
            }

        return {
            "order_id": order_id,
            "processed": 1,
        }
