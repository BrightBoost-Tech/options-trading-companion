from supabase import Client
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, TypedDict
import logging
import statistics
import hashlib

from packages.quantum.execution.transaction_cost_model import TransactionCostModel as V3TCM
from packages.quantum.models import TradeTicket, OptionLeg
from packages.quantum.strategy_profiles import CostModelConfig

logger = logging.getLogger(__name__)


def _build_legs_fingerprint(order_json: Optional[Dict]) -> Optional[str]:
    """
    Build a deterministic fingerprint from order legs for position grouping.
    Returns SHA256 hash of sorted leg symbols.
    """
    if not order_json:
        return None

    legs = order_json.get("legs", [])
    if not legs:
        return None

    # Extract symbols and sort for deterministic fingerprint
    symbols = sorted([leg.get("symbol", "") for leg in legs if leg.get("symbol")])
    if not symbols:
        return None

    fingerprint_str = "|".join(symbols)
    return hashlib.sha256(fingerprint_str.encode()).hexdigest()[:16]

class ExecutionDragStats(TypedDict):
    n: int
    avg_abs_slip: float            # dollars
    avg_slip_bps: float            # basis points vs target_price
    avg_fees: float                # dollars
    avg_drag: float                # dollars = avg_abs_slip + avg_fees
    source: str                    # "history"

class ExecutionService:
    def __init__(self, supabase: Client):
        self.supabase = supabase
        self.suggestions_table = "trade_suggestions"
        self.logs_table = "suggestion_logs"
        self.executions_table = "trade_executions"

    def register_execution(self,
                           user_id: str,
                           suggestion_id: str,
                           fill_details: Dict[str, Any] = None) -> Dict:
        """
        Explicitly links a suggestion to an execution.
        suggestion_id can be a trade_suggestions.id (primary) or suggestion_logs.id (legacy/fallback).
        """
        if not fill_details:
            fill_details = {}

        # 1. Fetch suggestion from trade_suggestions (Primary)
        suggestion = None
        source_table = None

        try:
            s_res = self.supabase.table(self.suggestions_table).select("*").eq("id", suggestion_id).single().execute()
            if s_res.data:
                suggestion = s_res.data
                source_table = self.suggestions_table
        except Exception:
            # Not found in trade_suggestions or error
            pass

        # 2. Fallback to suggestion_logs if not found
        if not suggestion:
            try:
                s_res = self.supabase.table(self.logs_table).select("*").eq("id", suggestion_id).single().execute()
                if s_res.data:
                    suggestion = s_res.data
                    source_table = self.logs_table
            except Exception:
                pass

        # 3. Calculate Realized Slippage & Drag
        mid_price = fill_details.get("mid_price_at_submission")
        fill_price = fill_details.get("fill_price", 0.0)

        # Realized Cost = Fill Price + Fees
        # Drag = |Fill - Mid| + Fees (per share)
        fees = fill_details.get("fees", 0.0)
        quantity = int(fill_details.get("quantity", 1))

        realized_execution_cost = 0.0
        slippage = 0.0

        if quantity > 0:
            if mid_price and fill_price > 0:
                slippage = abs(fill_price - mid_price)

            # Drag per unit
            fees_per_unit = fees / quantity
            realized_execution_cost = slippage + fees_per_unit

        # 4. Prepare Context Fields
        execution_data = {
            "user_id": user_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": fill_details.get("symbol") or (suggestion.get("symbol") if suggestion and "symbol" in suggestion else suggestion.get("ticker") if suggestion else "UNKNOWN"),
            "fill_price": fill_price,
            "quantity": quantity,
            "fees": fees,
            "mid_price_at_submission": mid_price,
            # We assume target_price is in suggestion or passed in fill_details
            "target_price": fill_details.get("target_price") or (suggestion.get("target_price") if suggestion else None),
            "order_json": fill_details.get("order_json") or (suggestion.get("order_json") if suggestion else None)
        }

        # Link IDs based on source
        if source_table == self.suggestions_table:
            execution_data["suggestion_id"] = suggestion_id
            # Extract additional context from trade_suggestions
            if suggestion:
                execution_data["trace_id"] = suggestion.get("trace_id")
                execution_data["window"] = suggestion.get("window")
                execution_data["strategy"] = suggestion.get("strategy")
                execution_data["model_version"] = suggestion.get("model_version")
                execution_data["features_hash"] = suggestion.get("features_hash")
                execution_data["regime"] = suggestion.get("regime")

        elif source_table == self.logs_table:
            execution_data["suggestion_log_id"] = suggestion_id
            # Try to infer some fields if possible, or leave null
            if suggestion:
                execution_data["regime"] = suggestion.get("regime_context") # might need parsing if it's JSON
                logger.warning(f"Execution linked to legacy suggestion_logs (id={suggestion_id}). Degrading context quality.")

        else:
             # Orphaned execution
             logger.error(f"Execution registered without valid suggestion link (id={suggestion_id}). Learning feedback loop broken.")

        try:
            ex_res = self.supabase.table(self.executions_table).insert(execution_data).execute()
            execution = ex_res.data[0] if ex_res.data else None
        except Exception as e:
            logger.error(f"Failed to insert execution: {e}")
            return None

        # 5. Update Source Table status
        if execution:
            if source_table == self.suggestions_table:
                # Assuming trade_suggestions has a status field or similar?
                # The user didn't explicitly ask to update trade_suggestions status,
                # but historically suggestion_logs were updated.
                # Checking schema notes: trade_suggestions has 'status'.
                try:
                    self.supabase.table(self.suggestions_table).update({
                        "status": "filled"
                    }).eq("id", suggestion_id).execute()
                except Exception:
                    pass
            elif source_table == self.logs_table:
                self.supabase.table(self.logs_table).update({
                    "was_accepted": True,
                    "trade_execution_id": execution["id"]
                }).eq("id", suggestion_id).execute()

        # 6. Record fill in v4 position ledger (best-effort, non-blocking)
        if execution:
            self._record_to_position_ledger(
                user_id=user_id,
                execution=execution,
                suggestion=suggestion,
                fill_details=fill_details,
            )

        return execution

    def _record_to_position_ledger(
        self,
        user_id: str,
        execution: Dict[str, Any],
        suggestion: Optional[Dict[str, Any]],
        fill_details: Dict[str, Any],
    ) -> None:
        """
        Record fill(s) to v4 position ledger (best-effort).

        For multi-leg strategies, records a fill for EACH leg in order_json.
        Price allocation: If only total fill_price is available, it's split
        evenly across legs. Per-leg prices from order_json take precedence.

        Wraps PositionLedgerService.record_fill() with error handling
        to ensure ledger failures don't break execution registration.
        """
        try:
            from packages.quantum.services.position_ledger_service import PositionLedgerService

            ledger = PositionLedgerService(self.supabase)

            order_json = execution.get("order_json") or (suggestion.get("order_json") if suggestion else None)
            legs = order_json.get("legs", []) if order_json else []

            # Build shared context from suggestion fields
            context = {
                "trace_id": execution.get("trace_id"),
                "legs_fingerprint": _build_legs_fingerprint(order_json),
                "strategy_key": suggestion.get("strategy_key") if suggestion else None,
                "strategy": execution.get("strategy"),
                "window": execution.get("window"),
                "regime": execution.get("regime"),
                "model_version": execution.get("model_version"),
                "features_hash": execution.get("features_hash"),
                "source": "LIVE",
            }

            if legs:
                # Multi-leg: record a fill for each leg
                self._record_multi_leg_fills(
                    ledger=ledger,
                    user_id=user_id,
                    execution=execution,
                    fill_details=fill_details,
                    legs=legs,
                    context=context,
                )
            else:
                # Single-leg or no order_json: record single fill
                self._record_single_leg_fill(
                    ledger=ledger,
                    user_id=user_id,
                    execution=execution,
                    fill_details=fill_details,
                    context=context,
                )

        except Exception as e:
            # Best-effort: log error but don't fail execution registration
            logger.error(f"[LEDGER] Error recording fill to ledger: {e}")

    def _record_multi_leg_fills(
        self,
        ledger,
        user_id: str,
        execution: Dict[str, Any],
        fill_details: Dict[str, Any],
        legs: List[Dict[str, Any]],
        context: Dict[str, Any],
    ) -> None:
        """
        Record fills for a multi-leg strategy.

        For each leg in the order_json.legs array:
        - Determine symbol from leg.symbol
        - Determine action (BUY/SELL) from leg.action
        - Determine qty from leg.quantity or default to fill_details.quantity
        - Determine price from leg.price or split total evenly

        Idempotency: Uses leg_index in broker_exec_id derivation for uniqueness.
        """
        total_fill_price = float(fill_details.get("fill_price", 0))
        total_fees = float(fill_details.get("fees", 0))
        total_qty = int(fill_details.get("quantity", 1))
        num_legs = len(legs)

        # Price allocation: if no per-leg prices, split total evenly
        # Fee allocation: split fees evenly across legs
        fee_per_leg = total_fees / num_legs if num_legs > 0 else total_fees

        results = []

        for leg_index, leg in enumerate(legs):
            # Extract leg symbol
            leg_symbol = leg.get("symbol")
            if not leg_symbol:
                logger.warning(f"[LEDGER] Leg {leg_index} missing symbol, skipping")
                continue

            # Extract leg action (BUY/SELL)
            leg_action = self._resolve_leg_action(leg)

            # Extract leg quantity (per-leg or default to 1)
            leg_qty = int(leg.get("quantity", leg.get("qty", 1)))

            # Extract leg price
            # Priority: leg.price > leg.fill_price > proportional split of total
            leg_price = leg.get("price") or leg.get("fill_price")
            if leg_price is None:
                # Proportional split based on leg qty vs total qty
                # If legs have equal qty, this is even split
                if total_qty > 0 and num_legs > 0:
                    leg_price = total_fill_price / num_legs
                else:
                    leg_price = 0

            leg_price = float(leg_price)

            # Extract option details
            right = leg.get("right", "C" if leg_symbol and len(leg_symbol) > 10 else "S")
            strike = leg.get("strike")
            expiry = leg.get("expiry")
            multiplier = int(leg.get("multiplier", 100))

            # Build unique broker_exec_id for this leg (for idempotency)
            base_broker_id = fill_details.get("broker_exec_id")
            leg_broker_id = f"{base_broker_id}:leg{leg_index}" if base_broker_id else None

            fill_data = {
                "symbol": leg_symbol,
                "underlying": self._extract_underlying(leg_symbol),
                "action": leg_action,
                "qty": leg_qty,
                "price": leg_price,
                "fee": fee_per_leg,
                "filled_at": execution.get("timestamp"),
                "broker_exec_id": leg_broker_id,
                "right": right,
                "strike": strike,
                "expiry": expiry,
                "multiplier": multiplier,
                "leg_index": leg_index,  # For event_key uniqueness
            }

            # Record this leg's fill
            # Include leg_index in trade_execution_id for event_key uniqueness
            result = ledger.record_fill(
                user_id=user_id,
                trade_execution_id=f"{execution.get('id')}:leg{leg_index}",
                fill_data=fill_data,
                context=context,
            )

            results.append(result)

            if result.get("success"):
                logger.info(
                    f"[LEDGER] Multi-leg fill recorded: exec={execution.get('id')}, "
                    f"leg_index={leg_index}, symbol={leg_symbol}, action={leg_action}, "
                    f"group={result.get('group_id')}"
                )
            else:
                logger.warning(
                    f"[LEDGER] Multi-leg fill failed: exec={execution.get('id')}, "
                    f"leg_index={leg_index}, error={result.get('error')}"
                )

        # Log summary
        success_count = sum(1 for r in results if r.get("success"))
        logger.info(
            f"[LEDGER] Multi-leg recording complete: exec={execution.get('id')}, "
            f"legs={num_legs}, success={success_count}/{len(results)}"
        )

    def _record_single_leg_fill(
        self,
        ledger,
        user_id: str,
        execution: Dict[str, Any],
        fill_details: Dict[str, Any],
        context: Dict[str, Any],
    ) -> None:
        """Record a single-leg fill (original logic)."""
        symbol = execution.get("symbol", "UNKNOWN")

        # Determine action from fill_details
        action = fill_details.get("action", "").upper()
        if not action:
            legacy_side = fill_details.get("side", "").lower()
            if legacy_side:
                action = "BUY" if legacy_side == "buy" else "SELL"

        if not action:
            action = "BUY"

        # Default option details for single-leg
        right = "S"
        if symbol and len(symbol) > 10 and any(c.isdigit() for c in symbol):
            # Likely an option symbol
            right = "C" if "C" in symbol else "P"

        fill_data = {
            "symbol": symbol,
            "underlying": self._extract_underlying(symbol),
            "action": action,
            "qty": int(fill_details.get("quantity", 1)),
            "price": float(fill_details.get("fill_price", 0)),
            "fee": float(fill_details.get("fees", 0)),
            "filled_at": execution.get("timestamp"),
            "broker_exec_id": fill_details.get("broker_exec_id"),
            "right": right,
            "strike": None,
            "expiry": None,
            "multiplier": 100,
        }

        result = ledger.record_fill(
            user_id=user_id,
            trade_execution_id=execution.get("id"),
            fill_data=fill_data,
            context=context,
        )

        if result.get("success"):
            logger.info(
                f"[LEDGER] Fill recorded: exec={execution.get('id')}, "
                f"group={result.get('group_id')}, status={result.get('group_status')}"
            )
        else:
            logger.warning(
                f"[LEDGER] Fill recording failed: exec={execution.get('id')}, "
                f"error={result.get('error')}"
            )

    def _resolve_leg_action(self, leg: Dict[str, Any]) -> str:
        """
        Resolve action (BUY/SELL) from leg data.

        Handles various formats:
        - leg.action: "buy", "sell", "BUY", "SELL"
        - leg.action: "buy_to_open", "sell_to_open", "buy_to_close", "sell_to_close"
        - leg.side: "buy", "sell" (legacy)
        """
        action = leg.get("action", "").lower()

        if action in ["buy", "buy_to_open", "buy_to_close"]:
            return "BUY"
        elif action in ["sell", "sell_to_open", "sell_to_close"]:
            return "SELL"

        # Try legacy 'side' field
        side = leg.get("side", "").lower()
        if side == "buy":
            return "BUY"
        elif side == "sell":
            return "SELL"

        # Default to BUY if can't determine
        logger.warning(f"[LEDGER] Could not resolve action for leg, defaulting to BUY: {leg}")
        return "BUY"

    def _extract_underlying(self, symbol: str) -> str:
        """Extract underlying from option symbol or return as-is for stock."""
        if not symbol:
            return "UNKNOWN"

        # Options symbols are typically like "AAPL240119C00150000"
        if len(symbol) > 10 and any(c.isdigit() for c in symbol):
            underlying = ""
            for c in symbol:
                if c.isalpha():
                    underlying += c
                else:
                    break
            return underlying or symbol

        return symbol

    def get_batch_execution_drag_stats(
        self,
        user_id: str,
        symbols: List[str],
        lookback_days: int = 45,
        min_samples: int = 3,
    ) -> Dict[str, ExecutionDragStats]:
        """
        Calculates execution drag stats for a batch of symbols based on history.
        """
        if not symbols or not user_id:
            return {}

        results: Dict[str, ExecutionDragStats] = {}
        cutoff_date = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()

        try:
            # Step 1: Pull executions in ONE query
            # We need to check both suggestion_id and suggestion_log_id
            query = self.supabase.table(self.executions_table)\
                .select("symbol, fill_price, fees, suggestion_id, suggestion_log_id, quantity, target_price")\
                .eq("user_id", user_id)\
                .in_("symbol", symbols)\
                .not_.is_("suggestion_id", "null")\
                .not_.is_("fill_price", "null")\
                .gte("timestamp", cutoff_date)

            ex_res = query.order("timestamp", desc=True).execute()
            executions = ex_res.data or []

            if not executions:
                return {}

            # Step 2: Resolve Targets
            # Targets might be directly on execution now (new schema) or on linked suggestion

            # Collect IDs for lookup
            suggestion_ids = set()
            log_ids = set()

            for ex in executions:
                # If target_price is already on execution, we don't need to look it up
                if ex.get("target_price") is not None:
                    continue

                if ex.get("suggestion_id"):
                    suggestion_ids.add(ex["suggestion_id"])
                elif ex.get("suggestion_log_id"):
                    log_ids.add(ex["suggestion_log_id"])

            target_map = {} # ID -> Price

            # Lookup trade_suggestions
            if suggestion_ids:
                try:
                    res = self.supabase.table(self.suggestions_table)\
                        .select("id, target_price")\
                        .in_("id", list(suggestion_ids))\
                        .execute()
                    for row in res.data or []:
                        if row.get("target_price"):
                            target_map[row["id"]] = float(row["target_price"])
                except Exception:
                    pass

            # Lookup suggestion_logs
            if log_ids:
                try:
                    res = self.supabase.table(self.logs_table)\
                        .select("id, target_price")\
                        .in_("id", list(log_ids))\
                        .execute()
                    for row in res.data or []:
                        if row.get("target_price"):
                            target_map[row["id"]] = float(row["target_price"])
                except Exception:
                    pass

            # Compute stats
            aggregates = {}

            for ex in executions:
                symbol = ex.get("symbol")
                fill_price = float(ex.get("fill_price") or 0.0)
                fees = float(ex.get("fees") or 0.0)
                qty = float(ex.get("quantity") or 0.0)

                # Fees per contract dollars
                fees_per_contract = (fees / qty) if qty > 0 else fees

                # Determine target price
                target = None
                if ex.get("target_price") is not None:
                    target = float(ex["target_price"])
                else:
                    # Try linking
                    sid = ex.get("suggestion_id") or ex.get("suggestion_log_id")
                    target = target_map.get(sid)

                if target is None or target <= 0:
                    continue
                if fill_price is None:
                    continue

                # Slippage in contract dollars (x100 for options)
                abs_slip_share = abs(fill_price - target)
                abs_slip_contract = abs_slip_share * 100.0

                slip_bps = (abs_slip_share / target) * 10_000
                drag_contract = abs_slip_contract + fees_per_contract

                if symbol not in aggregates:
                    aggregates[symbol] = {
                        "count": 0,
                        "sum_abs_slip": 0.0,
                        "sum_slip_bps": 0.0,
                        "sum_fees": 0.0,
                        "sum_drag": 0.0
                    }

                agg = aggregates[symbol]
                agg["count"] += 1
                agg["sum_abs_slip"] += abs_slip_contract
                agg["sum_slip_bps"] += slip_bps
                agg["sum_fees"] += fees_per_contract
                agg["sum_drag"] += drag_contract

            # Finalize results
            for symbol, agg in aggregates.items():
                n = agg["count"]
                if n < min_samples:
                    continue

                results[symbol] = {
                    "n": n,
                    "avg_abs_slip": agg["sum_abs_slip"] / n,  # CONTRACT dollars
                    "avg_slip_bps": agg["sum_slip_bps"] / n,
                    "avg_fees": agg["sum_fees"] / n,          # Fees per contract
                    "avg_drag": agg["sum_drag"] / n,          # CONTRACT dollars
                    "source": "history"
                }

        except Exception as e:
            logger.error(f"Error calculating batch execution drag: {e}")
            return {}

        return results

    def get_execution_drag_stats(
        self,
        user_id: str,
        symbol: str,
        lookback_days: int = 45,
        min_samples: int = 3
    ) -> Optional[ExecutionDragStats]:
        """
        Wrapper for single symbol stats.
        """
        batch = self.get_batch_execution_drag_stats(
            user_id=user_id,
            symbols=[symbol],
            lookback_days=lookback_days,
            min_samples=min_samples
        )
        return batch.get(symbol)

    def estimate_execution_cost(
        self,
        symbol: str,
        spread_pct: float | None = None,
        user_id: str | None = None,
        entry_cost: float | None = None,
        num_legs: int | None = None
    ) -> float:
        """
        Returns estimated execution cost (drag) per share/contract.
        Prioritizes historical data if user_id is provided and enough samples exist.
        Fallbacks to heuristic spread proxy: (Spread * 0.5) + (Legs * Fees).
        """
        # 1. Try History
        if user_id:
            stats = self.get_execution_drag_stats(user_id, symbol)
            if stats:
                return stats["avg_drag"]

        # 2. Fallback Heuristic
        # Default spread_pct if None
        if spread_pct is None:
            spread_pct = 0.005 # 0.5% default assumption

        # Precise formula match for scanner equivalence:
        # Cost = (Entry * Spread% * 0.5) + (Legs * 0.0065)
        # Note: Return value must be in CONTRACT dollars (x100 for options spread component).
        # entry_cost is per-share total premium (e.g. 1.50).
        # num_legs * 0.0065 is per share fees (assuming 0.65/contract).
        # So we multiply the entire share-based cost by 100.
        if entry_cost is not None and num_legs is not None:
             spread_value = abs(entry_cost) * spread_pct
             share_cost = (spread_value * 0.5) + (num_legs * 0.0065)
             return share_cost * 100.0

        # Legacy Assumption: Drag is roughly half the spread + some fees
        # Return a safe default if specific trade structure is unknown.
        # 5 cents/share = $5.00/contract
        return 5.0

    def simulate_fill(self,
                      symbol: str,
                      order_type: str,
                      price: float,
                      quantity: float,
                      side: str,
                      regime: str) -> Dict[str, Any]:
        """
        Simulates an execution for backtesting/paper trading using V3 TransactionCostModel.
        """
        # 1. Build TradeTicket
        ticket = TradeTicket(
            symbol=symbol,
            order_type="market" if order_type == "market" else "limit",
            limit_price=None if order_type == "market" else float(price),
            quantity=int(quantity),
            legs=[OptionLeg(symbol=symbol, action=side, type="other", quantity=1)]
        )

        # 2. Build synthetic quote
        mid = float(price)
        regime_upper = str(regime).upper()
        spread_map = {
            "SUPPRESSED": 0.005,
            "NORMAL": 0.01,
            "ELEVATED": 0.015,
            "SHOCK": 0.02
        }
        spread_pct = spread_map.get(regime_upper, 0.01)

        bid = mid * (1.0 - spread_pct/2.0)
        ask = mid * (1.0 + spread_pct/2.0)

        quote = {"bid_price": bid, "ask_price": ask}

        # 3. Choose CostModelConfig
        fill_model = "conservative" if regime_upper == "SHOCK" else "neutral"
        config = CostModelConfig(fill_probability_model=fill_model)

        # 4. Call V3TCM.estimate
        result = V3TCM.estimate(ticket, quote, config)

        # 5. Compute execution drag (in USD)
        execution_drag_usd = result["expected_spread_cost_usd"] + result["expected_slippage_usd"] + result["fees_usd"]

        # 6. Return exact keys
        return {
            "status": "simulated",
            "filled_quantity": int(quantity),
            "fill_price": float(result["expected_fill_price"]),
            "slippage_paid": float(result["expected_slippage_usd"]),
            "commission_paid": float(result["fees_usd"]),
            "fill_probability": float(result["fill_probability"]),
            "execution_drag": float(execution_drag_usd),
            "tcm_version": result.get("tcm_version"),
            "quote_used_fallback": True
        }
