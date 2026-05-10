from supabase import Client
from typing import Dict, Optional, TypedDict
import logging

from packages.quantum.execution.transaction_cost_model import TransactionCostModel as V3TCM  # noqa: F401  retained for downstream consumers
from packages.quantum.models import TradeTicket, OptionLeg  # noqa: F401  retained for downstream consumers
from packages.quantum.strategy_profiles import CostModelConfig  # noqa: F401  retained for downstream consumers

logger = logging.getLogger(__name__)


# #62a-D8 sweep deletion (2026-05-10):
#
# Removed alongside the dropped `trade_executions` table:
#   - module-level helpers _build_legs_fingerprint*,
#     _resolve_leg_action_standalone, _build_legs_fingerprint_with_fallback
#     (only used by the position-ledger recording chain below)
#   - ExecutionService.register_execution + private helpers
#     _record_to_position_ledger, _record_multi_leg_fills,
#     _record_single_leg_fill, _resolve_leg_action, _extract_underlying
#     (zero production callers; tests only)
#   - get_batch_execution_drag_stats, get_execution_drag_stats (read from
#     the dropped table; always returned {} since the table had zero rows
#     for its entire lifetime)
#   - simulate_fill (zero callers; TransactionCostModel has the live
#     simulate_fill that paper_endpoints + historical_simulation use)
#
# PRESERVED:
#   - ExecutionService class shell + __init__ minus self.executions_table
#   - ExecutionDragStats TypedDict (still used as a type hint by
#     downstream callers expecting the legacy shape; harmless residue)
#   - estimate_execution_cost (called by optimizer.py:543; the in-memory
#     execution-cost penalty path in options_scanner.py also routes
#     through this when ExecutionService is available). The history
#     branch was removed because the underlying drag-stats query path
#     was deleted; the function now always uses the heuristic fallback.
#
# Callers updated in same PR:
#   - options_scanner.py: removed get_batch_execution_drag_stats batch
#     fetch (always returned {}); drag_map stays {}; downstream
#     `stats = drag_map.get(symbol)` already handled None gracefully.


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

    def estimate_execution_cost(
        self,
        symbol: str,
        spread_pct: float | None = None,
        user_id: str | None = None,
        entry_cost: float | None = None,
        num_legs: int | None = None,
    ) -> float:
        """Returns estimated execution cost (drag) per share/contract.

        Heuristic spread proxy:
            cost = (Spread × 0.5) + (Legs × Fees)

        The historical-data branch (previously routed through
        get_execution_drag_stats → get_batch_execution_drag_stats →
        trade_executions) was removed in #62a-D8 sweep — the
        trade_executions table had zero rows for its entire lifetime,
        so the heuristic was the only branch that ever fired in
        practice. user_id is preserved on the signature for caller
        compatibility but no longer used.
        """
        if spread_pct is None:
            spread_pct = 0.005  # 0.5% default assumption

        # Precise formula match for scanner equivalence:
        #   Cost = (Entry × Spread% × 0.5) + (Legs × 0.0065)
        # Return value is per-CONTRACT dollars (×100 for options spread).
        # entry_cost is per-share total premium (e.g. 1.50).
        # num_legs × 0.0065 is per-share fees (assuming $0.65/contract).
        if entry_cost is not None and num_legs is not None:
            spread_value = abs(entry_cost) * spread_pct
            share_cost = (spread_value * 0.5) + (num_legs * 0.0065)
            return share_cost * 100.0

        # Legacy default when trade structure unknown.
        # 5 cents/share = $5.00/contract.
        return 5.0
