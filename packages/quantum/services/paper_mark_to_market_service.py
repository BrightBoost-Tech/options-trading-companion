"""
Paper Mark-to-Market Service

Refreshes current_mark and unrealized_pl on open paper_positions using
live option quotes, then saves an EOD snapshot for checkpoint evaluation.

Schedule: 3:30 PM CDT (before checkpoint), while quotes are still live.
"""

import logging
from datetime import datetime, timezone, date
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class PaperMarkToMarketService:
    """Fetches fresh quotes and marks open paper positions to market."""

    def __init__(self, supabase_client):
        self.client = supabase_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh_marks(self, user_id: str) -> Dict[str, Any]:
        """
        Fetch fresh quotes for all open positions and update current_mark + unrealized_pl.

        Uses the MarketDataTruthLayer's /v3/snapshot endpoint for Polygon,
        with automatic fallback to Alpaca's indicative options feed when
        Polygon returns empty bid/ask (plan doesn't include options quotes).

        Returns summary dict with positions_marked, errors, etc.
        """
        from packages.quantum.services.market_data_truth_layer import MarketDataTruthLayer

        truth_layer = MarketDataTruthLayer()
        positions = self._get_open_positions(user_id)

        if not positions:
            return {"status": "ok", "positions_marked": 0, "reason": "no_open_positions"}

        # Batch-fetch all leg symbols in one API call via truth layer
        all_leg_symbols = []
        for pos in positions:
            legs = pos.get("legs") or []
            for leg in legs:
                if isinstance(leg, dict):
                    sym = leg.get("occ_symbol") or leg.get("symbol", "")
                    if sym:
                        all_leg_symbols.append(sym)
            # Fallback: position-level symbol if no legs
            if not legs and pos.get("symbol"):
                all_leg_symbols.append(pos["symbol"])

        # Single batched snapshot call (uses /v3/snapshot with ticker.any_of)
        snapshots = truth_layer.snapshot_many(all_leg_symbols) if all_leg_symbols else {}

        marked = 0
        skipped = 0
        errors = []

        for pos in positions:
            pos_id = pos["id"]
            try:
                current_value = self._compute_position_value_from_snapshots(pos, snapshots)
                if current_value is None:
                    skipped += 1
                    errors.append({"position_id": pos_id, "error": "incomplete_quotes_skipped"})
                    continue

                qty = float(pos.get("quantity") or 1)
                multiplier = 100
                entry_value = float(pos["avg_entry_price"]) * abs(qty) * multiplier

                # For short positions (negative qty), value math is inverted:
                # entry_value = credit received, current_value = cost to close
                if qty < 0:
                    unrealized = entry_value - abs(current_value)
                else:
                    unrealized = current_value - entry_value

                per_contract_mark = current_value / (abs(qty) * multiplier) if qty != 0 else 0.0

                old_mark = pos.get("current_mark")
                old_upl = pos.get("unrealized_pl")
                mtm_msg = (
                    f"[MTM_DEBUG] position={pos_id} symbol={pos.get('symbol')} "
                    f"qty={qty} entry_value={entry_value} current_value={current_value} "
                    f"per_contract_mark={per_contract_mark} unrealized={unrealized} "
                    f"old_mark={old_mark} old_upl={old_upl}"
                )
                logger.info(mtm_msg)
                print(mtm_msg, flush=True)

                self.client.table("paper_positions").update({
                    "current_mark": per_contract_mark,
                    "unrealized_pl": unrealized,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", pos_id).execute()

                marked += 1

            except Exception as e:
                logger.error(f"[MARK_TO_MARKET] Failed to mark position {pos_id}: {e}")
                errors.append({"position_id": pos_id, "error": str(e)})

        if skipped:
            logger.info(
                f"[MARK_TO_MARKET] user={user_id} marked={marked} "
                f"skipped={skipped} (incomplete quotes) total={len(positions)}"
            )

        return {
            "status": "ok" if not errors else "partial",
            "positions_marked": marked,
            "positions_skipped": skipped,
            "errors": errors if errors else None,
            "total_positions": len(positions),
        }

    def save_eod_snapshot(self, user_id: str, snapshot_date: Optional[date] = None) -> Dict[str, Any]:
        """
        Save current unrealized_pl for all open positions as an EOD snapshot.
        Used by checkpoint to compute daily unrealized change.
        """
        snapshot_date = snapshot_date or date.today()
        positions = self._get_open_positions(user_id)

        if not positions:
            return {"status": "ok", "snapshots_saved": 0}

        saved = 0
        for pos in positions:
            try:
                self.client.table("paper_eod_snapshots").upsert({
                    "position_id": pos["id"],
                    "user_id": user_id,
                    "portfolio_id": pos["portfolio_id"],
                    "snapshot_date": snapshot_date.isoformat(),
                    "current_mark": pos.get("current_mark"),
                    "unrealized_pl": float(pos.get("unrealized_pl") or 0.0),
                }, on_conflict="position_id,snapshot_date").execute()
                saved += 1
            except Exception as e:
                logger.error(f"[MARK_TO_MARKET] Failed to save snapshot for position {pos['id']}: {e}")

        return {"status": "ok", "snapshots_saved": saved}

    def get_current_unrealized_total(self, user_id: str) -> float:
        """
        Sum unrealized_pl across all open paper positions for a user.
        Used by checkpoint to compute total_pnl = realized + unrealized.
        """
        positions = self._get_open_positions(user_id)
        return sum(float(p.get("unrealized_pl") or 0.0) for p in positions)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_open_positions(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all open paper positions for a user via portfolio join."""
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
                .neq("quantity", 0) \
                .execute()

            return pos_res.data or []
        except Exception as e:
            logger.error(f"[MARK_TO_MARKET] Failed to fetch positions for {user_id}: {e}")
            return []

    @staticmethod
    def _compute_position_value(
        position: Dict[str, Any],
        poly_service,
        is_valid_quote_fn,
    ) -> Optional[float]:
        """
        Compute current market value of a position from its legs' mid-prices.

        Returns total value in dollars, or None if ANY leg fails to get a
        valid quote.  Partial pricing of multi-leg positions is dangerous:
        a missing short-leg quote understates liabilities and overstates profit.
        """
        legs = position.get("legs") or []
        if not legs:
            # No legs — try to quote the symbol directly
            symbol = position.get("symbol", "")
            quote = poly_service.get_recent_quote(symbol)
            if not quote or not is_valid_quote_fn(quote):
                return None
            bid = float(quote.get("bid_price") or quote.get("bid") or 0)
            ask = float(quote.get("ask_price") or quote.get("ask") or 0)
            mid = (bid + ask) / 2.0 if (bid and ask) else 0.0
            if mid <= 0:
                return None
            qty = abs(float(position.get("quantity") or 1))
            return mid * 100 * qty

        # First pass: collect mid-prices for ALL legs.  If any leg fails,
        # abort the entire position — never partially price.
        leg_values: List[float] = []
        failed_legs: List[str] = []
        priceable_legs = 0

        for leg in legs:
            if isinstance(leg, str):
                continue  # Skip malformed leg entries

            occ_symbol = leg.get("occ_symbol") or leg.get("symbol", "")
            if not occ_symbol:
                continue

            priceable_legs += 1

            quote = poly_service.get_recent_quote(occ_symbol)
            if not quote or not is_valid_quote_fn(quote):
                failed_legs.append(occ_symbol)
                continue

            bid = float(quote.get("bid_price") or quote.get("bid") or 0)
            ask = float(quote.get("ask_price") or quote.get("ask") or 0)
            mid = (bid + ask) / 2.0 if (bid and ask) else 0.0
            if mid <= 0:
                failed_legs.append(occ_symbol)
                continue

            multiplier = 100
            leg_qty = float(leg.get("quantity") or position.get("quantity") or 1)
            action = leg.get("action", "buy")
            side_mult = 1.0 if action == "buy" else -1.0

            leg_values.append(mid * multiplier * abs(leg_qty) * side_mult)

        if priceable_legs == 0:
            return None

        # All-or-nothing: reject partial pricing
        if failed_legs:
            pos_id = position.get("id", "?")
            logger.warning(
                f"[MARK_TO_MARKET] Skipping position {pos_id}: "
                f"{len(failed_legs)}/{priceable_legs} legs failed to price "
                f"({', '.join(failed_legs)}). Keeping previous mark."
            )
            return None

        return sum(leg_values)

    @staticmethod
    def _compute_position_value_from_snapshots(
        position: Dict[str, Any],
        snapshots: Dict[str, Dict],
    ) -> Optional[float]:
        """
        Compute current market value from pre-fetched truth layer snapshots.

        Same all-or-nothing logic as _compute_position_value, but reads from
        the snapshot dict (keyed by normalized symbol) instead of making
        per-leg API calls. Uses /v3/snapshot which works for options on all
        Polygon plans (unlike /v3/quotes which requires Options add-on).
        """
        from packages.quantum.services.cache_key_builder import normalize_symbol

        legs = position.get("legs") or []
        if not legs:
            symbol = position.get("symbol", "")
            norm = normalize_symbol(symbol)
            snap = snapshots.get(norm, {})
            bid = float(snap.get("bid") or 0)
            ask = float(snap.get("ask") or 0)
            mid = (bid + ask) / 2.0 if (bid > 0 and ask > 0) else 0.0
            if mid <= 0:
                return None
            qty = abs(float(position.get("quantity") or 1))
            return mid * 100 * qty

        leg_values: List[float] = []
        failed_legs: List[str] = []
        priceable_legs = 0

        for leg in legs:
            if isinstance(leg, str):
                continue

            occ_symbol = leg.get("occ_symbol") or leg.get("symbol", "")
            if not occ_symbol:
                continue

            priceable_legs += 1
            norm = normalize_symbol(occ_symbol)
            snap = snapshots.get(norm, {})

            bid = float(snap.get("bid") or 0)
            ask = float(snap.get("ask") or 0)
            mid = (bid + ask) / 2.0 if (bid > 0 and ask > 0) else 0.0

            if mid <= 0:
                failed_legs.append(occ_symbol)
                continue

            multiplier = 100
            leg_qty = float(leg.get("quantity") or position.get("quantity") or 1)
            action = leg.get("action", "buy")
            side_mult = 1.0 if action == "buy" else -1.0

            leg_values.append(mid * multiplier * abs(leg_qty) * side_mult)

        if priceable_legs == 0:
            return None

        if failed_legs:
            pos_id = position.get("id", "?")
            logger.warning(
                f"[MARK_TO_MARKET] Skipping position {pos_id}: "
                f"{len(failed_legs)}/{priceable_legs} legs failed to price "
                f"({', '.join(failed_legs)}). Keeping previous mark."
            )
            return None

        return sum(leg_values)
