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
from datetime import date, datetime, timedelta, timezone
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
from packages.quantum.services.exit_geometry import (
    compute_spread_geometry,
    evaluate_geometry_rules,
)

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
    # entry_cost must be POSITION-scale to match unrealized_pl (which
    # paper_mark_to_market writes as avg_entry × abs(qty) × 100). max_credit
    # is PER-SPREAD, so scale by abs(quantity). Reduces to the old per-spread
    # value at qty=1. (2026-05-28: was 5× too tight on multi-contract positions.)
    entry_cost = abs(mc) * 100 * abs(float(pos.get("quantity") or 1))

    if _is_debit_spread(pos):
        # Debit spread: profit target = tp_pct of what we paid
        return upl >= entry_cost * tp_pct
    else:
        # Credit spread: profit target = tp_pct of credit received
        return mc > 0 and upl >= entry_cost * tp_pct


_STOP_LOSS_TIME_SCALING_ENABLED = os.environ.get(
    "EXIT_STOP_LOSS_TIME_SCALING_ENABLED", "0"
) == "1"
_STOP_LOSS_TIME_SCALING_FLOOR = float(
    os.environ.get("EXIT_STOP_LOSS_FLOOR_PCT", "0.30")
)


def _is_iron_condor(position: Dict[str, Any]) -> bool:
    """Strict iron-condor detection by strategy name. Used to exclude
    iron condors from stop-loss time-scaling (Q2 audit guardrail —
    AMZN/GOOGL iron_condor recoveries from <-50% loss)."""
    strategy = (position.get("strategy_key") or position.get("strategy") or "").upper()
    return "IRON_CONDOR" in strategy


def _close_limit_and_direction(exit_price, qty, n_legs):
    """(unsigned_limit, is_credit_close) for a close ticket.

    The Alpaca mleg limit is SIGNED at the broker boundary (positive = net
    debit, negative = net credit); internally requested_price / limit_price
    stay UNSIGNED and order_json.is_credit_close carries direction — the
    #101/#999 convention. build_alpaca_order_request applies the sign.

    Direction: a close inverts every leg, so its net direction is the
    inversion of the position's — qty > 0 (long, paid a debit to enter)
    closes for a credit; qty < 0 (short, received a credit) closes by paying
    a debit. Single-leg orders use unsigned limits (Alpaca infers direction
    from the leg side), so is_credit_close only applies to multi-leg.

    The signed close mark corroborates the leg math: compute_current_value
    sums the actual legs, so mark > 0 ⇒ selling the structure back nets a
    credit. Disagreement (e.g. the unsigned avg_entry_price fallback feeding
    a short structure) logs LOUD and the structural direction wins.

    06-11 incident: the signed mark (−1.39) was passed RAW as the limit on a
    short-condor force-close. Alpaca rejected the first submit (negative
    limit on a net-debit buy-back) and the retry RESTED at a price that can
    never fill — which satisfied the close-idempotency guards and disarmed
    the close path. The limit is now always the magnitude.
    """
    exit_price = float(exit_price or 0)
    is_credit_close = (float(qty or 0) > 0) and (n_legs >= 2)
    if exit_price != 0 and n_legs >= 2:
        mark_says_credit = exit_price > 0
        if mark_says_credit != is_credit_close:
            logger.warning(
                "[CLOSE_POSITION] close-direction disagreement: structural "
                "(qty=%s → is_credit_close=%s) vs signed mark (%s → "
                "mark_says_credit=%s). Using structural; check avg_entry/"
                "current_mark sign integrity on this position.",
                qty, is_credit_close, exit_price, mark_says_credit,
            )
    return abs(exit_price), is_credit_close


def _time_scaled_stop_loss_pct(pos: Dict, base_sl_pct: float) -> float:
    """
    DTE-aware stop-loss for DEBIT SPREADS only (audit/hold-period-asymmetry,
    2026-05-18). Symmetric to _time_scaled_target_profit_pct's sqrt-decay
    so theta-acceleration acts on both directions.

    At entry (dte/entry_dte=1.0): sl = base_sl_pct (unchanged from flat)
    At 50% elapsed:               sl ≈ 0.354
    At ≤20% elapsed:              sl = floor (default 0.30)

    Iron condors bypass and return base_sl_pct unchanged (caller is
    expected to gate on _is_iron_condor; this is defense-in-depth).
    Missing DTE data → returns base_sl_pct (no surprise tightening).
    """
    if _is_iron_condor(pos):
        return base_sl_pct
    dte = days_to_expiry(pos)
    entry_dte_raw = pos.get("entry_dte")
    entry_dte = entry_dte_raw if entry_dte_raw is not None else 35
    if entry_dte <= 0 or dte <= 0:
        return base_sl_pct
    dte_ratio = max(dte / entry_dte, 0.0)
    scaled = base_sl_pct * (dte_ratio ** 0.5)
    return max(_STOP_LOSS_TIME_SCALING_FLOOR, min(base_sl_pct, scaled))


def _check_stop_loss(pos: Dict, sl_pct: float = 2.0) -> bool:
    """Check if position has exceeded stop loss (debit-aware)."""
    mc = pos.get("max_credit")
    # ── FAIL-SAFE: a missing/zero max_credit must NOT silently disable the stop.
    # The legacy `return False` here was a SILENT fail-OPEN — a position whose
    # per-spread cost basis (max_credit) was null/0 lost ALL stop protection
    # with zero signal. Loss-protection is asymmetric (monitor #1035/#1036): the
    # stop side must never silently weaken. So we (1) log a LOUD data-fault
    # marker, then (2) recover a position-scale entry-cost basis from
    # avg_entry_price (same shape as the healthy max_credit basis) so a REAL
    # loss still triggers WITHOUT forcing a spurious close. Only if NO basis at
    # all is resolvable do we escalate: fire protectively iff there is a
    # confirmed loss (upl < 0) — never fabricate a basis (H9 both-ends), and
    # never silently clear the stop. The healthy (max_credit present) path below
    # is UNCHANGED.
    if mc is None or float(mc) == 0:
        upl = float(pos.get("unrealized_pl") or 0)
        qty = abs(float(pos.get("quantity") or 1))
        fallback_basis = abs(float(pos.get("avg_entry_price") or 0)) * 100 * qty
        logger.error(
            "[STOP_LOSS_DATA_FAULT] max_credit missing/zero on position %s "
            "(qty=%s upl=%s avg_entry=%s) — stop NOT silently disabled; "
            "fallback entry_cost=%s",
            pos.get("id") or pos.get("position_id"),
            pos.get("quantity"), upl, pos.get("avg_entry_price"), fallback_basis,
        )
        if fallback_basis > 0:
            # Conservative protective fallback: healthy formula shape, alternate
            # basis. Mirror the debit clamp; skip time-scaling on this degraded
            # path (no surprise loosening or tightening).
            effective_sl = (
                min(sl_pct, 1.0) if (_is_debit_spread(pos) and sl_pct > 1.0) else sl_pct
            )
            return upl <= -(fallback_basis * effective_sl)
        # No basis at all: cannot quantify the threshold. Do NOT clear the stop —
        # fire protectively iff there is a confirmed loss (upl < 0). A flat/up
        # position returns False, so this is never a spurious close.
        return upl < 0
    mc = float(mc)
    upl = float(pos.get("unrealized_pl") or 0)
    # entry_cost must be POSITION-scale to match unrealized_pl (see
    # _check_target_profit). max_credit is PER-SPREAD; scale by abs(quantity).
    # Reduces to old per-spread value at qty=1. (2026-05-28: was 5× too tight
    # on multi-contract positions — F 5ct had −$48 stop vs intended −$240.)
    entry_cost = abs(mc) * 100 * abs(float(pos.get("quantity") or 1))

    if _is_debit_spread(pos):
        # Debit spread: stop loss at sl_pct of entry cost (0.5 = lose half)
        # For debit spreads sl_pct is reinterpreted as fraction of entry cost
        # (default 2.0 → clamp to 1.0 since you can't lose more than you paid)
        effective_sl = min(sl_pct, 1.0) if sl_pct > 1.0 else sl_pct
        if _STOP_LOSS_TIME_SCALING_ENABLED and not _is_iron_condor(pos):
            # Symmetric to profit-target sqrt-decay. Gated default OFF;
            # iron_condor excluded (Q2 guardrail — AMZN/GOOGL recoveries
            # from <-50%). See docs/audit_hold_period_asymmetry.md.
            effective_sl = _time_scaled_stop_loss_pct(pos, effective_sl)
        return upl <= -(entry_cost * effective_sl)
    else:
        # Credit spread / iron_condor / other: flat threshold preserved.
        # Time-scaling intentionally excluded — Q2 (2026-05-18 audit)
        # showed iron_condor winners routinely recover from <-50% loss.
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
    # `pct`/`min_dte` carry the ACTUAL configured thresholds so the
    # EXIT_EVAL_DEBUG line can print the value the decision uses (06-15 fix:
    # it previously printed _DEFAULT_STOP_LOSS_PCT — 0.50 → −$80.50 — while
    # the cohort check used 0.30 → −$48.30, the "−54<=−80.5=False but fired"
    # confusion). Extra keys are inert in the condition loop.
    return {
        "target_profit": {
            "description": f"Position has reached {target_profit_pct:.0%} target profit",
            "check": lambda pos, tp=target_profit_pct: _check_target_profit(pos, tp),
            "pct": target_profit_pct,
        },
        "stop_loss": {
            "description": f"Position has exceeded {stop_loss_pct}x max loss",
            "check": lambda pos, sl=stop_loss_pct: _check_stop_loss(pos, sl),
            "pct": stop_loss_pct,
        },
        "dte_threshold": {
            "description": f"Position is within {min_dte_to_exit} DTE (gamma risk)",
            "check": lambda pos, dte_min=min_dte_to_exit: 0 < days_to_expiry(pos) <= dte_min,
            "min_dte": min_dte_to_exit,
        },
        "expiration_day": {
            "description": "Position expires today — must close",
            "check": lambda pos: days_to_expiry(pos) <= 0,
        },
    }


def is_gtc_profit_exit_order(order_row: Dict[str, Any]) -> bool:
    """True when the order row is a GTC resting profit-limit
    (services/gtc_profit_exit). Used by the close-idempotency guards in
    _close_position and intraday_risk_monitor._execute_force_close:
    a resting GTC profit order must NOT satisfy "a close already exists" —
    otherwise it would permanently disarm stop/envelope force-closes for
    the position (the guards match close-side orders in ANY status,
    including working/cancelled). A competing close instead proceeds and
    pre-cancels the resting GTC at the broker (submit_and_track's
    cancel_open_orders_for_symbols)."""
    oj = order_row.get("order_json") or {}
    return (
        oj.get("source_engine") == "gtc_profit_exit"
        or oj.get("order_class") == "intentional_resting_exit"
    )


# ── Close-retry re-arm (terminal-failed close attempts) ─────────────────────
# The 2026-05-18 BUG-C fix added 'cancelled' to the close-idempotency guards
# to stop the CSX retry-spam cascade (17 broker-terminal close failures,
# retried q15min). That overcorrected from infinite-retry to ZERO-RETRY-
# FOREVER: one close order terminating 'cancelled' at the broker (reject /
# expire / manual Alpaca-UI cancel all map to it) permanently satisfied
# "a close already exists", silently disarming EVERY automated exit for the
# position (stop, target, expiration, envelope force-close) — the loss then
# bounded only by defined-risk max. The only working retry path was an
# accident: the watchdog writes the different string 'watchdog_cancelled',
# absent from the guard lists (audit Area 2, 2026-06-09).
#
# Re-arm semantics: a 'cancelled' close blocks only while FRESH
# (CLOSE_REARM_WINDOW_MINUTES, default 30 — preserves the anti-spam intent)
# or while the retry budget is tripped (>= CLOSE_REARM_RETRY_BUDGET rows
# within CLOSE_REARM_BUDGET_WINDOW_HOURS → block + critical
# exit_protection_disarmed alert + backoff until rows age out). A STALE
# 'cancelled' row no longer blocks: protection RE-ARMS. 'filled', the
# active statuses, and 'needs_manual_review' block exactly as before
# (needs_manual_review now also alerts). Kill switch CLOSE_REARM_ENABLED,
# default ON (empty/unset → ON; the #1038 convention); explicit
# 0/false/no/off restores the legacy permanent block.

_TERMINAL_FAILED_STATUS = "cancelled"


def _close_rearm_enabled() -> bool:
    raw = os.environ.get("CLOSE_REARM_ENABLED", "")
    if not raw.strip():
        return True
    return raw.strip().lower() not in ("0", "false", "no", "off")


def _close_rearm_window_minutes() -> float:
    try:
        return float(os.environ.get("CLOSE_REARM_WINDOW_MINUTES", "30"))
    except ValueError:
        return 30.0


def _close_rearm_retry_budget() -> int:
    try:
        return int(os.environ.get("CLOSE_REARM_RETRY_BUDGET", "3"))
    except ValueError:
        return 3


def _close_rearm_budget_window_hours() -> float:
    try:
        return float(os.environ.get("CLOSE_REARM_BUDGET_WINDOW_HOURS", "4"))
    except ValueError:
        return 4.0


def _terminal_failed_time(row: Dict[str, Any]) -> Optional[datetime]:
    """When the close attempt failed: cancelled_at, else created_at.
    None when neither parses — the caller treats that row as FRESH
    (conservative: keeps blocking; never re-arms on data it can't read)."""
    for key in ("cancelled_at", "created_at"):
        raw = row.get(key)
        if not raw:
            continue
        try:
            ts = str(raw).replace("Z", "+00:00").replace(" ", "T", 1)
            parsed = datetime.fromisoformat(ts)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except (TypeError, ValueError):
            continue
    return None


# Per-(position, kind) alert throttle: 1/h. Process-local is acceptable —
# the guards run q15min, so even across recycles the worst case is one
# extra alert per recycle, not a spam loop.
_REARM_ALERT_LAST: Dict[str, float] = {}
_REARM_ALERT_THROTTLE_SECONDS = 3600.0


def _rearm_alert(supabase: Any, kind: str, position_id: Optional[str],
                 symbol: Optional[str], severity: str, message: str,
                 metadata: Dict[str, Any]) -> None:
    import time as _time
    key = f"{position_id or '?'}:{kind}"
    now_mono = _time.monotonic()
    last = _REARM_ALERT_LAST.get(key)
    if last is not None and (now_mono - last) < _REARM_ALERT_THROTTLE_SECONDS:
        return
    _REARM_ALERT_LAST[key] = now_mono
    try:
        from packages.quantum.observability.alerts import alert as _alert
        _alert(
            supabase,
            alert_type=kind,
            severity=severity,
            message=message,
            position_id=position_id,
            symbol=symbol,
            metadata=metadata,
        )
    except Exception as alert_err:
        logger.warning(f"[CLOSE_REARM] alert write failed: {alert_err}")


def _select_internal_fill_price(
    position: Dict[str, Any], exit_price_mid: float, snapshot_fn=None
) -> tuple:
    """#1017-class fix (06-12): internal/shadow fills price at the
    EXECUTABLE side (long→sell at bid, short→buy at ask), via the same
    computation the #1034 gate corroborates with — never the optimistic mid,
    which overstates exactly when spreads blow out (06-12 NFLX x3: mid
    booked +$314.70 vs achievable +$133.35).

    Returns (price, fill_quality). Fail-soft by contract: ANY failure falls
    back to the mid with an explicit quality flag — this function can never
    abort a close. fill_quality values:
      executable               — all legs two-sided; price is the achievable close
      executable_partial_quote — executable sides present, but some leg's
                                 non-executable side missing (estimate still
                                 honest; flagged for learning weighting)
      mid_fallback_quote_missing — an executable side was missing → mid used
      mid_fallback_error         — quote fetch/computation failed → mid used
    """
    try:
        from packages.quantum.analytics import exit_mark_corroboration as _emc
        est = _emc.executable_close_estimate(position, snapshot_fn=snapshot_fn)
        ach = est.get("achievable_close")
        if ach is not None:
            quality = (
                "executable" if est.get("quote_complete")
                else "executable_partial_quote"
            )
            return float(ach), quality
        return float(exit_price_mid), "mid_fallback_quote_missing"
    except Exception as e:
        logger.warning(
            f"[INTERNAL_FILL] executable-side pricing failed "
            f"(mid fallback, flagged): {e}"
        )
        return float(exit_price_mid), "mid_fallback_error"


# ── Close-side stage-time executable-quote validation (CLOSE_QUOTE_VALIDATION,
#    Phase 2) ──────────────────────────────────────────────────────────────
# Entry (#1038/#1052) validates each leg is executable at stage time and HARD-
# REJECTS; closes are intentionally EXEMPT there (being trapped is worse than a
# bad close mark). This is the close-specific equivalent: corroborate the LIVE
# close limit on the EXECUTABLE side and DEFER (re-eval next cycle) instead of
# staging a mark the broker rejects/rests (the 06-15 degenerate-stage class).
# Internal/shadow fills already price executable at fill (#1017) → NOT gated
# here. Reuses executable_close_estimate (the #1034 seam) — one shared
# "executable" definition. Default-ON; CLOSE_QUOTE_VALIDATION_ENABLED=0 reverts
# to the legacy mark-limit close.

def _close_quote_validation_enabled() -> bool:
    """CLOSE_QUOTE_VALIDATION_ENABLED — default ON (empty/unset → ON; only an
    explicit 0/false/no/off reverts to the legacy mark-limit close). Mirrors
    ENTRY_QUOTE_VALIDATION_ENABLED's polarity."""
    raw = os.environ.get("CLOSE_QUOTE_VALIDATION_ENABLED", "")
    if not raw.strip():
        return True
    return raw.strip().lower() not in ("0", "false", "no", "off")


def _close_stuck_escalate_cycles(is_stop: bool) -> int:
    """Consecutive uncorroborated-defer cycles before escalating to a critical
    stuck-can't-exit alert. STOPS escalate faster than TPs (a deferred stop is a
    needed exit; a deferred TP only forgoes a profit-take). Env-tunable."""
    if is_stop:
        try:
            return int(os.environ.get("CLOSE_STUCK_ESCALATE_STOP_CYCLES", "2"))
        except ValueError:
            return 2
    try:
        return int(os.environ.get("CLOSE_STUCK_ESCALATE_TP_CYCLES", "4"))
    except ValueError:
        return 4


def _corroborate_close_stage(position: Dict[str, Any], exit_price_mid: float,
                             snapshot_fn=None) -> tuple:
    """Executable corroboration for a LIVE close limit. Returns one of:
      ("stage_executable", executable_price, quality) — achievable_close priced;
          stage the live limit at this value (not the optimistic mid).
      ("defer", reason)   — a leg's executable side is missing/dark (the 06-15
          class); caller must HOLD the position (do not stage).
      ("stage_mark", reason) — transient estimate error → fall back to the mark
          limit (legacy); a flaky quote must NOT strand a needed exit.
    NEVER raises."""
    try:
        from packages.quantum.analytics import exit_mark_corroboration as _emc
        est = _emc.executable_close_estimate(position, snapshot_fn=snapshot_fn)
        ach = est.get("achievable_close")
        if ach is not None:
            quality = ("executable" if est.get("quote_complete")
                       else "executable_partial_quote")
            return ("stage_executable", float(ach), quality)
        return ("defer", "executable_side_missing")
    except Exception as e:
        logger.warning(
            f"[CLOSE_STAGE] executable corroboration errored "
            f"(mark-limit fallback, flagged): {e}"
        )
        return ("stage_mark", f"estimate_error:{type(e).__name__}")


def _handle_close_stage_defer(supabase: Any, position_id: str,
                              symbol: Optional[str], reason: str,
                              user_id: Optional[str]) -> Dict[str, Any]:
    """Emit the per-cycle close_stage_uncorroborated flag, escalate to a critical
    close_stuck_uncorroborated once this position has deferred >= the (reason-
    aware) cycle threshold within the re-arm budget window, and return the DEFER
    result. NEVER raises — a flag/escalation failure must not break the exit
    loop, and the position simply stays held for the next cycle."""
    is_stop = "target_profit" not in (reason or "").lower()
    threshold = _close_stuck_escalate_cycles(is_stop)
    # Count PRIOR defers (strictly before this cycle) so (prior+1) == this cycle.
    prior = 0
    try:
        since = (
            datetime.now(timezone.utc)
            - timedelta(hours=_close_rearm_budget_window_hours())
        ).isoformat()
        cnt = supabase.table("risk_alerts").select("id", count="exact") \
            .eq("alert_type", "close_stage_uncorroborated") \
            .eq("position_id", position_id) \
            .gte("created_at", since) \
            .execute()
        _cnt = getattr(cnt, "count", None)
        if isinstance(_cnt, int):
            prior = _cnt
        else:
            _data = getattr(cnt, "data", None)
            prior = len(_data) if isinstance(_data, list) else 0
    except Exception as e:
        logger.warning(f"[CLOSE_STAGE] defer-count query failed: {e}")
    # Per-cycle visibility (the close runs ~once/cycle/position → cycle-cadence,
    # not spam). Loud by design: a held exit must be visible.
    try:
        from packages.quantum.observability.alerts import alert as _alert
        _alert(
            supabase,
            alert_type="close_stage_uncorroborated",
            severity="warning",
            message=(
                f"Close DEFERRED for {symbol or position_id}: executable side not "
                f"corroborated (leg dark/unpriceable) — position HELD, re-eval next "
                f"cycle (reason={reason})"
            ),
            position_id=position_id,
            symbol=symbol,
            metadata={
                "position_id": position_id, "reason": reason, "is_stop": is_stop,
                "function_name": "_close_position.close_stage_gate",
            },
        )
    except Exception as e:
        logger.warning(f"[CLOSE_STAGE] defer-flag write failed: {e}")
    if (prior + 1) >= threshold:
        _rearm_alert(
            supabase, "close_stuck_uncorroborated", position_id, symbol, "critical",
            (
                f"{symbol or position_id}: automated close uncorroborated for "
                f">= {threshold} cycle(s) (reason={reason}, is_stop={is_stop}) — "
                f"exit BLOCKED on dark/unpriceable legs; position HELD and "
                f"protection degraded. Manual review: confirm the chain is quotable "
                f"or close manually."
            ),
            {
                "position_id": position_id, "consecutive_defers": prior + 1,
                "threshold": threshold, "is_stop": is_stop, "reason": reason,
            },
        )
    return {
        "order_id": None,
        "processed": 0,
        "routed_to": "deferred_uncorroborated",
        "note": (
            f"Close deferred — {symbol or position_id} executable side not "
            f"corroborated; position held, re-eval next cycle"
        ),
    }


def filter_blocking_close_orders(
    rows: List[Dict[str, Any]],
    *,
    supabase: Any = None,
    position_id: Optional[str] = None,
    symbol: Optional[str] = None,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Close-side order rows that legitimately block a new close attempt.

    Excludes GTC resting profit-limits (is_gtc_profit_exit_order) and —
    under the re-arm semantics above — STALE terminal-failed ('cancelled')
    attempts, so a broker-rejected or manually-cancelled close cannot
    permanently disarm the position's automated exits. Active statuses,
    'filled', and 'needs_manual_review' block as before.
    """
    candidates = [r for r in (rows or []) if not is_gtc_profit_exit_order(r)]
    if not _close_rearm_enabled():
        return candidates  # legacy: every status in the query list blocks

    blocking: List[Dict[str, Any]] = []
    terminal_failed: List[Dict[str, Any]] = []
    for r in candidates:
        if (r.get("status") or "") == _TERMINAL_FAILED_STATUS:
            terminal_failed.append(r)
        else:
            blocking.append(r)
            if (r.get("status") or "") == "needs_manual_review":
                _rearm_alert(
                    supabase, "close_blocked_needs_manual_review",
                    position_id, symbol, "warning",
                    f"Automated exits for {symbol or position_id or '?'} are "
                    f"blocked by a needs_manual_review close order "
                    f"{str(r.get('id'))[:8]} — operator attention required",
                    {"order_id": r.get("id"), "position_id": position_id},
                )

    if not terminal_failed:
        return blocking

    now = now or datetime.now(timezone.utc)
    window = timedelta(minutes=_close_rearm_window_minutes())
    budget_window = timedelta(hours=_close_rearm_budget_window_hours())
    budget = _close_rearm_retry_budget()

    fresh: List[Dict[str, Any]] = []
    in_budget_window: List[Dict[str, Any]] = []
    for r in terminal_failed:
        failed_at = _terminal_failed_time(r)
        if failed_at is None:
            # Unreadable timestamp → treat as fresh (block). Conservative:
            # preserves anti-spam; created_at is NOT NULL so this is rare.
            logger.error(
                f"[CLOSE_REARM] cancelled close order {str(r.get('id'))[:8]} "
                f"has no parseable timestamp — treating as fresh (blocking)"
            )
            fresh.append(r)
            in_budget_window.append(r)
            continue
        age = now - failed_at
        if age <= window:
            fresh.append(r)
        if age <= budget_window:
            in_budget_window.append(r)

    if len(in_budget_window) >= budget:
        # Retry budget tripped: the broker (or operator) is repeatedly
        # killing our closes. Keep blocking (backoff until rows age past
        # the budget window) and say so LOUDLY — this is the disarm STATE
        # the old code never alerted.
        blocking.extend(terminal_failed)
        logger.critical(
            f"[CLOSE_REARM] {symbol or position_id or '?'}: "
            f"{len(in_budget_window)} terminal-failed close attempts within "
            f"{_close_rearm_budget_window_hours():.0f}h (budget {budget}) — "
            f"close retries SUSPENDED until attempts age out"
        )
        _rearm_alert(
            supabase, "exit_protection_disarmed", position_id, symbol,
            "critical",
            f"{symbol or position_id or '?'}: {len(in_budget_window)} "
            f"terminal-failed close attempts in "
            f"{_close_rearm_budget_window_hours():.0f}h — automated close "
            f"retries suspended (backoff); broker/manual interference likely. "
            f"Position protection is degraded until retries re-arm.",
            {
                "position_id": position_id,
                "terminal_failed_count": len(in_budget_window),
                "budget": budget,
                "budget_window_hours": _close_rearm_budget_window_hours(),
            },
        )
    elif fresh:
        # Inside the anti-spam window — defer, will re-arm shortly.
        blocking.extend(fresh)
        logger.warning(
            f"[CLOSE_REARM] {symbol or position_id or '?'}: close attempt "
            f"deferred — {len(fresh)} fresh terminal-failed close order(s) "
            f"within {_close_rearm_window_minutes():.0f}min; retry re-arms "
            f"when they age out"
        )
    else:
        # Only STALE terminal-failed rows: RE-ARM. Under the pre-fix
        # semantics these would have blocked forever (the CSX -$161 class).
        logger.warning(
            f"[CLOSE_REARM] {symbol or position_id or '?'}: re-arming "
            f"automated exits — ignoring {len(terminal_failed)} stale "
            f"terminal-failed close attempt(s) that would previously have "
            f"blocked forever"
        )

    return blocking


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

    # Log threshold computations if max_credit is available.
    # 06-15 honesty fix: read the ACTUAL pcts the active conditions use (the
    # cohort-built `pct` keys), NOT _DEFAULT_*. The debug line previously
    # printed the default 0.50 stop while the cohort check ran 0.30, so it
    # showed "−54 <= −80.50 = False" while the real decision (−54 <= −48.30)
    # fired True — the §8 EXIT_EVAL_DEBUG known-liar. Now the printed
    # threshold equals the threshold the decision computes through.
    _active_tp = conditions.get("target_profit", {}).get("pct", _DEFAULT_TARGET_PROFIT_PCT)
    _active_sl = conditions.get("stop_loss", {}).get("pct", _DEFAULT_STOP_LOSS_PCT)
    _active_dte = conditions.get("dte_threshold", {}).get("min_dte", _DEFAULT_MIN_DTE_TO_EXIT)

    is_debit = _is_debit_spread(position)
    if max_credit is not None:
        try:
            mc = float(max_credit)
            upl = float(unrealized_pl or 0)
            # Position-scale to match the decision functions + unrealized_pl
            # (max_credit is per-spread; × abs(qty)). Keeps this DEBUG line
            # consistent with _check_target_profit / _check_stop_loss.
            entry_cost = abs(mc) * 100 * abs(float(qty or 1))
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
                f"dte_threshold: 0 < {dte} <= {_active_dte} ? {0 < dte <= _active_dte} | "
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
        # Per-position exit-trigger corroboration (#1035/#1036): evaluate stop/TP
        # against the EXECUTABLE-corroborated mark (long→bid, short→ask), not the
        # raw persisted `unrealized_pl`, which on an incomplete-leg-quote window
        # is a leg-skew phantom (06-17 MARA: raw −285 vs executable −15). Fail-
        # SAFE: a position whose executable side can't be priced keeps its RAW
        # mark + current fire-if-past behavior (NEVER a suppressor; worst case =
        # today's stop), exactly as #1071's brake fell back to the legacy basis.
        positions = self._corroborate_positions_for_exit(positions)
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
        # D6 Phase 1: (position, actual premium-% decision) captured for the
        # OBSERVATION-ONLY shadow geometry harness, logged AFTER closes/holds are
        # finalized so it cannot influence the real exit decision.
        shadow_inputs: List[tuple] = []

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
                # WARNING deliberately: positive confirmation that cohort
                # thresholds (not defaults) govern this pass must be visible
                # at the worker's WARNING+ log level (06-10 A2 diagnostic).
                logger.warning(
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

            # Structural mark-validity clamp (06-15): an IMPOSSIBLE composed
            # mark (|mark| > wing width OR implied loss > max structural loss)
            # must never reach an exit condition on this path either. Skip the
            # eval (hold; retry next cycle), loud [STRUCT_CLAMP]. NEVER
            # suppresses a real stop — only rejects geometrically impossible
            # marks (the stop-side analogue of the #1034 guard).
            try:
                from packages.quantum.risk.mark_validity import validate_structure_mark
                _clamp_ok, _clamp_reason, _clamp_detail = validate_structure_mark(position)
            except Exception:
                _clamp_ok, _clamp_reason, _clamp_detail = True, "unvalidatable", {}
            if not _clamp_ok:
                logger.critical(
                    "[STRUCT_CLAMP] %s (%s) impossible mark rejected (%s): %s "
                    "— held this cycle, not acted on",
                    position.get("symbol"), str(position.get("id"))[:8],
                    _clamp_reason, _clamp_detail,
                )
                holds.append(position)
                shadow_inputs.append((position, None))
                continue

            triggered = evaluate_position_exit(position, conditions=pos_conditions)
            active_conditions = pos_conditions or EXIT_CONDITIONS
            shadow_inputs.append((position, triggered))
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

        # D6 Phase 1: OBSERVATION-ONLY shadow geometry harness. Runs AFTER the
        # closes/holds partition is finalized above, so it is structurally
        # incapable of altering the real exit decision — it only reads positions
        # and writes shadow_exit_decisions rows. Fail-soft: a harness error must
        # never break exit evaluation (observability must not undo primary work).
        try:
            self._persist_shadow_exit_decisions(user_id, shadow_inputs)
        except Exception as e:
            logger.warning(f"[SHADOW_EXIT] harness failed (non-fatal): {e}")

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

    def _persist_shadow_exit_decisions(self, user_id: str, shadow_inputs: List[tuple]) -> None:
        """D6 Phase 1 — OBSERVATION-ONLY shadow geometry harness.

        For each open position at this evaluation, log what each candidate
        geometry rule (R1-R4) WOULD decide alongside the premium-% champion's
        ACTUAL decision, to ``shadow_exit_decisions``. Has NO write path to the
        real exit/close — it only reads positions and inserts shadow rows. The
        real exit was already determined (premium-% logic) before this runs.

        Fail-soft per row + per cycle: any error is swallowed (observability must
        not undo primary work). Underlying spot is fetched best-effort; on miss,
        the row is still written with spot=None and rules recorded n/a.
        """
        if not shadow_inputs:
            return

        # Fetch live underlying spot for each position's ticker (best-effort,
        # same MarketDataTruthLayer path marks use). Batch the distinct tickers.
        spot_by_symbol: Dict[str, Optional[float]] = {}
        try:
            from packages.quantum.services.market_data_truth_layer import MarketDataTruthLayer
            truth_layer = MarketDataTruthLayer()
            symbols = sorted({
                (pos.get("symbol") or "").upper()
                for pos, _ in shadow_inputs if pos.get("symbol")
            })
            if symbols:
                snaps = truth_layer.snapshot_many(symbols)
                from packages.quantum.services.cache_key_builder import normalize_symbol
                for sym in symbols:
                    snap = snaps.get(normalize_symbol(sym)) or snaps.get(sym) or {}
                    q = snap.get("quote", snap) if isinstance(snap, dict) else {}
                    bid = float(q.get("bid") or 0)
                    ask = float(q.get("ask") or 0)
                    mid = (bid + ask) / 2.0 if (bid > 0 and ask > 0) else float(q.get("mid") or 0)
                    spot_by_symbol[sym] = mid if mid > 0 else None
        except Exception as e:
            logger.warning(f"[SHADOW_EXIT] underlying spot fetch failed (non-fatal): {e}")

        rows: List[Dict[str, Any]] = []
        for pos, triggered in shadow_inputs:
            try:
                sym = (pos.get("symbol") or "").upper()
                spot = spot_by_symbol.get(sym)
                dte = days_to_expiry(pos)
                geometry = compute_spread_geometry(pos, spot, dte)
                rule_decisions = evaluate_geometry_rules(geometry)
                rows.append({
                    "user_id": user_id or pos.get("user_id"),
                    "position_id": pos.get("id"),
                    "symbol": pos.get("symbol"),
                    "underlying_spot": spot,
                    "dte": dte,
                    "structure": geometry.get("structure", "n/a"),
                    "geometry": geometry,
                    "premium_pct_decision": triggered or "hold",
                    "geometry_decisions": rule_decisions,
                })
            except Exception as e:
                logger.warning(f"[SHADOW_EXIT] row build failed for {pos.get('id')} (non-fatal): {e}")

        if not rows:
            return
        try:
            self.client.table("shadow_exit_decisions").insert(rows).execute()
            logger.info(f"[SHADOW_EXIT] logged {len(rows)} shadow exit decision row(s)")
        except Exception as e:
            logger.warning(f"[SHADOW_EXIT] persist failed (non-fatal): {e}")

    def _corroborate_positions_for_exit(
        self, positions: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Return ``positions`` with ``unrealized_pl`` replaced by the executable-
        corroborated decision P&L (#1035/#1036), so the stop/TP triggers fire on
        the position's TRUE value, not a raw persisted phantom. Per-position
        FAIL-SAFE: an uncorroborable position keeps its RAW mark (fire-if-past) —
        never suppressed. One shared truth-layer snapshot source across the batch
        (60s TTL); every raw-fallback is logged so the fallback is never silent."""
        if not positions:
            return positions
        from packages.quantum.analytics import exit_mark_corroboration as _emc
        _snap = None
        try:
            from packages.quantum.services.market_data_truth_layer import (
                MarketDataTruthLayer,
            )
            _snap = MarketDataTruthLayer().snapshot_many
        except Exception:
            _snap = None  # corroborated_exit_upl self-creates per call / raw-falls back
        out: List[Dict[str, Any]] = []
        for p in positions:
            upl, basis = _emc.corroborated_exit_upl(p, snapshot_fn=_snap)
            if basis == "corroborated":
                logger.info(
                    "[EXIT_CORROBORATE] %s (%s): corroborated upl=%s (raw was %s)",
                    p.get("symbol"), str(p.get("id"))[:8], upl, p.get("unrealized_pl"),
                )
            else:
                logger.info(
                    "[EXIT_CORROBORATE] %s (%s): RAW-FALLBACK (%s) — stop/TP "
                    "evaluates on the raw mark upl=%s, fire-if-past (never suppressed)",
                    p.get("symbol"), str(p.get("id"))[:8], basis, upl,
                )
            out.append({**p, "unrealized_pl": upl})
        return out

    def _get_open_positions(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all open paper positions for a user."""
        try:
            # Paper-shadow isolation (additive, no-op when off): exclude the
            # paper-shadow executor's portfolios so the live evaluator never
            # evaluates/closes its observation positions. Extends the existing
            # shadow_only exclusion precedent (see services/paper_shadow_isolation.py
            # PAPER_SHADOW_ROUTING_MODE). When no paper_shadow portfolios exist
            # (always, pre-Phase-1b), .neq matches all rows → identical result.
            port_res = self.client.table("paper_portfolios") \
                .select("id") \
                .eq("user_id", user_id) \
                .neq("routing_mode", "paper_shadow") \
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

        # Fallback: currently-promoted champion cohort for positions
        # on the default portfolio.
        #
        # #62a-D1 (closed 2026-05-18): pre-PR this queried
        # `is_champion = True` — a non-existent column. Always raised,
        # always contributed to _resolution_failures, never returned a
        # cohort. Rewritten to use the `promoted_at` lookup that
        # `policy_lab_evaluator` writes. See champion.py for the
        # symmetric helper used by fork.py. We keep the inline query
        # here rather than calling the helper because path 3's
        # exception goes into `_resolution_failures` for the aggregate
        # `paper_exit_cohort_resolve_exhausted` alert — the helper's
        # log-and-return-fallback shape doesn't fit that contract.
        if user_id:
            try:
                res = self.client.table("policy_lab_cohorts") \
                    .select("cohort_name") \
                    .eq("user_id", user_id) \
                    .eq("is_active", True) \
                    .not_.is_("promoted_at", "null") \
                    .order("promoted_at", desc=True) \
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
        exit_price_override: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Close a single position using the position's current_mark as exit price.

        exit_price_override (optional): the EXACT mark the caller's decision
        used. The 15-min intraday monitor evaluates KEEP/CLOSE on fresh
        in-memory marks (_refresh_marks) that are never persisted, while this
        function re-reads the DB row — so without the override the close
        limit staged from a mark up to ~6.5h stale (evaluate-fresh /
        execute-stale, 2026-06-04: BAC detected >=+$255 on the fresh mark,
        closed at the stale $3.03 -> +$192; loss-side worse — a stop/envelope
        close staged ABOVE a falling market rests unfilled, watchdog-cancels,
        and re-stages at the SAME stale mark until the next persisting job).
        Passing the decision's mark makes decision-price == order-price by
        construction. Default None = byte-identical legacy behavior (DB
        current_mark) for every other caller, incl. the scheduled evaluator
        (which persists-then-reads and is already coherent).
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
            # P0-A FAIL-CLOSED (2026-07-10, F-A2-1 / E6): a routing-query failure
            # must NEVER default a LIVE position to the internal-fill route (the
            # prior `position_is_alpaca=False` was fail-WRONG — it internally
            # filled a live close on a lookup error). Treat unknown routing as
            # ALPACA; the authoritative should_submit_to_broker portfolio gate
            # downstream makes the real live/shadow decision (a paper portfolio
            # still routes to shadow_blocked→internal correctly). A live position
            # can no longer be internally filled on a query failure.
            position_is_alpaca = True
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
                    "consequence": "P0-A fail-closed: routed to the broker-submit gate (never defaulted to internal fill); portfolio routing_mode makes the real decision.",
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

        # ── Fetch position ───────────────────────────────────────────
        # Moved ahead of the idempotency check (2026-05-18 BUG-C fix) so
        # downstream guards can branch on observed position state, and
        # the idempotency lookup can be scoped to the close side.
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

        # ── BUG-C / H9 doctrine: refuse to close an already-closed pos ─
        # H9 (verified-write across wrapper chains) — Anti-pattern from
        # 2026-05-18 CSX cycle: the violation loop in
        # intraday_risk_monitor called _execute_force_close 5 times on
        # the same position; the first call succeeded and closed the
        # position; the next 4 punched through the upstream idempotency
        # check (because internal-paper close orders fill synchronously,
        # so the prior close was already 'filled' — not in the pre-fix
        # status list) and reached this function. Pre-fix _close_position
        # had no `status='closed'` guard, so it proceeded to fetch the
        # position, observe quantity=0, and crash inside compute_realized_pl
        # ("qty must be positive, got 0"). Each crash wrote a critical
        # alert. The position was already closed; the caller is operating
        # on stale state; the right behavior is to short-circuit and
        # surface that fact, not raise.
        #
        # This is a verified-state check: we read the position from the
        # DB and branch on observed state. We do NOT trust the caller's
        # implicit assumption that "this function only gets called when
        # the position is open". The caller may be wrong, and this is
        # the function that bears responsibility for refusing to operate
        # on closed state.
        pos_status = (position.get("status") or "").lower()
        if pos_status == "closed" or qty == 0:
            logger.info(
                f"[CLOSE_POSITION] Skipping — position already closed "
                f"for position={position_id[:8]} status={pos_status!r} "
                f"qty={qty}"
            )
            return {
                "order_id": None,
                "processed": 0,
                "routed_to": "already_closed",
                "note": (
                    f"Position {position_id[:8]} status={pos_status!r} "
                    f"qty={qty} — no action taken"
                ),
            }

        # ── Idempotency: block if a close order already exists ──────
        # Check ALL non-terminal statuses including needs_manual_review.
        # Without this, every caller (_execute_force_close, evaluate_exits)
        # creates a new staged order on each invocation, causing 100+ orders
        # to pile up when submission repeatedly fails (e.g. held_for_orders).
        #
        # 2026-05-18 BUG-C fix: 'filled' and 'cancelled' MUST be in the
        # filter, AND the lookup must be scoped to the CLOSE side
        # (sell-to-close for long, buy-to-close for short) so the entry
        # order — which shares position_id and ends in status='filled' —
        # does not match. Pre-fix list omitted 'filled', so when the
        # first internal-paper close order filled synchronously, the
        # next invocation of this function punched straight through the
        # guard and staged a duplicate zero-qty close order.
        try:
            existing_close = supabase.table("paper_orders") \
                .select("id, status, created_at, cancelled_at, order_json") \
                .eq("position_id", position_id) \
                .eq("side", side) \
                .in_("status", [
                    "staged", "submitted", "working", "partial", "pending",
                    "needs_manual_review", "filled", "cancelled",
                ]) \
                .order("created_at", desc=True) \
                .limit(10) \
                .execute()
            # GTC resting profit-limits do NOT block a competing close —
            # excluding them here is what lets a stop/envelope force-close
            # proceed (and pre-cancel the resting GTC at the broker) instead
            # of being deduped into never firing. See is_gtc_profit_exit_order.
            # STALE terminal-failed ('cancelled') attempts no longer block
            # either — the close-retry re-arm semantics (see the helper).
            _blocking = filter_blocking_close_orders(
                existing_close.data or [],
                supabase=supabase,
                position_id=position_id,
            )
            if _blocking:
                existing = _blocking[0]
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

            # ── Resting-TP ownership (06-12): the GTC profit-limit OWNS the
            # profit side. A target_profit close staged while an intentional
            # resting exit is live at the broker would be a SECOND submitter
            # for the same intent — the 06-11/06-12 double-submit class.
            # Profit-side closes defer to the resting order; stop/envelope
            # closes proceed unchanged (submit_and_track's pre-cancel removes
            # the resting GTC before the protective close submits).
            if _map_close_reason(reason) == "target_profit_hit":
                _resting_live = [
                    r for r in (existing_close.data or [])
                    if is_gtc_profit_exit_order(r)
                    and (r.get("status") or "") in (
                        "staged", "submitted", "working", "partial", "pending",
                    )
                ]
                if _resting_live:
                    _r0 = _resting_live[0]
                    logger.info(
                        f"[CLOSE_POSITION] Skipping target_profit close for "
                        f"position={position_id[:8]} — resting TP "
                        f"{str(_r0.get('id'))[:8]} (status={_r0.get('status')}) "
                        f"owns the profit side"
                    )
                    return {
                        "order_id": _r0.get("id"),
                        "processed": 0,
                        "routed_to": "skipped_resting_tp_owns_profit_side",
                        "note": (
                            f"Resting TP {str(_r0.get('id'))[:8]} owns the "
                            f"profit side; no second submitter"
                        ),
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

        # Exit price: the caller's decision mark when provided (intraday
        # monitor — see docstring), else the persisted DB mark (legacy,
        # byte-identical for all other callers).
        if exit_price_override is not None:
            exit_price = float(exit_price_override)
            logger.info(
                f"[CLOSE_POSITION] position={position_id[:8]} using caller's "
                f"decision mark {exit_price} (DB current_mark="
                f"{position.get('current_mark')})"
            )
        else:
            exit_price = float(position.get("current_mark") or position.get("avg_entry_price") or 0)
        entry_price = float(position.get("avg_entry_price") or 0)

        # ── CLOSE_FILL_GAP instrumentation (ADDITIVE, observe-only) ───
        # Capture the triggering mark (mid) and the full-cross executable
        # estimate (cross) at STAGE time so the fill point can record the
        # slippage gap (Phase-3 precursor). These NEVER affect any close
        # decision — they are stamped onto order_json and read back at fill.
        # Default None: an internal/shadow close or a non-corroborated stage
        # simply logs fill-only (gap_fraction=NA) downstream.
        _cfg_mid: Optional[float] = None
        _cfg_cross: Optional[float] = None

        # ── CLOSE_QUOTE_VALIDATION (Phase 2, default-ON) ──────────────
        # Corroborate the LIVE close limit on the EXECUTABLE side BEFORE
        # staging — and BEFORE submit_and_track's resting-order pre-cancel
        # below — so a DEFER can never strand a naked position (refinement 2:
        # the only pre-cancel is inside submit_and_track, which a defer never
        # reaches). Live only: internal/shadow fills already price executable
        # at fill (#1017), so they are NOT gated here (shadow path unchanged).
        # Corroborated → stage the live limit at achievable_close (kills the
        # 06-15 degenerate-stage class, aligns live PRICING to the executable
        # basis). Dark leg → DEFER (hold + flag + re-eval; escalate if stuck).
        # Transient estimate error → mark-limit fallback (legacy; never strand
        # a needed exit on a flaky quote). Harmonizes with the clamp / Stage-2
        # / #1062 / #1017 — this is the missing STAGE-time live-limit layer.
        if position_is_alpaca and _close_quote_validation_enabled():
            _live_submit = os.environ.get("ALPACA_DRY_RUN", "0") != "1"
            if _live_submit:
                try:
                    from packages.quantum.brokers.execution_router import (
                        should_submit_to_broker,
                    )
                    _live_submit = should_submit_to_broker(
                        position["portfolio_id"], supabase
                    )
                except Exception:
                    _live_submit = True  # fail toward validating the live path
            if _live_submit:
                _decision, _cval, *_q = _corroborate_close_stage(position, exit_price)
                # CLOSE_FILL_GAP: the value handed to corroboration IS the
                # trigger mark (mid); _cval (on stage_executable) IS the
                # full-cross executable estimate (cross). Capture both before
                # exit_price is repriced below. Observe-only.
                _cfg_mid = exit_price
                if _decision == "defer":
                    logger.warning(
                        f"[CLOSE_STAGE] DEFER live close for "
                        f"{position.get('symbol')} ({position_id[:8]}): executable "
                        f"side not corroborated ({_cval}); holding position, "
                        f"re-eval next cycle (reason={reason})"
                    )
                    return _handle_close_stage_defer(
                        supabase, position_id, position.get("symbol"),
                        reason, user_id,
                    )
                if _decision == "stage_executable":
                    logger.warning(
                        f"[CLOSE_STAGE] live close limit repriced to executable "
                        f"for {position.get('symbol')} ({position_id[:8]}): "
                        f"mark={exit_price} → executable={round(_cval, 4)} "
                        f"(quality={_q[0] if _q else '?'})"
                    )
                    _cfg_cross = _cval  # CLOSE_FILL_GAP: full-cross estimate
                    exit_price = _cval
                # "stage_mark": transient error → keep the mark limit (legacy),
                # already warned inside _corroborate_close_stage.

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

        # Limit magnitude + direction via _close_limit_and_direction: the
        # ticket's limit stays UNSIGNED (the 06-11 short-condor close passed
        # the signed mark −1.39 raw and rested unfillable); is_credit_close
        # carries direction and build_alpaca_order_request signs at the
        # broker boundary.
        close_limit, is_credit_close = _close_limit_and_direction(
            exit_price, qty, len(close_legs)
        )

        ticket = TradeTicket(
            symbol=position["symbol"],
            quantity=abs_qty,
            order_type="limit",
            limit_price=round(close_limit, 2),
            strategy_type="custom",
            source_engine="paper_exit_evaluator",
            legs=close_legs,
            is_credit_close=is_credit_close,
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
                # Single-submitter rule (06-12): THIS function owns broker
                # submission for closes (the explicit submit_and_track below,
                # with its pre-cancel semantics). Staging must not also
                # submit — that was the double-submission bug
                # (docs/double_submit_close_trace.md): two broker orders per
                # live close; #2's pre-cancel killed #1 (06-11), or #2 was
                # intent-mismatch-rejected after #1 FILLED (06-12 SPY).
                submit_to_broker=False,
            )
        finally:
            os.environ["EXECUTION_MODE"] = _saved_mode

        # ── CLOSE_FILL_GAP: thread stage-time cross/mid onto the close
        # order's EXISTING order_json (no migration) so the LIVE fill /
        # reconcile point can read them back and log the slippage gap.
        # Best-effort; never affects the close. The internal-fill path below
        # reads these from locals + folds them into its own order_json write.
        if _cfg_cross is not None or _cfg_mid is not None:
            try:
                from packages.quantum.services.close_fill_gap import (
                    stamp_order_json as _cfg_stamp,
                )
                _cfg_stamp(supabase, order_id, _cfg_cross, _cfg_mid)
            except Exception as _cfg_e:
                logger.warning(f"[CLOSE_FILL_GAP] stage stamp failed: {_cfg_e}")

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
                    # PR2a: mark routing decision (preserved through fill —
                    # _commit_fill only writes filled-state fields, not
                    # execution_mode).
                    supabase.table("paper_orders") \
                        .update({"execution_mode": "shadow_blocked"}) \
                        .eq("id", order_id) \
                        .execute()
                    logger.info(
                        f"[ROUTING] Blocked Alpaca close for shadow_only portfolio: "
                        f"order_id={order_id} position_id={position_id[:8]}"
                    )
                    # #62a-D4-PR2b: don't return — fall through to the
                    # internal-fill block below (line 1252+) which fills
                    # at current_mark, updates portfolio cash, emits
                    # ledger entry, and calls close_position_shared
                    # (writes learning_feedback_loops outcome for cohort
                    # comparison). Same code path exercised by DRY_RUN
                    # and Alpaca-failure-fallback flows.
                else:
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
                        # P0-A INVARIANT (2026-07-10, F-A2-1 / E6): a LIVE submit
                        # that raises must NEVER be internally filled (this is the
                        # 2026-04-16 ghost-position class — closed here). Hold the
                        # position OPEN in an explicit alarmed state; the fill
                        # reconciler (targeted lookup) or the operator resolves it.
                        # No phantom internal fill can accumulate.
                        try:
                            supabase.table("paper_orders").update({
                                "status": "needs_manual_review",
                            }).eq("id", order_id).execute()
                        except Exception:
                            pass
                        alert(
                            _get_admin_supabase(),
                            alert_type="force_close_failed",
                            severity="critical",
                            message=f"LIVE close submit raised — position HELD OPEN, no internal fill: {position.get('symbol')} ({type(e).__name__})",
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
                                "state": "unknown_reconciling",
                                "consequence": "Broker submit outcome unknown; position remains OPEN (P0-A invariant). Resolved by the fill reconciler or operator — NEVER internally filled (2026-04-16 ghost-position class closed).",
                                "operator_action_required": "Verify the broker order state; the position is safely OPEN. Re-evaluate next cycle or close manually.",
                            },
                        )
                        logger.critical(
                            f"[EXIT_EVAL] P0-A: Alpaca close submit raised for {order_id}: {e}. "
                            f"Position HELD OPEN (unknown_reconciling) — NO internal fill."
                        )
                        return {
                            "order_id": order_id,
                            "processed": 0,
                            "routed_to": "unknown_reconciling",
                            "note": "LIVE close submit raised — held open for broker reconciliation (P0-A); no internal fill",
                        }

        # ── STRUCTURAL INVARIANT GUARD (P0-A / E6, 2026-07-10) ─────────────
        # The internal-fill block below is UNREACHABLE for a LIVE-routed close.
        # A live close requires a BROKER ACKNOWLEDGEMENT; it may NEVER be filled
        # internally (the 2026-04-16 ghost-position class). Any live position
        # that reaches here (a routing edge, an unexpected path) is HELD OPEN in
        # an explicit alarmed state — never internally filled. Paper/shadow
        # closes (should_submit_to_broker False, incl. the shadow_blocked
        # fall-through above) fill internally exactly as before.
        try:
            from packages.quantum.brokers.execution_router import (
                should_submit_to_broker as _p0a_should_submit,
            )
            _p0a_is_live_close = _p0a_should_submit(position["portfolio_id"], supabase)
        except Exception:
            _p0a_is_live_close = True  # fail-closed: unknown routing → treat as live
        if _p0a_is_live_close:
            try:
                supabase.table("paper_orders").update({
                    "status": "needs_manual_review",
                }).eq("id", order_id).execute()
            except Exception:
                pass
            alert(
                _get_admin_supabase(),
                alert_type="force_close_failed",
                severity="critical",
                message=f"LIVE close reached the internal-fill guard — HELD OPEN, no internal fill: {position.get('symbol')}",
                user_id=user_id,
                symbol=position.get("symbol"),
                position_id=position_id,
                metadata={
                    "function_name": "_close_position",
                    "position_id": position_id,
                    "order_id": order_id,
                    "reason": reason,
                    "state": "unknown_reconciling",
                    "consequence": "A live-routed close reached the internal-fill path; blocked by the P0-A structural guard. Position remains OPEN; resolved by the reconciler or operator — never internally filled.",
                },
            )
            return {
                "order_id": order_id,
                "processed": 0,
                "routed_to": "unknown_reconciling",
                "note": "LIVE close blocked at the internal-fill guard — held open (P0-A invariant)",
            }

        # --- Internal fill (internal_paper or Alpaca fallback) ---
        # 06-12 (#1017 class): the fill prices at the EXECUTABLE side, not
        # the triggering mid. Sign convention unchanged — achievable_close
        # comes from the same finalize_mark stack as current_mark. Fail-soft:
        # mid fallback carries an explicit fill_quality flag so learning can
        # weight or exclude; this step can never abort the close.
        _mid_reference = float(exit_price)
        exit_price, _fill_quality = _select_internal_fill_price(
            position, exit_price
        )
        logger.warning(
            f"[INTERNAL_FILL] position={position_id[:8]} fill_quality="
            f"{_fill_quality} mid={_mid_reference} executable_fill="
            f"{round(exit_price, 4)} "
            f"delta={round((exit_price - _mid_reference), 4)}"
        )

        # CLOSE_FILL_GAP (internal/shadow + Alpaca-fallback fill): record the
        # slippage between the stage-time full-cross estimate and the executable
        # fill. Additive, observe-only; best-effort. cross/mid are the locals
        # captured at stage (None for a non-corroborated internal close ->
        # fill-only line, gap_fraction=NA).
        try:
            from packages.quantum.services.close_fill_gap import (
                log_close_fill_gap as _cfg_log,
            )
            _cfg_log(
                position.get("symbol"), position_id,
                _cfg_cross, _cfg_mid, exit_price,
                reason=reason, log=logger,
            )
        except Exception as _cfg_e:
            logger.warning(f"[CLOSE_FILL_GAP] internal emit failed: {_cfg_e}")

        # 1. Mark order as filled.
        #
        # FIX 3 (2026-05-18 instrumentation gap): also stamp submitted_at
        # = now. Pre-fix, target_profit_hit close orders had filled_at
        # populated but submitted_at NULL (verified empirically: 11 of
        # 11 such closes in 60d had submitted_at IS NULL). This broke
        # exit-side latency analysis for the most common exit path.
        # For internal/fallback fills the submission and fill happen
        # in the same call site, so submitted_at == filled_at is the
        # most honest timestamp. Alpaca-path submissions write
        # submitted_at separately upstream.
        try:
            _oj_row = supabase.table("paper_orders") \
                .select("order_json").eq("id", order_id).single().execute().data or {}
            _order_json = _oj_row.get("order_json") or {}
        except Exception:
            _order_json = {}
        _order_json["fill_quality"] = _fill_quality
        _order_json["fill_mid_reference"] = _mid_reference
        # CLOSE_FILL_GAP P2 persistence (existing JSONB, NO migration): fold
        # {cross, mid, fill, gap_fraction} into this same write so the
        # distribution is queryable beyond short log retention. Best-effort.
        try:
            from packages.quantum.services.close_fill_gap import (
                stamp_payload as _cfg_payload,
            )
            _order_json.update(_cfg_payload(_cfg_cross, _cfg_mid, exit_price))
        except Exception:
            pass
        supabase.table("paper_orders").update({
            "status": "filled",
            "filled_qty": abs_qty,
            "avg_fill_price": round(exit_price, 2),
            "fees_usd": 0,
            "submitted_at": now,
            "filled_at": now,
            "order_json": _order_json,
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
                "fill_quality": _fill_quality,
                "fill_mid_reference": _mid_reference,
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
