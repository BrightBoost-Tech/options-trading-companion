"""
Position PnL Service (v4 Accounting)

Handles mark-to-market snapshots and unrealized PnL computation for the v4 ledger.

Features:
- Refresh marks for all open positions
- Compute unrealized PnL per leg
- Aggregate group-level NLV (Net Liquidation Value)

Usage:
    from packages.quantum.services.position_pnl_service import PositionPnLService

    pnl = PositionPnLService(supabase_client, api_key)
    result = pnl.refresh_marks_for_user(user_id)
"""

import logging
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class PositionPnLService:
    """
    Manages mark-to-market snapshots and unrealized PnL for position legs.

    Tables managed:
    - position_leg_marks: Point-in-time mark snapshots
    - position_legs: Updates last_mark_* and unrealized_pnl columns
    - position_groups: Updates unrealized_pnl and net_liquidation_value
    """

    def __init__(self, supabase_client, api_key: Optional[str] = None):
        """
        Initialize the PnL service.

        Args:
            supabase_client: Supabase client (service_role for background jobs)
            api_key: Polygon API key (optional, falls back to env var)
        """
        self.client = supabase_client
        self.api_key = api_key or os.getenv("POLYGON_API_KEY")

    # -------------------------------------------------------------------------
    # Core: refresh_marks_for_user
    # -------------------------------------------------------------------------

    def refresh_marks_for_user(
        self,
        user_id: str,
        group_ids: Optional[List[str]] = None,
        source: str = "MARKET",
        max_symbols: Optional[int] = None,
        batch_size: int = 50,
        max_groups: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Refresh marks for all open position legs for a user.

        Fetches current market quotes, inserts mark snapshots, and updates
        materialized columns (last_mark_*, unrealized_pnl).

        Args:
            user_id: User UUID
            group_ids: Optional list of specific group IDs to refresh
                       If None, refreshes all open groups for the user
            source: Mark source label (MARKET, EOD, MANUAL)
            max_symbols: Optional cap on symbols to fetch (deterministic truncation)
            batch_size: Batch size for quote fetching (default 50)
            max_groups: Optional cap on groups to process

        Returns:
            Dict with:
                success: bool
                legs_marked: int
                groups_updated: int
                marks_inserted: int
                errors: List[str]
                diagnostics: Dict with timing, quota, and throttle info
        """
        start_time = datetime.now(timezone.utc)
        errors = []
        marks_inserted = 0
        legs_marked = 0
        groups_updated = set()
        stale_skips = 0
        missing_quote_skips = 0

        try:
            # 1. Get all open legs for the user (or specific groups)
            legs = self._get_open_legs(user_id, group_ids, max_groups=max_groups)

            if not legs:
                return {
                    "success": True,
                    "legs_marked": 0,
                    "groups_updated": 0,
                    "marks_inserted": 0,
                    "errors": [],
                    "diagnostics": {
                        "duration_ms": self._duration_ms(start_time),
                        "message": "No open legs found",
                        "symbols_requested_total": 0,
                        "symbols_processed": 0,
                        "batches": 0,
                        "stale_skips": 0,
                        "missing_quote_skips": 0
                    }
                }

            # 2. Collect unique symbols for batch quote fetch (sorted for determinism)
            all_symbols = sorted(set(leg["symbol"] for leg in legs))
            symbols_requested_total = len(all_symbols)

            # Apply max_symbols cap (deterministic truncation on sorted list)
            if max_symbols is not None and len(all_symbols) > max_symbols:
                symbols_to_fetch = all_symbols[:max_symbols]
                logger.info(f"Truncated symbols from {len(all_symbols)} to {max_symbols}")
            else:
                symbols_to_fetch = all_symbols

            logger.info(f"Refreshing marks for {len(legs)} legs ({len(symbols_to_fetch)} symbols to fetch)")

            # 3. Fetch quotes in batches
            quotes = self._fetch_quotes_batched(symbols_to_fetch, batch_size)
            batches_used = (len(symbols_to_fetch) + batch_size - 1) // batch_size if symbols_to_fetch else 0

            if not quotes:
                return {
                    "success": False,
                    "legs_marked": 0,
                    "groups_updated": 0,
                    "marks_inserted": 0,
                    "errors": ["No quotes fetched - check API key or connectivity"],
                    "diagnostics": {
                        "duration_ms": self._duration_ms(start_time),
                        "symbols_requested_total": symbols_requested_total,
                        "symbols_processed": 0,
                        "batches": batches_used,
                        "stale_skips": 0,
                        "missing_quote_skips": 0
                    }
                }

            # 4. Process each leg
            marked_at = datetime.now(timezone.utc)
            for leg in legs:
                symbol = leg["symbol"]

                # Skip if symbol wasn't in our fetch list (truncation case)
                if symbol not in quotes and symbol not in symbols_to_fetch:
                    continue

                try:
                    result = self._mark_leg(leg, quotes, marked_at, source)
                    if result.get("success"):
                        marks_inserted += 1
                        legs_marked += 1
                        groups_updated.add(leg["group_id"])
                    else:
                        error_msg = result.get('error', 'Unknown error')
                        if "Stale quote" in error_msg:
                            stale_skips += 1
                        elif "No quote" in error_msg or "No valid mid" in error_msg:
                            missing_quote_skips += 1
                        errors.append(f"Leg {leg['id']}: {error_msg}")
                except Exception as e:
                    errors.append(f"Leg {leg['id']}: {str(e)}")
                    logger.warning(f"Error marking leg {leg['id']}: {e}")

            # 5. Update group-level aggregates
            for group_id in groups_updated:
                try:
                    self._update_group_pnl(group_id, marked_at)
                except Exception as e:
                    errors.append(f"Group {group_id}: {str(e)}")
                    logger.warning(f"Error updating group PnL {group_id}: {e}")

            return {
                "success": len(errors) == 0,
                "legs_marked": legs_marked,
                "groups_updated": len(groups_updated),
                "marks_inserted": marks_inserted,
                "errors": errors[:10],  # Cap errors for payload size
                "diagnostics": {
                    "duration_ms": self._duration_ms(start_time),
                    "symbols_requested_total": symbols_requested_total,
                    "symbols_processed": len(symbols_to_fetch),
                    "quotes_received": len(quotes),
                    "batches": batches_used,
                    "total_legs": len(legs),
                    "stale_skips": stale_skips,
                    "missing_quote_skips": missing_quote_skips
                }
            }

        except Exception as e:
            logger.error(f"refresh_marks_for_user failed: {e}")
            return {
                "success": False,
                "legs_marked": legs_marked,
                "groups_updated": len(groups_updated),
                "marks_inserted": marks_inserted,
                "errors": [str(e)],
                "diagnostics": {
                    "duration_ms": self._duration_ms(start_time),
                    "stale_skips": stale_skips,
                    "missing_quote_skips": missing_quote_skips
                }
            }

    # -------------------------------------------------------------------------
    # Core: compute_group_nlv
    # -------------------------------------------------------------------------

    def compute_group_nlv(self, group_id: str) -> Dict[str, Any]:
        """
        Compute Net Liquidation Value for a position group.

        NLV = realized_pnl + unrealized_pnl - fees_paid

        Args:
            group_id: Position group UUID

        Returns:
            Dict with:
                success: bool
                nlv: Decimal or None
                realized_pnl: Decimal or None
                unrealized_pnl: Decimal or None
                fees_paid: Decimal or None
                error: str (if failed)
        """
        try:
            # Get group with current values
            result = self.client.table("position_groups").select(
                "id, realized_pnl, unrealized_pnl, fees_paid, net_liquidation_value"
            ).eq("id", group_id).single().execute()

            if not result.data:
                return {
                    "success": False,
                    "error": f"Group not found: {group_id}"
                }

            group = result.data
            realized = Decimal(str(group.get("realized_pnl") or 0))
            unrealized = Decimal(str(group.get("unrealized_pnl") or 0))
            fees = Decimal(str(group.get("fees_paid") or 0))

            nlv = realized + unrealized - fees

            return {
                "success": True,
                "nlv": float(nlv),
                "realized_pnl": float(realized),
                "unrealized_pnl": float(unrealized),
                "fees_paid": float(fees)
            }

        except Exception as e:
            logger.error(f"compute_group_nlv failed for {group_id}: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    # -------------------------------------------------------------------------
    # Core: compute_leg_unrealized_pnl
    # -------------------------------------------------------------------------

    def compute_leg_unrealized_pnl(
        self,
        side: str,
        avg_cost_open: Optional[float],
        mark_mid: Optional[float],
        qty_current: int,
        multiplier: int = 100
    ) -> Optional[float]:
        """
        Compute unrealized PnL for a single leg.

        Formula:
            LONG:  (mark - cost) * qty * multiplier
            SHORT: (cost - mark) * abs(qty) * multiplier

        Args:
            side: "LONG" or "SHORT"
            avg_cost_open: Average open cost per unit
            mark_mid: Current mid price
            qty_current: Current quantity (signed, negative for short)
            multiplier: Contract multiplier (default 100)

        Returns:
            Unrealized PnL as float, or None if inputs invalid
        """
        if mark_mid is None or avg_cost_open is None or qty_current == 0:
            return None

        if side == "LONG":
            return (mark_mid - avg_cost_open) * qty_current * multiplier
        else:
            return (avg_cost_open - mark_mid) * abs(qty_current) * multiplier

    # -------------------------------------------------------------------------
    # Internal: _get_open_legs
    # -------------------------------------------------------------------------

    def _get_open_legs(
        self,
        user_id: str,
        group_ids: Optional[List[str]] = None,
        max_groups: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get all open position legs for a user."""
        # If max_groups is set and no specific group_ids provided, fetch limited groups first
        if max_groups is not None and not group_ids:
            groups_result = self.client.table("position_groups").select(
                "id"
            ).eq("user_id", user_id).eq("status", "OPEN").order(
                "created_at", desc=False
            ).limit(max_groups).execute()

            if not groups_result.data:
                return []

            group_ids = [g["id"] for g in groups_result.data]

        query = self.client.table("position_legs").select(
            "id, group_id, user_id, symbol, underlying, side, "
            "qty_opened, qty_closed, qty_current, avg_cost_open, multiplier"
        ).eq("user_id", user_id)

        if group_ids:
            query = query.in_("group_id", group_ids)

        # Only legs with open quantity
        # qty_current != 0 means (qty_opened - qty_closed) > 0
        query = query.neq("qty_current", 0)

        result = query.execute()
        return result.data or []

    # -------------------------------------------------------------------------
    # Internal: _fetch_quotes_batched
    # -------------------------------------------------------------------------

    def _fetch_quotes_batched(
        self,
        symbols: List[str],
        batch_size: int = 50
    ) -> Dict[str, Dict[str, Any]]:
        """
        Fetch quotes for a list of symbols in batches using MarketDataTruthLayer.

        Args:
            symbols: List of symbols to fetch
            batch_size: Number of symbols per batch (default 50)

        Returns:
            Dict mapping symbol -> quote data with bid, ask, mid, last, quality
        """
        if not self.api_key:
            logger.warning("No POLYGON_API_KEY configured, cannot fetch quotes")
            return {}

        if not symbols:
            return {}

        all_quotes = {}

        try:
            from packages.quantum.services.market_data_truth_layer import MarketDataTruthLayer

            layer = MarketDataTruthLayer(api_key=self.api_key)

            # Process in batches
            for i in range(0, len(symbols), batch_size):
                batch = symbols[i:i + batch_size]
                logger.debug(f"Fetching batch {i // batch_size + 1}: {len(batch)} symbols")

                snapshots = layer.snapshot_many_v4(batch)

                for symbol, snap in snapshots.items():
                    if snap:
                        all_quotes[symbol] = {
                            "bid": snap.quote.bid,
                            "ask": snap.quote.ask,
                            "mid": snap.quote.mid,
                            "last": snap.quote.last,
                            "quality_score": snap.quality.quality_score,
                            "freshness_ms": snap.quality.freshness_ms,
                            "is_stale": snap.quality.is_stale
                        }

            return all_quotes

        except Exception as e:
            logger.error(f"Failed to fetch quotes: {e}")
            return all_quotes  # Return partial results if any

    # -------------------------------------------------------------------------
    # Internal: _fetch_quotes (legacy, single batch)
    # -------------------------------------------------------------------------

    def _fetch_quotes(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Fetch quotes for a list of symbols using MarketDataTruthLayer (single batch).

        Returns:
            Dict mapping symbol -> quote data with bid, ask, mid, last, quality
        """
        return self._fetch_quotes_batched(symbols, batch_size=len(symbols) if symbols else 1)

    # -------------------------------------------------------------------------
    # Internal: _mark_leg
    # -------------------------------------------------------------------------

    def _mark_leg(
        self,
        leg: Dict[str, Any],
        quotes: Dict[str, Dict[str, Any]],
        marked_at: datetime,
        source: str
    ) -> Dict[str, Any]:
        """
        Insert a mark snapshot for a leg and update materialized columns.

        Args:
            leg: Leg record from position_legs
            quotes: Dict of symbol -> quote data
            marked_at: Timestamp for the mark
            source: Mark source (MARKET, EOD, MANUAL)

        Returns:
            Dict with success, mark_id, unrealized_pnl
        """
        symbol = leg["symbol"]
        quote = quotes.get(symbol)

        if not quote:
            return {
                "success": False,
                "error": f"No quote for {symbol}"
            }

        # Don't mark stale quotes
        if quote.get("is_stale"):
            return {
                "success": False,
                "error": f"Stale quote for {symbol}"
            }

        mid = quote.get("mid")
        if mid is None:
            # Try to compute mid from bid/ask
            bid = quote.get("bid")
            ask = quote.get("ask")
            if bid is not None and ask is not None:
                mid = (bid + ask) / 2
            else:
                mid = quote.get("last")  # Fallback to last

        if mid is None:
            return {
                "success": False,
                "error": f"No valid mid price for {symbol}"
            }

        # 1. Insert mark snapshot
        mark_data = {
            "id": str(uuid.uuid4()),
            "user_id": leg["user_id"],
            "group_id": leg["group_id"],
            "leg_id": leg["id"],
            "symbol": symbol,
            "marked_at": marked_at.isoformat(),
            "bid": quote.get("bid"),
            "ask": quote.get("ask"),
            "mid": mid,
            "last": quote.get("last"),
            "quality_score": quote.get("quality_score"),
            "freshness_ms": quote.get("freshness_ms"),
            "source": source
        }

        mark_result = self.client.table("position_leg_marks").insert(mark_data).execute()

        if not mark_result.data:
            return {
                "success": False,
                "error": "Failed to insert mark"
            }

        mark_id = mark_result.data[0]["id"]

        # 2. Compute unrealized PnL
        unrealized_pnl = self.compute_leg_unrealized_pnl(
            side=leg["side"],
            avg_cost_open=leg.get("avg_cost_open"),
            mark_mid=mid,
            qty_current=leg["qty_current"],
            multiplier=leg.get("multiplier", 100)
        )

        # 3. Update leg with mark reference and PnL
        update_data = {
            "last_mark_id": mark_id,
            "last_mark_mid": mid,
            "last_mark_at": marked_at.isoformat(),
            "unrealized_pnl": unrealized_pnl
        }

        self.client.table("position_legs").update(update_data).eq(
            "id", leg["id"]
        ).execute()

        return {
            "success": True,
            "mark_id": mark_id,
            "unrealized_pnl": unrealized_pnl
        }

    # -------------------------------------------------------------------------
    # Internal: _update_group_pnl
    # -------------------------------------------------------------------------

    def _update_group_pnl(self, group_id: str, marked_at: datetime) -> None:
        """
        Update group-level unrealized_pnl and net_liquidation_value.

        Sums unrealized_pnl from all legs in the group.
        """
        # Get all legs for the group
        legs_result = self.client.table("position_legs").select(
            "unrealized_pnl"
        ).eq("group_id", group_id).execute()

        legs = legs_result.data or []

        # Sum unrealized PnL (handle None values)
        total_unrealized = Decimal("0")
        for leg in legs:
            if leg.get("unrealized_pnl") is not None:
                total_unrealized += Decimal(str(leg["unrealized_pnl"]))

        # Get group for realized_pnl and fees
        group_result = self.client.table("position_groups").select(
            "realized_pnl, fees_paid"
        ).eq("id", group_id).single().execute()

        if not group_result.data:
            logger.warning(f"Group not found for PnL update: {group_id}")
            return

        group = group_result.data
        realized = Decimal(str(group.get("realized_pnl") or 0))
        fees = Decimal(str(group.get("fees_paid") or 0))

        # NLV = realized + unrealized - fees
        nlv = realized + total_unrealized - fees

        # Update group
        self.client.table("position_groups").update({
            "unrealized_pnl": float(total_unrealized),
            "net_liquidation_value": float(nlv),
            "last_marked_at": marked_at.isoformat()
        }).eq("id", group_id).execute()

    # -------------------------------------------------------------------------
    # Internal: _duration_ms
    # -------------------------------------------------------------------------

    def _duration_ms(self, start_time: datetime) -> float:
        """Calculate duration in milliseconds from start_time to now."""
        elapsed = datetime.now(timezone.utc) - start_time
        return elapsed.total_seconds() * 1000


# =============================================================================
# Module-level convenience functions
# =============================================================================

def compute_leg_unrealized_pnl(
    side: str,
    avg_cost_open: Optional[float],
    mark_mid: Optional[float],
    qty_current: int,
    multiplier: int = 100
) -> Optional[float]:
    """
    Standalone function to compute unrealized PnL for a single leg.

    Formula:
        LONG:  (mark - cost) * qty * multiplier
        SHORT: (cost - mark) * abs(qty) * multiplier
    """
    if mark_mid is None or avg_cost_open is None or qty_current == 0:
        return None

    if side == "LONG":
        return (mark_mid - avg_cost_open) * qty_current * multiplier
    else:
        return (avg_cost_open - mark_mid) * abs(qty_current) * multiplier
