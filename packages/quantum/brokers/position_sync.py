"""
Position Sync Service — syncs positions from Alpaca and reconciles with internal state.

Gradual transition path from Plaid → Alpaca:
  POSITION_SOURCE=plaid     — Plaid only (current default)
  POSITION_SOURCE=hybrid    — Alpaca for automated, Plaid for manual
  POSITION_SOURCE=alpaca    — Alpaca only, Plaid disabled
"""

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def get_position_source() -> str:
    """Get configured position source."""
    return os.environ.get("POSITION_SOURCE", "plaid").lower()


class PositionSyncService:
    """
    Syncs positions from Alpaca and reconciles with internal state.
    Eventually replaces Plaid holdings sync.
    """

    def __init__(self, supabase, alpaca_client=None):
        self.supabase = supabase
        self.alpaca = alpaca_client
        self.source = get_position_source()

    def sync_from_alpaca(self, user_id: str) -> Dict[str, Any]:
        """
        Pull all positions from Alpaca → log and return.
        Does NOT overwrite internal paper_positions (those are managed by
        the execution pipeline). This is for reconciliation and visibility.
        """
        if not self.alpaca:
            return {"status": "no_alpaca_client"}

        try:
            positions = self.alpaca.get_option_positions()
            logger.info(
                f"[POS_SYNC] Fetched {len(positions)} option positions from Alpaca "
                f"for user={user_id}"
            )
            return {
                "status": "ok",
                "source": "alpaca",
                "count": len(positions),
                "positions": positions,
            }
        except Exception as e:
            logger.error(f"[POS_SYNC] Alpaca sync failed: {e}")
            return {"status": "error", "error": str(e)}

    def reconcile_plaid_vs_alpaca(self, user_id: str) -> Dict[str, Any]:
        """
        Compare Plaid holdings vs Alpaca positions.
        During transition, Plaid is source of truth for non-automated
        positions, Alpaca for automated ones.
        """
        from packages.quantum.brokers.alpaca_order_handler import reconcile_positions

        if not self.alpaca:
            return {"status": "no_alpaca_client"}

        return reconcile_positions(self.alpaca, self.supabase, user_id)

    def get_positions(
        self,
        user_id: str,
        source: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get positions from the configured source.

        source="auto": use POSITION_SOURCE env var
        source="alpaca": Alpaca only
        source="plaid": Plaid/internal only (legacy)
        source="internal": paper_positions table only
        """
        effective_source = source or self.source

        if effective_source == "alpaca" and self.alpaca:
            return self.sync_from_alpaca(user_id)

        if effective_source == "hybrid" and self.alpaca:
            # Merge: Alpaca for automated, internal for everything
            alpaca_result = self.sync_from_alpaca(user_id)
            internal_result = self._get_internal_positions(user_id)
            return {
                "status": "ok",
                "source": "hybrid",
                "alpaca": alpaca_result,
                "internal": internal_result,
            }

        # Default: internal paper_positions
        return self._get_internal_positions(user_id)

    def _get_internal_positions(self, user_id: str) -> Dict[str, Any]:
        """Get positions from paper_positions table."""
        try:
            port_res = self.supabase.table("paper_portfolios") \
                .select("id").eq("user_id", user_id).execute()
            if not port_res.data:
                return {"status": "ok", "source": "internal", "count": 0, "positions": []}

            p_ids = [p["id"] for p in port_res.data]
            pos_res = self.supabase.table("paper_positions") \
                .select("*") \
                .in_("portfolio_id", p_ids) \
                .eq("status", "open") \
                .neq("quantity", 0) \
                .execute()

            positions = pos_res.data or []
            return {
                "status": "ok",
                "source": "internal",
                "count": len(positions),
                "positions": positions,
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}
