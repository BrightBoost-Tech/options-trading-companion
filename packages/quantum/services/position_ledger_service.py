"""
Position Ledger Service (v4 Accounting)

Canonical position ledger with multi-leg strategy grouping.
Handles:
- Fill recording with automatic group/leg management
- Position lifecycle (OPEN -> CLOSED/ASSIGNED/EXPIRED)
- Event tracking with idempotency
- Reconciliation against broker snapshots

Usage:
    from packages.quantum.services.position_ledger_service import PositionLedgerService

    ledger = PositionLedgerService(supabase_client)
    result = ledger.record_fill(user_id, trade_execution_id, fill_data, context)
"""

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class PositionLedgerService:
    """
    Manages the canonical position ledger with multi-leg support.

    Tables managed:
    - position_groups: Strategy-level grouping
    - position_legs: Individual leg positions
    - fills: Execution fill records
    - position_events: Append-only event log
    """

    def __init__(self, supabase_client):
        """
        Initialize the ledger service.

        Args:
            supabase_client: Supabase client (service_role for background jobs)
        """
        self.client = supabase_client

    # -------------------------------------------------------------------------
    # Core: record_fill
    # -------------------------------------------------------------------------

    def record_fill(
        self,
        user_id: str,
        trade_execution_id: Optional[str],
        fill_data: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Record a fill and update position ledger.

        This is the main entry point for recording fills from:
        - ExecutionService.register_execution()
        - Broker fill imports
        - Paper trading (future migration)

        Args:
            user_id: User UUID
            trade_execution_id: Optional FK to trade_executions.id
            fill_data: Fill details {
                symbol: str,           # Full symbol (e.g., "AAPL240119C00150000")
                underlying: str,       # e.g., "AAPL"
                action: str,           # "BUY" or "SELL" (fill action, NOT leg orientation)
                qty: int,              # Quantity (always positive)
                price: float,          # Fill price
                fee: float,            # Fee for this fill
                filled_at: str,        # ISO timestamp
                broker_exec_id: str,   # Optional broker execution ID
                right: str,            # "C", "P", or "S" (call, put, stock)
                strike: float,         # Optional strike price
                expiry: str,           # Optional expiry date (YYYY-MM-DD)
                multiplier: int,       # Contract multiplier (default 100)
            }
            context: Traceability context {
                trace_id: str,
                legs_fingerprint: str,
                strategy_key: str,
                strategy: str,
                window: str,
                regime: str,
                model_version: str,
                features_hash: str,
                source: str,           # "LIVE", "PAPER", "BACKFILL"
            }

        Returns:
            Dict with:
                success: bool
                group_id: str
                leg_id: str
                fill_id: str
                event_id: str
                group_status: str
                error: str (if failed)
        """
        try:
            # Extract fill details with defaults
            symbol = fill_data.get("symbol")
            underlying = fill_data.get("underlying") or self._extract_underlying(symbol)

            # Support both 'action' (new) and 'side' (legacy) parameters
            action = fill_data.get("action", "").upper()
            if not action:
                # Legacy fallback: map side -> action
                legacy_side = fill_data.get("side", "buy").lower()
                action = "BUY" if legacy_side == "buy" else "SELL"

            qty = int(fill_data.get("qty", 0))
            price = Decimal(str(fill_data.get("price", 0)))
            fee = Decimal(str(fill_data.get("fee", 0)))
            filled_at = fill_data.get("filled_at") or datetime.now(timezone.utc).isoformat()
            broker_exec_id = fill_data.get("broker_exec_id")
            right = fill_data.get("right", "S").upper()
            strike = fill_data.get("strike")
            expiry = fill_data.get("expiry")
            multiplier = int(fill_data.get("multiplier", 100))

            # Extract context
            trace_id = context.get("trace_id")
            legs_fingerprint = context.get("legs_fingerprint")
            strategy_key = context.get("strategy_key")
            strategy = context.get("strategy")
            window = context.get("window")
            regime = context.get("regime")
            model_version = context.get("model_version")
            features_hash = context.get("features_hash")
            source = context.get("source", "LIVE")

            if not symbol:
                return {"success": False, "error": "symbol is required"}
            if qty <= 0:
                return {"success": False, "error": "qty must be positive"}
            if action not in ("BUY", "SELL"):
                return {"success": False, "error": f"action must be BUY or SELL, got: {action}"}

            # Build idempotent event_key (includes action for uniqueness)
            event_key = self._build_event_key(
                trade_execution_id, symbol, action, filled_at, qty, price
            )

            # Check for duplicate event (idempotency)
            if event_key:
                existing_event = self._check_event_exists(user_id, event_key)
                if existing_event:
                    logger.info(f"[LEDGER] Duplicate event_key={event_key}, returning existing")
                    return {
                        "success": True,
                        "group_id": existing_event.get("group_id"),
                        "fill_id": existing_event.get("fill_id"),
                        "event_id": existing_event.get("id"),
                        "deduplicated": True,
                    }

            # Check for duplicate broker_exec_id (idempotency for broker fills)
            if broker_exec_id:
                existing_fill = self._check_fill_exists_by_broker_id(user_id, broker_exec_id)
                if existing_fill:
                    logger.info(f"[LEDGER] Duplicate broker_exec_id={broker_exec_id}")
                    return {
                        "success": True,
                        "group_id": existing_fill.get("group_id"),
                        "leg_id": existing_fill.get("leg_id"),
                        "fill_id": existing_fill.get("id"),
                        "deduplicated": True,
                    }

            # Step 1: Find or create position group
            group = self._find_or_create_group(
                user_id=user_id,
                underlying=underlying,
                legs_fingerprint=legs_fingerprint,
                strategy_key=strategy_key,
                trace_id=trace_id,
                strategy=strategy,
                window=window,
                regime=regime,
                model_version=model_version,
                features_hash=features_hash,
            )
            group_id = group["id"]

            # Step 2: Find or create position leg
            # Leg is resolved by (group_id, symbol) only, NOT by side
            # Orientation is determined on first fill only
            leg, is_new_leg = self._find_or_create_leg_by_symbol(
                group_id=group_id,
                user_id=user_id,
                symbol=symbol,
                underlying=underlying,
                right=right,
                strike=strike,
                expiry=expiry,
                multiplier=multiplier,
                action=action,  # Used to determine orientation if new leg
            )
            leg_id = leg["id"]
            leg_side = leg["side"]  # LONG or SHORT (stable property)

            # Step 3: Determine if opening or closing based on leg orientation + action
            is_opening = self._is_opening_fill_v2(leg_side, action)

            # Step 4: Check for over-close (flip) scenario
            qty_current = leg.get("qty_opened", 0) - leg.get("qty_closed", 0)
            if not is_opening and qty > qty_current:
                # Over-close: close current position, open new group for remainder
                return self._handle_over_close(
                    user_id=user_id,
                    trade_execution_id=trade_execution_id,
                    group_id=group_id,
                    leg=leg,
                    action=action,
                    total_qty=qty,
                    close_qty=qty_current,
                    price=price,
                    fee=fee,
                    filled_at=filled_at,
                    broker_exec_id=broker_exec_id,
                    source=source,
                    context=context,
                    fill_data=fill_data,
                )

            # Step 5: Insert fill with action
            fill_id = self._insert_fill(
                user_id=user_id,
                group_id=group_id,
                leg_id=leg_id,
                trade_execution_id=trade_execution_id,
                broker_exec_id=broker_exec_id,
                action=action,
                side=leg_side,  # Deprecated, kept for backward compat
                qty=qty,
                price=price,
                fee=fee,
                filled_at=filled_at,
                source=source,
            )

            # Step 6: Update leg quantities
            self._update_leg_quantities(
                leg_id=leg_id,
                qty=qty,
                price=price,
                is_opening=is_opening,
            )

            # Step 7: Compute cash impact and insert event
            # Cash impact based on action: BUY = cash outflow, SELL = cash inflow
            cash_impact = self._compute_cash_impact(
                action=action,
                qty=qty,
                price=price,
                fee=fee,
                multiplier=multiplier,
            )
            # qty_delta is signed based on action
            qty_delta = qty if action == "BUY" else -qty

            event_id = self._insert_event(
                user_id=user_id,
                group_id=group_id,
                fill_id=fill_id,
                leg_id=leg_id,
                event_type="FILL",
                amount_cash=cash_impact,
                qty_delta=qty_delta,
                event_key=event_key,
            )

            # Step 8: Update group materialized stats
            self._update_group_stats(group_id, fee, cash_impact if not is_opening else None)

            # Step 9: Check if group should be closed
            group_status = self._check_and_close_group(group_id)

            logger.info(
                f"[LEDGER] Recorded fill: user={user_id}, group={group_id}, "
                f"leg={leg_id}, fill={fill_id}, action={action}, status={group_status}"
            )

            return {
                "success": True,
                "group_id": group_id,
                "leg_id": leg_id,
                "fill_id": fill_id,
                "event_id": event_id,
                "group_status": group_status,
            }

        except Exception as e:
            logger.error(f"[LEDGER] Error recording fill: {e}")
            return {"success": False, "error": str(e)}

    # -------------------------------------------------------------------------
    # Reconciliation
    # -------------------------------------------------------------------------

    def reconcile_snapshot(
        self,
        user_id: str,
        snapshot_rows: List[Dict[str, Any]],
        run_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Reconcile canonical ledger against broker snapshot.

        Args:
            user_id: User UUID
            snapshot_rows: Broker positions from `positions` table
                [{"symbol": "AAPL", "qty": 100, ...}, ...]
            run_id: Optional reconciliation run ID (generated if not provided)

        Returns:
            Dict with:
                run_id: str
                breaks_found: int
                breaks: List[Dict]
                ledger_positions: int
                broker_positions: int
        """
        try:
            run_id = run_id or str(uuid.uuid4())
            run_at = datetime.now(timezone.utc).isoformat()
            breaks = []

            # Get ledger positions (aggregate by symbol from open groups)
            ledger_positions = self._get_ledger_positions_by_symbol(user_id)

            # Build broker position map (symbol -> qty)
            broker_positions = {}
            for row in snapshot_rows:
                symbol = row.get("symbol")
                qty = int(row.get("qty", 0) or row.get("quantity", 0))
                if symbol:
                    broker_positions[symbol] = broker_positions.get(symbol, 0) + qty

            all_symbols = set(ledger_positions.keys()) | set(broker_positions.keys())

            for symbol in all_symbols:
                ledger_qty = ledger_positions.get(symbol, 0)
                broker_qty = broker_positions.get(symbol, 0)

                if ledger_qty == broker_qty:
                    continue  # No break

                # Determine break type
                if ledger_qty != 0 and broker_qty == 0:
                    break_type = "MISSING_IN_BROKER"
                elif ledger_qty == 0 and broker_qty != 0:
                    break_type = "MISSING_IN_LEDGER"
                else:
                    break_type = "QTY_MISMATCH"

                # Get underlying from symbol
                underlying = self._extract_underlying(symbol)

                break_record = {
                    "user_id": user_id,
                    "run_id": run_id,
                    "run_at": run_at,
                    "break_type": break_type,
                    "symbol": symbol,
                    "underlying": underlying,
                    "ledger_qty": ledger_qty,
                    "broker_qty": broker_qty,
                    "qty_diff": ledger_qty - broker_qty,
                }
                breaks.append(break_record)

            # Insert breaks to DB
            if breaks:
                self.client.table("reconciliation_breaks").insert(breaks).execute()

            logger.info(
                f"[LEDGER] Reconciliation complete: user={user_id}, "
                f"run_id={run_id}, breaks={len(breaks)}"
            )

            return {
                "run_id": run_id,
                "breaks_found": len(breaks),
                "breaks": breaks,
                "ledger_positions": len(ledger_positions),
                "broker_positions": len(broker_positions),
            }

        except Exception as e:
            logger.error(f"[LEDGER] Reconciliation error: {e}")
            return {
                "run_id": run_id,
                "error": str(e),
                "breaks_found": 0,
                "breaks": [],
            }

    # -------------------------------------------------------------------------
    # Placeholder methods for future events
    # -------------------------------------------------------------------------

    def record_assignment(
        self,
        user_id: str,
        group_id: str,
        leg_id: str,
        assignment_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Record an option assignment event.
        Placeholder for future broker API integration.
        """
        # TODO: Implement assignment handling
        # - Update leg to ASSIGNED status
        # - Create stock leg for exercise/assignment
        # - Insert ASSIGNMENT event
        logger.warning("[LEDGER] record_assignment not yet implemented")
        return {"success": False, "error": "not_implemented"}

    def record_exercise(
        self,
        user_id: str,
        group_id: str,
        leg_id: str,
        exercise_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Record an option exercise event.
        Placeholder for future broker API integration.
        """
        logger.warning("[LEDGER] record_exercise not yet implemented")
        return {"success": False, "error": "not_implemented"}

    def record_expiration(
        self,
        user_id: str,
        group_id: str,
        leg_id: str,
        expiration_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Record an option expiration event.
        Placeholder for future broker API integration.
        """
        logger.warning("[LEDGER] record_expiration not yet implemented")
        return {"success": False, "error": "not_implemented"}

    # -------------------------------------------------------------------------
    # Private: Group management
    # -------------------------------------------------------------------------

    def _find_or_create_group(
        self,
        user_id: str,
        underlying: str,
        legs_fingerprint: Optional[str],
        strategy_key: Optional[str],
        trace_id: Optional[str],
        strategy: Optional[str],
        window: Optional[str],
        regime: Optional[str],
        model_version: Optional[str],
        features_hash: Optional[str],
    ) -> Dict[str, Any]:
        """Find existing OPEN group or create new one."""

        # Try to find by legs_fingerprint first (most specific)
        if legs_fingerprint:
            result = self.client.table("position_groups") \
                .select("*") \
                .eq("user_id", user_id) \
                .eq("legs_fingerprint", legs_fingerprint) \
                .eq("status", "OPEN") \
                .limit(1) \
                .execute()
            if result.data and len(result.data) > 0:
                return result.data[0]

        # Fallback: find by strategy_key + underlying
        if strategy_key:
            result = self.client.table("position_groups") \
                .select("*") \
                .eq("user_id", user_id) \
                .eq("strategy_key", strategy_key) \
                .eq("underlying", underlying) \
                .eq("status", "OPEN") \
                .limit(1) \
                .execute()
            if result.data and len(result.data) > 0:
                return result.data[0]

        # Create new group
        new_group = {
            "user_id": user_id,
            "underlying": underlying,
            "legs_fingerprint": legs_fingerprint,
            "strategy_key": strategy_key,
            "trace_id": trace_id,
            "strategy": strategy,
            "window": window,
            "regime": regime,
            "model_version": model_version,
            "features_hash": features_hash,
            "status": "OPEN",
            "fees_paid": 0,
        }

        result = self.client.table("position_groups").insert(new_group).execute()
        if result.data and len(result.data) > 0:
            logger.info(f"[LEDGER] Created new group: {result.data[0]['id']}")
            return result.data[0]

        raise Exception("Failed to create position group")

    # -------------------------------------------------------------------------
    # Private: Leg management
    # -------------------------------------------------------------------------

    def _find_or_create_leg_by_symbol(
        self,
        group_id: str,
        user_id: str,
        symbol: str,
        underlying: str,
        right: str,
        strike: Optional[float],
        expiry: Optional[str],
        multiplier: int,
        action: str,
    ) -> Tuple[Dict[str, Any], bool]:
        """
        Find existing leg by (group_id, symbol) or create new one.

        Leg orientation (LONG/SHORT) is determined on FIRST fill only:
        - BUY first -> LONG
        - SELL first -> SHORT

        Returns:
            Tuple of (leg_dict, is_new_leg)
        """
        # Find existing leg by group_id and symbol (NOT by side)
        result = self.client.table("position_legs") \
            .select("*") \
            .eq("group_id", group_id) \
            .eq("symbol", symbol) \
            .limit(1) \
            .execute()

        if result.data and len(result.data) > 0:
            return result.data[0], False

        # Create new leg - determine orientation from first fill action
        # BUY first -> LONG position, SELL first -> SHORT position
        leg_side = "LONG" if action == "BUY" else "SHORT"

        new_leg = {
            "group_id": group_id,
            "user_id": user_id,
            "symbol": symbol,
            "underlying": underlying,
            "right": right,
            "strike": float(strike) if strike else None,
            "expiry": expiry,
            "multiplier": multiplier,
            "side": leg_side,
            "qty_opened": 0,
            "qty_closed": 0,
        }

        result = self.client.table("position_legs").insert(new_leg).execute()
        if result.data and len(result.data) > 0:
            logger.info(f"[LEDGER] Created new leg: {result.data[0]['id']}, side={leg_side}")
            return result.data[0], True

        raise Exception("Failed to create position leg")

    def _find_or_create_leg(
        self,
        group_id: str,
        user_id: str,
        symbol: str,
        underlying: str,
        right: str,
        strike: Optional[float],
        expiry: Optional[str],
        multiplier: int,
        side: str,
    ) -> Dict[str, Any]:
        """
        DEPRECATED: Use _find_or_create_leg_by_symbol instead.
        Kept for backward compatibility.
        """
        # Map side to action for the new method
        action = "BUY" if side == "LONG" else "SELL"
        leg, _ = self._find_or_create_leg_by_symbol(
            group_id=group_id,
            user_id=user_id,
            symbol=symbol,
            underlying=underlying,
            right=right,
            strike=strike,
            expiry=expiry,
            multiplier=multiplier,
            action=action,
        )
        return leg

    def _is_opening_fill_v2(self, leg_side: str, action: str) -> bool:
        """
        Determine if fill is opening or closing based on leg orientation and action.

        For LONG leg:
          - BUY increases position (opening)
          - SELL decreases position (closing)

        For SHORT leg:
          - SELL increases position (opening)
          - BUY decreases position (closing)
        """
        if leg_side == "LONG":
            return action == "BUY"
        else:  # SHORT
            return action == "SELL"

    def _is_opening_fill(self, leg: Dict[str, Any], fill_side: str) -> bool:
        """
        DEPRECATED: Use _is_opening_fill_v2 instead.
        Kept for backward compatibility.
        """
        leg_side = leg.get("side")  # "LONG" or "SHORT"
        action = "BUY" if fill_side == "buy" else "SELL"
        return self._is_opening_fill_v2(leg_side, action)

    def _handle_over_close(
        self,
        user_id: str,
        trade_execution_id: Optional[str],
        group_id: str,
        leg: Dict[str, Any],
        action: str,
        total_qty: int,
        close_qty: int,
        price: Decimal,
        fee: Decimal,
        filled_at: str,
        broker_exec_id: Optional[str],
        source: str,
        context: Dict[str, Any],
        fill_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Handle over-close scenario where closing qty exceeds current position.

        Strategy:
        1. Close the current position with close_qty
        2. Open a new group with the remainder (total_qty - close_qty)
           with opposite orientation
        """
        remainder_qty = total_qty - close_qty
        leg_id = leg["id"]
        leg_side = leg["side"]

        logger.info(
            f"[LEDGER] Over-close detected: closing {close_qty}, "
            f"opening new position with {remainder_qty}"
        )

        # Proportionally split fee between close and open
        fee_per_unit = fee / total_qty if total_qty > 0 else Decimal(0)
        close_fee = fee_per_unit * close_qty
        open_fee = fee_per_unit * remainder_qty

        results = {"close": None, "open": None}

        # Step 1: Close current position (if any qty to close)
        if close_qty > 0:
            close_fill_id = self._insert_fill(
                user_id=user_id,
                group_id=group_id,
                leg_id=leg_id,
                trade_execution_id=trade_execution_id,
                broker_exec_id=broker_exec_id,  # Use original broker_exec_id for first fill
                action=action,
                side=leg_side,
                qty=close_qty,
                price=price,
                fee=close_fee,
                filled_at=filled_at,
                source=source,
            )

            self._update_leg_quantities(
                leg_id=leg_id,
                qty=close_qty,
                price=price,
                is_opening=False,
            )

            cash_impact = self._compute_cash_impact(
                action=action,
                qty=close_qty,
                price=price,
                fee=close_fee,
                multiplier=int(fill_data.get("multiplier", 100)),
            )

            event_key = self._build_event_key(
                trade_execution_id, fill_data.get("symbol"), action, filled_at, close_qty, price
            )
            event_id = self._insert_event(
                user_id=user_id,
                group_id=group_id,
                fill_id=close_fill_id,
                leg_id=leg_id,
                event_type="FILL",
                amount_cash=cash_impact,
                qty_delta=-close_qty if action == "SELL" else close_qty,
                event_key=event_key,
            )

            self._update_group_stats(group_id, close_fee, cash_impact)
            group_status = self._check_and_close_group(group_id)

            results["close"] = {
                "group_id": group_id,
                "leg_id": leg_id,
                "fill_id": close_fill_id,
                "event_id": event_id,
                "group_status": group_status,
                "qty": close_qty,
            }

        # Step 2: Open new group with remainder (opposite orientation)
        if remainder_qty > 0:
            # New fill data with remainder qty
            new_fill_data = fill_data.copy()
            new_fill_data["qty"] = remainder_qty
            new_fill_data["fee"] = float(open_fee)
            new_fill_data["action"] = action
            new_fill_data["broker_exec_id"] = None  # New fill, no broker ID

            # Clear strategy_key/legs_fingerprint to create new group
            new_context = context.copy()
            new_context["strategy_key"] = None
            new_context["legs_fingerprint"] = None

            open_result = self.record_fill(
                user_id=user_id,
                trade_execution_id=trade_execution_id,
                fill_data=new_fill_data,
                context=new_context,
            )
            results["open"] = open_result

        # Return combined result
        return {
            "success": True,
            "group_id": results["close"]["group_id"] if results["close"] else results["open"]["group_id"],
            "leg_id": results["close"]["leg_id"] if results["close"] else results["open"]["leg_id"],
            "fill_id": results["close"]["fill_id"] if results["close"] else results["open"]["fill_id"],
            "event_id": results["close"]["event_id"] if results["close"] else results["open"]["event_id"],
            "group_status": results["close"]["group_status"] if results["close"] else "OPEN",
            "over_close": True,
            "close_result": results["close"],
            "open_result": results["open"],
        }

    def _update_leg_quantities(
        self,
        leg_id: str,
        qty: int,
        price: Decimal,
        is_opening: bool,
    ):
        """Update leg quantities and average cost."""

        # Get current leg state
        result = self.client.table("position_legs") \
            .select("qty_opened, qty_closed, avg_cost_open, avg_cost_close") \
            .eq("id", leg_id) \
            .single() \
            .execute()

        leg = result.data
        qty_opened = leg.get("qty_opened", 0)
        qty_closed = leg.get("qty_closed", 0)
        avg_cost_open = Decimal(str(leg.get("avg_cost_open") or 0))
        avg_cost_close = Decimal(str(leg.get("avg_cost_close") or 0))

        if is_opening:
            # Update opening quantities and average cost
            new_qty_opened = qty_opened + qty
            if qty_opened == 0:
                new_avg_cost_open = price
            else:
                # Weighted average
                total_cost = (avg_cost_open * qty_opened) + (price * qty)
                new_avg_cost_open = total_cost / new_qty_opened

            self.client.table("position_legs").update({
                "qty_opened": new_qty_opened,
                "avg_cost_open": float(new_avg_cost_open),
            }).eq("id", leg_id).execute()
        else:
            # Update closing quantities and average cost
            new_qty_closed = qty_closed + qty
            if qty_closed == 0:
                new_avg_cost_close = price
            else:
                total_cost = (avg_cost_close * qty_closed) + (price * qty)
                new_avg_cost_close = total_cost / new_qty_closed

            self.client.table("position_legs").update({
                "qty_closed": new_qty_closed,
                "avg_cost_close": float(new_avg_cost_close),
            }).eq("id", leg_id).execute()

    # -------------------------------------------------------------------------
    # Private: Fill management
    # -------------------------------------------------------------------------

    def _insert_fill(
        self,
        user_id: str,
        group_id: str,
        leg_id: str,
        trade_execution_id: Optional[str],
        broker_exec_id: Optional[str],
        action: str,
        side: str,
        qty: int,
        price: Decimal,
        fee: Decimal,
        filled_at: str,
        source: str,
    ) -> str:
        """Insert a fill record."""

        fill_data = {
            "user_id": user_id,
            "group_id": group_id,
            "leg_id": leg_id,
            "trade_execution_id": trade_execution_id,
            "broker_exec_id": broker_exec_id,
            "action": action,  # BUY or SELL
            "side": side,      # LONG or SHORT (deprecated, kept for compat)
            "qty": qty,
            "price": float(price),
            "fee": float(fee),
            "filled_at": filled_at,
            "source": source,
        }

        result = self.client.table("fills").insert(fill_data).execute()
        if result.data and len(result.data) > 0:
            return result.data[0]["id"]

        raise Exception("Failed to insert fill")

    def _check_fill_exists_by_broker_id(
        self, user_id: str, broker_exec_id: str
    ) -> Optional[Dict[str, Any]]:
        """Check if fill with broker_exec_id already exists."""
        result = self.client.table("fills") \
            .select("id, group_id, leg_id") \
            .eq("user_id", user_id) \
            .eq("broker_exec_id", broker_exec_id) \
            .limit(1) \
            .execute()

        if result.data and len(result.data) > 0:
            return result.data[0]
        return None

    # -------------------------------------------------------------------------
    # Private: Event management
    # -------------------------------------------------------------------------

    def _insert_event(
        self,
        user_id: str,
        group_id: str,
        fill_id: Optional[str],
        leg_id: Optional[str],
        event_type: str,
        amount_cash: Decimal,
        qty_delta: int,
        event_key: Optional[str],
    ) -> str:
        """Insert a position event."""

        event_data = {
            "user_id": user_id,
            "group_id": group_id,
            "fill_id": fill_id,
            "leg_id": leg_id,
            "event_type": event_type,
            "amount_cash": float(amount_cash),
            "qty_delta": qty_delta,
            "event_key": event_key,
        }

        result = self.client.table("position_events").insert(event_data).execute()
        if result.data and len(result.data) > 0:
            return result.data[0]["id"]

        raise Exception("Failed to insert position event")

    def _check_event_exists(
        self, user_id: str, event_key: str
    ) -> Optional[Dict[str, Any]]:
        """Check if event with event_key already exists."""
        result = self.client.table("position_events") \
            .select("id, group_id, fill_id") \
            .eq("user_id", user_id) \
            .eq("event_key", event_key) \
            .limit(1) \
            .execute()

        if result.data and len(result.data) > 0:
            return result.data[0]
        return None

    def _build_event_key(
        self,
        trade_execution_id: Optional[str],
        symbol: str,
        action: str,
        filled_at: str,
        qty: int,
        price: Decimal,
    ) -> Optional[str]:
        """Build deterministic event key for idempotency."""
        if trade_execution_id:
            return f"fill:{trade_execution_id}:{symbol}:{action}:{filled_at}:{qty}:{price}"
        return None  # No event_key for broker-imported fills without execution ID

    # -------------------------------------------------------------------------
    # Private: Group stats
    # -------------------------------------------------------------------------

    def _update_group_stats(
        self,
        group_id: str,
        fee: Decimal,
        realized_amount: Optional[Decimal]
    ):
        """Update group materialized stats."""

        # Get current stats
        result = self.client.table("position_groups") \
            .select("fees_paid, realized_pnl") \
            .eq("id", group_id) \
            .single() \
            .execute()

        current = result.data
        fees_paid = Decimal(str(current.get("fees_paid") or 0))
        realized_pnl = Decimal(str(current.get("realized_pnl") or 0))

        new_fees_paid = fees_paid + fee
        updates = {"fees_paid": float(new_fees_paid)}

        if realized_amount is not None:
            new_realized_pnl = realized_pnl + realized_amount
            updates["realized_pnl"] = float(new_realized_pnl)

        self.client.table("position_groups").update(updates).eq("id", group_id).execute()

    def _check_and_close_group(self, group_id: str) -> str:
        """Check if all legs closed and update group status."""

        # Check if any legs have remaining quantity
        result = self.client.table("position_legs") \
            .select("qty_opened, qty_closed") \
            .eq("group_id", group_id) \
            .execute()

        all_closed = True
        for leg in result.data or []:
            qty_remaining = leg.get("qty_opened", 0) - leg.get("qty_closed", 0)
            if qty_remaining > 0:
                all_closed = False
                break

        if all_closed:
            self.client.table("position_groups").update({
                "status": "CLOSED",
                "closed_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", group_id).execute()
            return "CLOSED"

        return "OPEN"

    # -------------------------------------------------------------------------
    # Private: Reconciliation helpers
    # -------------------------------------------------------------------------

    def _get_ledger_positions_by_symbol(self, user_id: str) -> Dict[str, int]:
        """Get current ledger positions aggregated by symbol."""

        # Get all legs from OPEN groups
        result = self.client.table("position_legs") \
            .select("symbol, qty_opened, qty_closed, side, group_id") \
            .eq("user_id", user_id) \
            .execute()

        # Filter to only legs from OPEN groups
        open_groups = self.client.table("position_groups") \
            .select("id") \
            .eq("user_id", user_id) \
            .eq("status", "OPEN") \
            .execute()

        open_group_ids = {g["id"] for g in (open_groups.data or [])}

        positions = {}
        for leg in result.data or []:
            if leg.get("group_id") not in open_group_ids:
                continue

            symbol = leg.get("symbol")
            qty_opened = leg.get("qty_opened", 0)
            qty_closed = leg.get("qty_closed", 0)
            side = leg.get("side")

            qty_remaining = qty_opened - qty_closed
            if side == "SHORT":
                qty_remaining = -qty_remaining

            positions[symbol] = positions.get(symbol, 0) + qty_remaining

        return positions

    # -------------------------------------------------------------------------
    # Private: Utility
    # -------------------------------------------------------------------------

    def _extract_underlying(self, symbol: str) -> str:
        """Extract underlying from option symbol or return as-is for stock."""
        if not symbol:
            return "UNKNOWN"

        # Options symbols are typically like "AAPL240119C00150000"
        # Stock symbols are just letters like "AAPL"
        if len(symbol) > 10 and any(c.isdigit() for c in symbol):
            # Likely an option symbol, extract letters at start
            underlying = ""
            for c in symbol:
                if c.isalpha():
                    underlying += c
                else:
                    break
            return underlying or symbol

        return symbol

    def _compute_cash_impact(
        self,
        action: str,
        qty: int,
        price: Decimal,
        fee: Decimal,
        multiplier: int,
    ) -> Decimal:
        """
        Compute cash impact of a fill.

        Args:
            action: "BUY" or "SELL"
            qty: Quantity filled
            price: Fill price per unit
            fee: Fee for this fill
            multiplier: Contract multiplier (100 for options, 1 for stock)

        Returns:
            Cash impact (negative for outflow, positive for inflow)
        """
        notional = price * qty * multiplier

        if action == "BUY":
            # Buying: cash outflow (negative)
            return -(notional + fee)
        else:
            # Selling: cash inflow (positive)
            return notional - fee
