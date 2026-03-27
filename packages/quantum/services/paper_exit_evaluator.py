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
from typing import Dict, Any, List, Tuple, Optional, Callable

PDT_MAX_DAY_TRADES = int(os.environ.get("PDT_MAX_DAY_TRADES", "3"))
EXIT_RANKING_ENABLED = os.environ.get("EXIT_RANKING_ENABLED", "1") == "1"

logger = logging.getLogger(__name__)


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

EXIT_CONDITIONS: Dict[str, Dict[str, Any]] = {
    "target_profit": {
        "description": "Position has reached target profit percentage",
        "check": lambda pos: _check_target_profit(pos, 0.50),
    },
    "stop_loss": {
        "description": "Position has exceeded maximum acceptable loss",
        "check": lambda pos: _check_stop_loss(pos, 2.0),
    },
    "dte_threshold": {
        "description": "Position is too close to expiration (gamma risk)",
        "check": lambda pos: 0 < days_to_expiry(pos) <= 7,
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
    is_debit = _is_debit_spread(position)
    if max_credit is not None:
        try:
            mc = float(max_credit)
            upl = float(unrealized_pl or 0)
            entry_cost = abs(mc) * 100
            if is_debit:
                tp_threshold = entry_cost * 0.50
                sl_threshold = -(entry_cost * 1.0)  # Can't lose more than paid
                spread_type = "DEBIT"
            else:
                tp_threshold = entry_cost * 0.50
                sl_threshold = -(entry_cost * 2.0)
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

        # 3. Evaluate each position (with per-cohort exit params when Policy Lab is on)
        closes: List[Dict[str, Any]] = []
        holds: List[Dict[str, Any]] = []

        # Build cohort → exit conditions map for Policy Lab
        cohort_conditions_cache: Dict[str, Dict] = {}
        from packages.quantum.policy_lab.config import is_policy_lab_enabled
        policy_lab_on = is_policy_lab_enabled()
        if policy_lab_on:
            from packages.quantum.policy_lab.config import load_cohort_configs
            cohort_cfgs = load_cohort_configs(user_id, self.client)
            for cname, cfg in cohort_cfgs.items():
                cohort_conditions_cache[cname] = build_exit_conditions(
                    target_profit_pct=cfg.target_profit_pct,
                    stop_loss_pct=cfg.stop_loss_pct,
                    min_dte_to_exit=cfg.min_dte_to_exit,
                )

        for position in positions:
            # Resolve cohort-specific exit conditions
            pos_conditions = None
            if policy_lab_on:
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
            return []

    def _resolve_position_cohort(self, position: Dict[str, Any]) -> Optional[str]:
        """Resolve which cohort a position belongs to via its portfolio_id."""
        portfolio_id = position.get("portfolio_id")
        if not portfolio_id:
            return None
        try:
            res = self.client.table("policy_lab_cohorts") \
                .select("cohort_name") \
                .eq("portfolio_id", portfolio_id) \
                .limit(1) \
                .execute()
            if res.data:
                return res.data[0]["cohort_name"]
        except Exception:
            pass
        return None

    def _close_position(
        self,
        user_id: str,
        position_id: str,
        reason: str,
    ) -> Dict[str, Any]:
        """
        Close a single position using the position's current_mark as exit price.

        Uses current_mark (set by the most recent MTM run during market hours)
        instead of fetching a live Polygon quote, which would return stale
        after-hours data and corrupt realized P&L.
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

        # Fetch position
        pos_res = supabase.table("paper_positions") \
            .select("*") \
            .eq("id", position_id) \
            .single() \
            .execute()
        position = pos_res.data

        # Resolve OCC symbol
        occ_symbol = PaperAutopilotService._resolve_occ_symbol(position, supabase)

        qty = float(position["quantity"])
        side = "sell" if qty > 0 else "buy"
        abs_qty = abs(qty)
        multiplier = 100.0

        # Use current_mark from the most recent MTM run as exit price.
        # Falls back to avg_entry_price (break-even close) if no mark exists.
        exit_price = float(position.get("current_mark") or position.get("avg_entry_price") or 0)
        entry_price = float(position.get("avg_entry_price") or 0)

        # Carry strike/expiry/type from the position's original leg so
        # order validation doesn't reject the closing order.
        orig_legs = position.get("legs") or []
        orig_leg = orig_legs[0] if orig_legs else {}

        ticket = TradeTicket(
            symbol=position["symbol"],
            quantity=abs_qty,
            order_type="market",
            strategy_type="custom",
            source_engine="paper_exit_evaluator",
            legs=[{
                "symbol": occ_symbol,
                "action": side,
                "quantity": abs_qty,
                "type": orig_leg.get("type", "call"),
                "strike": orig_leg.get("strike"),
                "expiry": orig_leg.get("expiry"),
            }],
        )

        if position.get("suggestion_id"):
            ticket.source_ref_id = position["suggestion_id"]

        # Stage the order for audit trail
        order_id = _stage_order_internal(
            supabase,
            analytics,
            user_id,
            ticket,
            position["portfolio_id"],
            position_id=position_id,
            trace_id_override=position.get("trace_id"),
        )

        now = datetime.now(timezone.utc).isoformat()

        # --- Fill the order directly at current_mark (no Polygon fetch) ---

        # 1. Mark order as filled
        supabase.table("paper_orders").update({
            "status": "filled",
            "filled_qty": abs_qty,
            "avg_fill_price": exit_price,
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

        # 4. Close position with realized P&L
        #    Short (credit) positions: profit = (entry_credit - close_cost) * qty * 100
        #    Long (debit) positions:    profit = (exit_price - entry_cost) * qty * 100
        if qty < 0:
            # Short position: entry was a credit (sell), exit is a debit (buy)
            realized_pl = (entry_price - exit_price) * abs_qty * multiplier
        else:
            # Long position: entry was a debit (buy), exit is a credit (sell)
            realized_pl = (exit_price - entry_price) * abs_qty * multiplier

        supabase.table("paper_positions").update({
            "quantity": 0,
            "status": "closed",
            "close_reason": reason,
            "closed_at": now,
            "realized_pl": realized_pl,
            "updated_at": now,
        }).eq("id", position_id).execute()

        return {
            "order_id": order_id,
            "processed": 1,
        }
